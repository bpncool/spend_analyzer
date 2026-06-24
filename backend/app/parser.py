import io
import re
from datetime import datetime, date
from typing import List, Dict, Any, Optional
import pandas as pd
import pdfplumber
from google.genai import types
from google.genai.errors import APIError

from .categorizer import gemini_client
from .schemas import AIParsingResponse
from .rate_limiter import is_ai_rate_limited, trigger_ai_rate_limit, should_send_notification
from .agents.utility_agents import send_notification_email

def _is_rate_limit_error(e: Exception) -> bool:
    """Helper to detect if an exception represents an API rate limit error."""
    if isinstance(e, APIError):
        return e.code == 429 or e.status == "RESOURCE_EXHAUSTED" or (e.message and "RESOURCE_EXHAUSTED" in e.message)
    code = getattr(e, "code", None)
    status_attr = getattr(e, "status", None)
    msg = str(e)
    return code == 429 or status_attr == "RESOURCE_EXHAUSTED" or "RESOURCE_EXHAUSTED" in msg or "429" in msg


def clean_amount(val: Any) -> float:
    """Helper to convert string amounts with commas, currency symbols, or parentheses to float."""
    if pd.isna(val) or val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    
    val_str = str(val).strip()
    if not val_str:
        return 0.0
    
    # Check for negative in parentheses e.g. ($100.00) or (100.00)
    is_negative = False
    if val_str.startswith('(') and val_str.endswith(')'):
        is_negative = True
        val_str = val_str[1:-1]
        
    # Remove currency symbols and commas
    val_str = re.sub(r'[^\d\.\-]', '', val_str)
    
    try:
        amount = float(val_str)
        return -amount if is_negative else amount
    except ValueError:
        return 0.0

def parse_date(date_str: str) -> Optional[date]:
    """Tries parsing various date formats common in bank statements."""
    if not date_str or not isinstance(date_str, str):
        return None
    
    # Strip ordinal suffixes like 1st, 2nd, 3rd, 4th
    clean_str = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_str.strip())
    
    formats = [
        "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y",
        "%d/%m/%y", "%m/%d/%y", "%d-%m-%y",
        "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
        "%d-%b-%y", "%d-%b-%Y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(clean_str, fmt).date()
        except ValueError:
            continue
    return None

def post_process_transactions(raw_rows: List[Dict[str, Any]], opening_balance: Optional[float] = None) -> List[Dict[str, Any]]:
    """
    Standardized post-processing for all transaction rows.
    Calculates signed amount based on prioritized metrics:
    1. Explicit Debit and Credit values (highest priority)
    2. Explicit raw amount with Balance Delta for sign determination
    3. Balance Delta alone
    4. Heuristics on descriptions as fallback
    """
    transactions = []
    
    for i in range(len(raw_rows)):
        current = raw_rows[i]
        
        debit = abs(current.get("debit", 0.0))
        credit = abs(current.get("credit", 0.0))
        balance = current.get("balance")
        raw_amount = current.get("raw_amount", 0.0)
        description = current.get("description", "")
        
        amount = 0.0
        
        # Priority 1: Explicit debit/credit columns
        if debit != 0.0 or credit != 0.0:
            amount = credit - debit
        # Priority 2: Single raw amount column with a balance column
        elif raw_amount != 0.0:
            if balance is not None:
                prev_balance = raw_rows[i-1]["balance"] if i > 0 else opening_balance
                if prev_balance is not None:
                    delta = balance - prev_balance
                    # Sign of delta determines the sign of raw_amount
                    amount = -abs(raw_amount) if delta < 0 else abs(raw_amount)
                else:
                    # Fallback to heuristics
                    desc_lower = description.lower()
                    is_deposit = any(k in desc_lower for k in ["salary", "deposit", "interest", "credit", "transfer in", "incoming", "refund", "dep"])
                    is_withdrawal = any(k in desc_lower for k in ["payment", "purchase", "withdrawal", "fee", "transfer out", "card", "uber", "kroger", "starbucks", "netflix", "atm", "debit", "wd", "pay"])
                    if is_deposit:
                        amount = abs(raw_amount)
                    elif is_withdrawal:
                        amount = -abs(raw_amount)
                    else:
                        amount = raw_amount
            else:
                # No balance, use heuristics
                desc_lower = description.lower()
                is_deposit = any(k in desc_lower for k in ["salary", "deposit", "interest", "credit", "transfer in", "incoming", "refund", "dep"])
                is_withdrawal = any(k in desc_lower for k in ["payment", "purchase", "withdrawal", "fee", "transfer out", "card", "uber", "kroger", "starbucks", "netflix", "atm", "debit", "wd", "pay"])
                if is_deposit:
                    amount = abs(raw_amount)
                elif is_withdrawal:
                    amount = -abs(raw_amount)
                else:
                    amount = raw_amount
        # Priority 3: Only balance column is available
        elif balance is not None:
            prev_balance = raw_rows[i-1]["balance"] if i > 0 else opening_balance
            if prev_balance is not None:
                amount = balance - prev_balance
                
        # Round final values to 2 decimal places to avoid floating point representations
        amount = round(amount, 2)
        balance_after = round(balance, 2) if balance is not None else None
        
        transactions.append({
            "date": current["date"],
            "description": description,
            "amount": amount,
            "balance_after": balance_after,
            "raw_payload": current.get("raw_payload") or current.get("row_dict") or {}
        })
        
    return transactions

def parse_generic_csv_statement(file_bytes: bytes) -> List[Dict[str, Any]]:
    """Reads a CSV statement and maps it to standard transaction columns."""
    df = pd.read_csv(io.BytesIO(file_bytes))
    
    # Auto-detect columns
    col_mapping = {}
    for col in df.columns:
        col_lower = str(col).lower()
        if "date" in col_lower and "value" not in col_lower:
            col_mapping["date"] = col
        elif "desc" in col_lower or "narration" in col_lower or "transaction" in col_lower or "particulars" in col_lower:
            col_mapping["description"] = col
        elif "amount" in col_lower:
            col_mapping["amount"] = col
        elif "debit" in col_lower:
            col_mapping["debit"] = col
        elif "credit" in col_lower:
            col_mapping["credit"] = col
        elif "balance" in col_lower:
            col_mapping["balance"] = col
        elif "withdrawal_or_deposit" in col_lower or "value" in col_lower:
            col_mapping["withdrawal_or_deposit"] = col
        elif "type" in col_lower:
            col_mapping["type"] = col
            
    # Verify minimal columns
    if "date" not in col_mapping or ("description" not in col_mapping and "narration" not in col_mapping):
        desc_col = next((c for c in df.columns if "desc" in c.lower() or "narr" in c.lower() or "trans" in c.lower()), None)
        if desc_col:
            col_mapping["description"] = desc_col
        else:
            raise ValueError("Could not auto-detect Date and Description columns in CSV.")
        
    opening_balance = None
    # Scan for opening balance in CSV rows before filtering
    for _, row in df.iterrows():
        row_str = " ".join([str(val) for val in row.values]).lower()
        if "opening balance" in row_str or "balance b/f" in row_str or "bal b/f" in row_str:
            if "balance" in col_mapping:
                opening_balance = clean_amount(row[col_mapping["balance"]])
                if opening_balance != 0.0:
                    break
            for val in reversed(row.values):
                amt = clean_amount(val)
                if amt != 0.0:
                    opening_balance = amt
                    break
            if opening_balance:
                break
                
    raw_rows = []
    
    for _, row in df.iterrows():
        raw_date = row[col_mapping["date"]]
        parsed_date = parse_date(str(raw_date))
        if not parsed_date:
            continue  # Skip header or invalid rows
            
        desc_parts = []
        if "type" in col_mapping:
            t_val = str(row[col_mapping["type"]]).strip()
            if t_val and t_val.lower() != "nan":
                desc_parts.append(t_val)
        desc_val = str(row.get(col_mapping.get("description", ""))).strip()
        if desc_val and desc_val.lower() != "nan":
            desc_parts.append(desc_val)
        desc = " - ".join(desc_parts) if desc_parts else "Unknown Transaction"
        
        if not desc or desc.lower() == "nan" or desc.lower() == "opening balance" or desc.lower() == "closing balance":
            continue
            
        debit_val = clean_amount(row[col_mapping["debit"]]) if "debit" in col_mapping else 0.0
        credit_val = clean_amount(row[col_mapping["credit"]]) if "credit" in col_mapping else 0.0
        amount_val = 0.0
        
        if "amount" in col_mapping:
            amount_val = clean_amount(row[col_mapping["amount"]])
        elif "withdrawal_or_deposit" in col_mapping:
            amount_val = clean_amount(row[col_mapping["withdrawal_or_deposit"]])
            
        balance = None
        if "balance" in col_mapping:
            balance = clean_amount(row[col_mapping["balance"]])
            
        raw_rows.append({
            "date": parsed_date,
            "description": desc,
            "debit": debit_val,
            "credit": credit_val,
            "raw_amount": amount_val,
            "balance": balance,
            "row_dict": row.to_dict()
        })
        
    return post_process_transactions(raw_rows, opening_balance)

def parse_hdfc_bank_txt_statement(file_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parses fixed-width/structured TXT statements (HDFC layout) based on the logic in
    read_account_statement.py.
    """
    try:
        content = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = file_bytes.decode("latin-1", errors="ignore")
        
    lines = content.split("\n")
    
    # Step 1: Scan for opening balance in the text lines (with next-line fallback for summary block)
    opening_balance = None
    for idx, line in enumerate(lines):
        line_lower = line.lower()
        if "opening balance" in line_lower or "balance b/f" in line_lower or "bal b/f" in line_lower or "brought forward" in line_lower:
            numbers = re.findall(r'[\d,]+\.\d{2}', line)
            if numbers:
                opening_balance = clean_amount(numbers[-1])
                break
            for offset in range(1, 3):
                if idx + offset < len(lines):
                    next_line = lines[idx + offset]
                    next_numbers = re.findall(r'[\d,]+\.\d{2}', next_line)
                    if next_numbers:
                        opening_balance = clean_amount(next_numbers[0])
                        break
            if opening_balance is not None:
                break

    # Step 2: Extract transaction lines
    border_counter = 0
    table_indexes = []
    for i in range(len(lines)):
        line = lines[i]
        if "-------------" in line:
            border_counter += 1
            if border_counter % 2 == 0:
                table_indexes += [i+1]
        if "**Continue**" in line:
            table_indexes += [i-1]
        if "**********" in line:
            table_indexes += [i-1]
            break
            
    # Extract table lines
    table = []
    if len(table_indexes) >= 2:
        for i in range(0, len(table_indexes), 2):
            if i + 1 < len(table_indexes):
                table += lines[table_indexes[i]:table_indexes[i+1]]
    else:
        table = lines
        
    # Reconstruct multi-line descriptions and parse columns cleanly
    raw_rows = []
    current_tx = None
    
    for line in table:
        cleaned_line = line.replace("\r", "").replace("\n", "")
        if cleaned_line.strip() == "":
            continue
            
        date_str = cleaned_line[0:8].strip()
        parsed_date = parse_date(date_str)
        
        if parsed_date:
            if current_tx:
                raw_rows.append(current_tx)
                
            sale_split = re.split(r" |-", cleaned_line[8:52].strip(), 1)
            tx_type = sale_split[0] if len(sale_split) > 1 else ""
            tx_desc = sale_split[1] if len(sale_split) > 1 else sale_split[0]
            
            line_rest = cleaned_line[53:]
            rest_processed = re.sub(r'\s{2,}', '\t', re.sub(r'(?<! ) (?! )', '_', line_rest))
            other_table_cols = [c.strip() for c in rest_processed.split("\t") if c.strip()]
            
            if len(other_table_cols) >= 2:
                balance_str = other_table_cols[-1]
                amt_str = other_table_cols[-2]
                
                balance = clean_amount(balance_str)
                raw_amount = clean_amount(amt_str)
                
                desc_parts = [tx_type, tx_desc]
                desc = " - ".join([p.strip() for p in desc_parts if p.strip()])
                
                current_tx = {
                    "date": parsed_date,
                    "description": desc,
                    "debit": 0.0,
                    "credit": 0.0,
                    "raw_amount": raw_amount,
                    "balance": balance,
                    "raw_payload": {"raw_line": cleaned_line}
                }
        else:
            if current_tx and len(cleaned_line) > 7:
                continuation_text = cleaned_line.strip()
                if continuation_text:
                    current_tx["description"] += " " + continuation_text

    if current_tx:
        raw_rows.append(current_tx)
        
    return post_process_transactions(raw_rows, opening_balance)

def parse_axis_bank_pdf_statement(file_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Extracts transaction tables from Axis Bank statement PDFs.
    Detects Debit, Credit, and Balance columns to parse signed amounts accurately.
    """
    raw_rows = []
    opening_balance = None
    
    # Initialize column indexes to standard defaults for Axis Bank statement format
    date_idx = 0
    desc_idx = 2
    debit_idx = 3
    credit_idx = 4
    balance_idx = 5
    amount_idx = -1
    
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        # Step 1: Scan for opening balance first across all pages/tables
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    for row in table:
                        cleaned_row = [str(cell).strip() if cell is not None else "" for cell in row]
                        row_str = " ".join(cleaned_row).lower()
                        if "opening balance" in row_str or "balance b/f" in row_str or "bal b/f" in row_str:
                            for cell in reversed(cleaned_row):
                                val = clean_amount(cell)
                                if val != 0.0:
                                    opening_balance = val
                                    break
                            if opening_balance is not None:
                                break
                    if opening_balance is not None:
                        break
            if opening_balance is not None:
                break
                
        # Step 2: Extract transactions
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    if len(table) == 0:
                        continue
                    
                    # Detect if table[0] is a header row
                    is_header = False
                    header_cells = [str(cell).lower().replace("\n", " ") if cell is not None else "" for cell in table[0]]
                    if any("date" in cell or "particular" in cell or "debit" in cell or "credit" in cell or "balance" in cell for cell in header_cells):
                        is_header = True
                        
                    if is_header:
                        # Auto-detect headers from this header row
                        for idx, cell in enumerate(header_cells):
                            if "date" in cell and "val" not in cell:
                                date_idx = idx
                            elif "particular" in cell or "desc" in cell or "narration" in cell or "detail" in cell:
                                desc_idx = idx
                            elif "debit" in cell or "withdrawal" in cell or "payment" in cell:
                                debit_idx = idx
                            elif "credit" in cell or "deposit" in cell or "received" in cell:
                                credit_idx = idx
                            elif "balance" in cell:
                                balance_idx = idx
                            elif "amount" in cell or "value" in cell:
                                amount_idx = idx
                        rows_to_process = table[1:]
                    else:
                        rows_to_process = table
                        
                    for row in rows_to_process:
                        cleaned_row = [str(cell).strip() if cell is not None else "" for cell in row]
                        if len(cleaned_row) <= max(date_idx, desc_idx):
                            continue
                            
                        date_str = cleaned_row[date_idx]
                        parsed_date = parse_date(date_str)
                        if not parsed_date:
                            continue
                            
                        desc = cleaned_row[desc_idx]
                        if desc.lower() == "opening balance" or desc.lower() == "closing balance" or "balance b/f" in desc.lower() or "transaction total" in desc.lower():
                            continue
                            
                        debit_val = clean_amount(cleaned_row[debit_idx]) if debit_idx != -1 and debit_idx < len(cleaned_row) else 0.0
                        credit_val = clean_amount(cleaned_row[credit_idx]) if credit_idx != -1 and credit_idx < len(cleaned_row) else 0.0
                        amount_val = clean_amount(cleaned_row[amount_idx]) if amount_idx != -1 and amount_idx < len(cleaned_row) else 0.0
                        balance = clean_amount(cleaned_row[balance_idx]) if balance_idx != -1 and balance_idx < len(cleaned_row) else None
                        
                        raw_rows.append({
                            "date": parsed_date,
                            "description": desc,
                            "debit": debit_val,
                            "credit": credit_val,
                            "raw_amount": amount_val,
                            "balance": balance,
                            "raw_payload": {"raw_row": cleaned_row}
                        })
            else:
                # Text fallback regex logic if no tables are extracted
                text = page.extract_text()
                if not text:
                    continue
                for line in text.split("\n"):
                    match = re.search(r'^(\d{1,2}[-/ ]\w{3,9}[-/ ]\d{2,4})\s+(.*?)\s+(-?\d+[\.,]\d{2})\s*(-?\d+[\.,]\d{2})?$', line)
                    if match:
                        date_str, desc, amount_str, balance_str = match.groups()
                        parsed_date = parse_date(date_str)
                        if parsed_date:
                            raw_amount = clean_amount(amount_str)
                            balance = clean_amount(balance_str) if balance_str else None
                            raw_rows.append({
                                "date": parsed_date,
                                "description": desc.strip(),
                                "debit": 0.0,
                                "credit": 0.0,
                                "raw_amount": raw_amount,
                                "balance": balance,
                                "raw_payload": {"raw_line": line}
                            })
                            
    return post_process_transactions(raw_rows, opening_balance)

async def parse_statement_with_gemini(file_content_text: str) -> List[Dict[str, Any]]:
    """
    Fallback GenAI Statement Parser:
    Queries Gemini utilizing Structured Outputs to parse statement text
    and extract date, description, amount, and running balance fields.
    """
    if not gemini_client:
        raise ValueError("Gemini API client is not initialized. Ensure GEMINI_API_KEY is configured.")
        
    if is_ai_rate_limited():
        raise ValueError("AI Parsing is temporarily rate-limited.")
        
    system_instruction = (
        "You are an expert bank statement auditing assistant. Your task is to extract "
        "all transaction rows from the provided bank statement text. "
        "Convert each transaction to a structured JSON object. "
        "Crucial: Ensure amounts are signed (negative for debits/withdrawals, positive for deposits/credits)."
    )
    
    prompt = f"""
    Please extract the transaction table from this bank statement text:
    ---
    {file_content_text}
    ---
    
    Format the output as a JSON object containing a list of transaction items.
    Ensure dates are in 'YYYY-MM-DD' format. If years are not explicitly mentioned next to transactions,
    infer it from the statement header or period.
    """
    
    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=AIParsingResponse,
                temperature=0.0,
            )
        )
    except Exception as e:
        print(f"Gemini statement parsing failed: {e}")
        if _is_rate_limit_error(e):
            trigger_ai_rate_limit(5)
            if should_send_notification():
                send_notification_email(
                    "Spend Analyzer: Gemini API Rate Limit Triggered",
                    "The Gemini API rate limit has been reached (429/RESOURCE_EXHAUSTED). The system is falling back to local rule and vector similarity matching."
                )
        raise ValueError("AI Parsing is temporarily rate-limited.") from e
        
    result = AIParsingResponse.model_validate_json(response.text)
    
    parsed_txs = []
    for tx in result.transactions:
        parsed_date = parse_date(tx.date)
        if not parsed_date:
            continue
        parsed_txs.append({
            "date": parsed_date,
            "description": tx.description,
            "amount": round(tx.amount, 2),
            "balance_after": round(tx.balance_after, 2) if tx.balance_after is not None else None,
            "raw_payload": {"ai_parsed": True}
        })
        
    return parsed_txs


def detect_bank_from_pdf(file_bytes: bytes) -> str:
    """Detects the originating bank layout for PDF statement uploads."""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if pdf.pages:
                text = pdf.pages[0].extract_text() or ""
                text_lower = text.lower()
                if "axis" in text_lower or "utib" in text_lower:
                    return "axis"
    except Exception:
        pass
    return "unknown"

def detect_bank_from_txt(file_bytes: bytes) -> str:
    """Detects the originating bank layout for TXT statement uploads."""
    try:
        content = file_bytes.decode("utf-8", errors="ignore")
    except Exception:
        content = file_bytes.decode("latin-1", errors="ignore")
    content_lower = content.lower()
    if "hdfc" in content_lower:
        return "hdfc"
    return "unknown"

def detect_bank_from_csv(file_bytes: bytes) -> str:
    """Detects the originating bank layout for CSV statement uploads."""
    try:
        content = file_bytes.decode("utf-8", errors="ignore")
    except Exception:
        content = file_bytes.decode("latin-1", errors="ignore")
    content_lower = content.lower()
    if "axis" in content_lower or "utib" in content_lower:
        return "axis"
    elif "hdfc" in content_lower:
        return "hdfc"
    return "generic"


# =============================================================================
# Dynamic Custom Parser Registry
# =============================================================================
DYNAMIC_PARSERS = {}

def register_custom_parser(format_name: str, detect_fn, parse_fn):
    """Registers a dynamic parser format with its format detector and parsing functions."""
    DYNAMIC_PARSERS[format_name] = {
        "detect": detect_fn,
        "parse": parse_fn
    }

def detect_bank_from_custom(file_bytes: bytes) -> Optional[str]:
    """Checks if any dynamically registered custom parser matches the file content."""
    if not DYNAMIC_PARSERS:
        return None
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if pdf.pages:
                text = "\n".join([page.extract_text() or "" for page in pdf.pages[:2]])
    except Exception:
        try:
            text = file_bytes.decode("utf-8", errors="ignore")
        except Exception:
            try:
                text = file_bytes.decode("latin-1", errors="ignore")
            except Exception:
                text = ""

    text_lower = text.lower()
    for format_name, fns in DYNAMIC_PARSERS.items():
        try:
            if fns["detect"](text) or fns["detect"](text_lower):
                return format_name
        except Exception:
            continue
    return None

def load_and_register_saved_parsers():
    """Scans the custom_parsers directory and registers any existing files."""
    import os
    import importlib
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    custom_parsers_dir = os.path.join(current_dir, "custom_parsers")
    if not os.path.exists(custom_parsers_dir):
        return
        
    for filename in os.listdir(custom_parsers_dir):
        if filename.startswith("custom_") and filename.endswith(".py"):
            module_name = filename[:-3]
            try:
                # Relative import since it's within the package
                module = importlib.import_module(f".custom_parsers.{module_name}", package=__package__)
                if hasattr(module, "detect_format") and hasattr(module, "parse_statement"):
                    format_name = module_name
                    register_custom_parser(
                        format_name,
                        module.detect_format,
                        module.parse_statement
                    )
                    print(f"Dynamically registered parser: {format_name}")
            except Exception as e:
                print(f"Failed to load dynamic parser {module_name}: {e}")

# Run autoloader
load_and_register_saved_parsers()

# === REGISTERED CUSTOM PARSERS ===

