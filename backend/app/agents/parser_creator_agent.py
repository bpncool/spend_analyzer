import os
import sys
import importlib
import traceback
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from google.genai import types

from ..config import settings
from ..categorizer import gemini_client
from ..parser import register_custom_parser, clean_amount, parse_date
from .utility_agents import log_run_step

# =============================================================================
# Pydantic response schema for Gemini Structured Output
# =============================================================================

class GeneratedParserResponse(BaseModel):
    format_name: str = Field(description="A unique snake_case name for this format starting with 'custom_'. Example: 'custom_icici_pdf' or 'custom_sbi_csv'")
    detect_keywords: List[str] = Field(description="List of 2 to 4 unique case-insensitive strings found in this statement text that uniquely identify the layout (e.g. specific headers or bank names)")
    python_code: str = Field(description="The complete Python code for parsing the statement. MUST define 'detect_format(file_text: str) -> bool' and 'parse_statement(file_bytes: bytes) -> List[Dict[str, Any]]'.")

# =============================================================================
# Agent Execution Logic
# =============================================================================

def extract_preview_text(file_path: str, max_chars: int = 2000) -> str:
    """Helper to extract text from PDF, CSV or TXT file for prompt context."""
    filename = file_path.lower()
    text = ""
    if filename.endswith(".pdf"):
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                parts = []
                for page in pdf.pages[:3]:  # get first few pages
                    t = page.extract_text()
                    if t:
                        parts.append(t)
                text = "\n".join(parts)
        except Exception as e:
            text = f"Error extracting PDF text: {str(e)}"
    else:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read(max_chars * 2)
        except Exception:
            try:
                with open(file_path, "r", encoding="latin-1", errors="ignore") as f:
                    text = f.read(max_chars * 2)
            except Exception as e:
                text = f"Error reading text file: {str(e)}"
                
    return text[:max_chars]

async def run_parser_creator_agent(file_path: str, run_id: str) -> bool:
    """Runs a code generation agent to build a custom parser for unknown statement formats.
    Returns True if successfully generated and validated, False otherwise.
    """
    log_run_step(run_id, "parsing", f"Parser Creator Agent: Starting parser generation for {os.path.basename(file_path)}")
    
    if not gemini_client:
        log_run_step(run_id, "failed", "Gemini Client not initialized.", "GEMINI_API_KEY is missing.")
        return False

    # Extract preview text
    preview_text = extract_preview_text(file_path, 2000)
    if not preview_text.strip():
        log_run_step(run_id, "failed", "Empty file preview. Cannot generate parser.", "Statement contains no readable text.")
        return False

    system_instruction = (
        "You are an expert software developer specializing in writing python data parsers. "
        "Your task is to write a self-contained python parsing module for a new bank statement layout. "
        "The module MUST export two functions:\n"
        "1. `detect_format(file_text: str) -> bool`: Returns True if the statement contains identifying keywords.\n"
        "2. `parse_statement(file_bytes: bytes) -> List[Dict[str, Any]]`: Parses the statement and returns a list "
        "of transaction dicts. Each dict must follow this schema exactly:\n"
        "   - 'date': datetime.date object (strongly preferred) or 'YYYY-MM-DD' string.\n"
        "   - 'description': string (narration).\n"
        "   - 'amount': float (negative for debit, positive for credit).\n"
        "   - 'balance_after': float (running balance) or None.\n\n"
        "Helper utilities:\n"
        "You can (and should) import `clean_amount` and `parse_date` from `app.parser` to clean numbers and parse dates:\n"
        "  `from app.parser import clean_amount, parse_date`\n"
        "Standard libraries available: pdfplumber, io, re, pandas, datetime, typing.\n"
        "Make sure to handle PDF tables or raw text lines cleanly. Ensure amounts are signed properly."
    )

    prompt = f"""
    Here are the first 2000 characters extracted from the unknown bank statement:
    ---
    {preview_text}
    ---

    Generate the parsing module code. Ensure the python code is ready to be written to a file and imported.
    Do not wrap the python code inside markdown backticks in the response fields.
    """

    attempts = 3
    feedback = ""
    
    # Define directories
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    custom_parsers_dir = os.path.join(current_dir, "custom_parsers")
    os.makedirs(custom_parsers_dir, exist_ok=True)
    
    temp_file_path = os.path.join(custom_parsers_dir, "temp_parser_validation.py")

    for attempt in range(1, attempts + 1):
        log_run_step(run_id, "parsing", f"Parser Creator Agent: Gemini generation attempt {attempt}/{attempts}")
        
        current_prompt = prompt
        if feedback:
            current_prompt += f"\n\nPrevious attempt failed validation tests with this error:\n{feedback}\nPlease fix the Python code and try again."

        try:
            response = gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=current_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=GeneratedParserResponse,
                    temperature=0.1,
                )
            )
            
            result = GeneratedParserResponse.model_validate_json(response.text)
        except Exception as e:
            log_run_step(run_id, "parsing", f"Gemini generation call failed: {str(e)}")
            feedback = f"Gemini API call / parse error: {str(e)}"
            continue

        format_name = result.format_name.strip()
        if not format_name.startswith("custom_"):
            format_name = f"custom_{format_name}"
            
        python_code = result.python_code

        # Write to temporary file
        try:
            with open(temp_file_path, "w", encoding="utf-8") as f:
                f.write(python_code)
        except Exception as e:
            feedback = f"Failed to write temp module file: {str(e)}"
            continue

        # Run Validation Tests
        log_run_step(run_id, "parsing", "Parser Creator Agent: Running validation tests on generated module...")
        try:
            # Clear sys.modules cache to force reload
            parent_package = __package__.rsplit('.', 1)[0] if __package__ else "app"
            module_key = f"{parent_package}.custom_parsers.temp_parser_validation"
            if module_key in sys.modules:
                del sys.modules[module_key]
                
            temp_module = importlib.import_module(".custom_parsers.temp_parser_validation", package=parent_package)
            
            # Check functions
            if not hasattr(temp_module, "detect_format"):
                raise ValueError("Generated python module is missing 'detect_format' function.")
            if not hasattr(temp_module, "parse_statement"):
                raise ValueError("Generated python module is missing 'parse_statement' function.")

            # Load actual file bytes to test
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            transactions = temp_module.parse_statement(file_bytes)
            
            if not isinstance(transactions, list):
                raise ValueError(f"parse_statement must return a List, got {type(transactions)}")
            if len(transactions) == 0:
                raise ValueError("parse_statement returned 0 transactions. Ensure table/row extraction is correct.")

            # Validate schema of transactions
            from datetime import date
            for idx, tx in enumerate(transactions):
                if not isinstance(tx, dict):
                    raise ValueError(f"Transaction index {idx} is not a dictionary.")
                for col in ["date", "description", "amount", "balance_after"]:
                    if col not in tx:
                        raise ValueError(f"Transaction index {idx} is missing required column: '{col}'")
                
                # Check date
                d = tx["date"]
                parsed_d = None
                if isinstance(d, str):
                    parsed_d = parse_date(d)
                elif isinstance(d, date):
                    parsed_d = d
                if not parsed_d:
                    raise ValueError(f"Transaction index {idx} has invalid date value/format: '{d}'")
                
                # Check desc
                if not isinstance(tx["description"], str) or not tx["description"].strip():
                    raise ValueError(f"Transaction index {idx} has invalid description: '{tx['description']}'")
                
                # Check amount
                try:
                    float(tx["amount"])
                except (TypeError, ValueError):
                    raise ValueError(f"Transaction index {idx} has invalid numeric amount: '{tx['amount']}'")

            # If we get here, validation is successful!
            log_run_step(run_id, "parsing", f"Parser Creator Agent: Validation passed! Generated {len(transactions)} transaction rows.")
            
            # Copy to permanent file
            perm_filename = f"{format_name}.py"
            perm_file_path = os.path.join(custom_parsers_dir, perm_filename)
            with open(perm_file_path, "w", encoding="utf-8") as f:
                f.write(python_code)
                
            # Clean up temp file
            try:
                os.remove(temp_file_path)
            except Exception:
                pass

            # Register dynamic parser to parser.py
            parser_file_path = os.path.join(current_dir, "parser.py")
            with open(parser_file_path, "r", encoding="utf-8") as f:
                parser_content = f.read()

            marker = "# === REGISTERED CUSTOM PARSERS ==="
            if marker in parser_content:
                registration_statement = (
                    f"\nfrom .custom_parsers import {format_name}\n"
                    f"register_custom_parser(\"{format_name}\", {format_name}.detect_format, {format_name}.parse_statement)\n"
                )
                parts = parser_content.split(marker)
                new_content = parts[0] + marker + registration_statement + parts[1]
                with open(parser_file_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                
                # Dynamically call the registration function in the current memory state as well
                register_custom_parser(format_name, temp_module.detect_format, temp_module.parse_statement)
                log_run_step(run_id, "parsing", f"Parser Creator Agent: Dynamically registered parser '{format_name}' in memory and parser.py.")
                return True
            else:
                log_run_step(run_id, "parsing", "Parser Creator Agent: Could not find parser.py registration marker. Falling back to dynamic autoloader.")
                # Fallback: the autoloader will load it on restart, but we register it now in memory
                register_custom_parser(format_name, temp_module.detect_format, temp_module.parse_statement)
                return True

        except Exception as e:
            tb = traceback.format_exc()
            log_run_step(run_id, "parsing", f"Parser Creator Agent: Validation failed on attempt {attempt}: {str(e)}")
            feedback = f"Error during parsing validation test:\n{str(e)}\n\nTraceback:\n{tb}"

    log_run_step(run_id, "parsing", "Parser Creator Agent: Failed all attempts to generate a valid parser function.")
    # Clean up temp file on absolute failure
    try:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
    except Exception:
        pass
    return False
