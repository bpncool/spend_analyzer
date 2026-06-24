import os
import io
import json
from google.antigravity import Agent, LocalAgentConfig
from .utility_agents import persist_transactions_to_db, send_notification_email, log_run_step
from ..parser import (
    detect_bank_from_pdf, detect_bank_from_txt, detect_bank_from_csv,
    parse_axis_bank_pdf_statement, parse_hdfc_bank_txt_statement, parse_generic_csv_statement
)

# =============================================================================
# Tools for Document Parser Agent
# =============================================================================

def detect_statement_format(file_path: str) -> str:
    """Reads a file and detects its bank statement format layout.
    Args:
        file_path: The absolute path of the statement file on disk.
    Returns:
        One of 'axis_pdf', 'hdfc_txt', 'generic_csv', a registered custom parser name, or 'unknown'.
    """
    if not os.path.exists(file_path):
        return "error: file not found"
        
    filename = file_path.lower()
    try:
        with open(file_path, "rb") as f:
            content = f.read()
            
        if filename.endswith(".pdf"):
            bank = detect_bank_from_pdf(content)
            if bank == "axis":
                return "axis_pdf"
        elif filename.endswith(".txt"):
            bank = detect_bank_from_txt(content)
            if bank == "hdfc":
                return "hdfc_txt"
        elif filename.endswith(".csv"):
            bank = detect_bank_from_csv(content)
            if bank in ("axis", "hdfc", "generic"):
                return "generic_csv"

        # Try dynamic custom parser detection
        from ..parser import detect_bank_from_custom
        custom_bank = detect_bank_from_custom(content)
        if custom_bank:
            return custom_bank
    except Exception as e:
         return f"error: {str(e)}"
         
    return "unknown"

def parse_and_persist_statement(file_path: str, format_type: str) -> str:
    """Parses a recognized statement file and persists its transactions to the database.
    Args:
        file_path: The absolute path of the statement file.
        format_type: The format code.
    Returns:
        A success summary message or error.
    """
    if not os.path.exists(file_path):
        return "error: file not found"
        
    try:
        with open(file_path, "rb") as f:
            content = f.read()
            
        parsed_txs = []
        source_type = ""
        account_name = ""
        
        from ..parser import DYNAMIC_PARSERS

        if format_type == "axis_pdf":
            parsed_txs = parse_axis_bank_pdf_statement(content)
            source_type = "axis_bank_pdf_agent_upload"
            account_name = "Axis Bank Pdf Statement"
        elif format_type == "hdfc_txt":
            parsed_txs = parse_hdfc_bank_txt_statement(content)
            source_type = "hdfc_bank_txt_agent_upload"
            account_name = "Hdfc Bank Txt Statement"
        elif format_type == "generic_csv":
            parsed_txs = parse_generic_csv_statement(content)
            source_type = "generic_csv_agent_upload"
            account_name = "Generic Csv Statement"
        elif format_type in DYNAMIC_PARSERS:
            parsed_txs = DYNAMIC_PARSERS[format_type]["parse"](content)
            source_type = f"{format_type}_agent_upload"
            account_name = f"{format_type.replace('_', ' ').title()} Statement"
        else:
            return "error: unsupported format type"
            
        # Serialize list of dicts to pass to database utility
        serializable_txs = []
        for tx in parsed_txs:
            serializable_txs.append({
                "date": str(tx["date"]),
                "description": tx["description"],
                "amount": float(tx["amount"]),
                "balance_after": float(tx["balance_after"]) if tx.get("balance_after") is not None else None
            })
            
        result = persist_transactions_to_db(json.dumps(serializable_txs), account_name, source_type)
        return result
    except Exception as e:
        return f"error: {str(e)}"

def notify_missing_parser(file_path: str) -> str:
    """Dispatches a notification email to the human administrator when a file format is unsupported.
    Args:
        file_path: Absolute path to the file requesting a parser.
    Returns:
        A confirmation status message.
    """
    basename = os.path.basename(file_path)
    subject = f"Parser Creation Required: Unknown Bank Statement layout for {basename}"
    body = (
        f"Hello Admin,\n\n"
        f"The autonomous statement agentic pipeline has detected a new statement file that "
        f"could not be parsed by any existing standard code parsers.\n\n"
        f"File Details:\n"
        f"- Path: {file_path}\n"
        f"- Name: {basename}\n\n"
        f"Please define an appropriate parser function in app/parser.py and update detect_bank_from_pdf/txt/csv accordingly.\n\n"
        f"Best,\n"
        f"Personal Finance Orchestrator Agent"
    )
    return send_notification_email(subject, body)

# =============================================================================
# Agent Config and Exec Runner
# =============================================================================

class UnknownLayoutException(Exception):
    """Raised when the document parser agent encounters an unrecognized format layout."""
    pass

async def run_parser_agent(file_path: str, run_id: str, raise_on_unknown: bool = False) -> bool:
    """Orchestrates Super Agent 1 task to parse a statement.
    Returns True if successfully parsed, False if parsing failed.
    Raises UnknownLayoutException if layout is unknown and raise_on_unknown is True.
    """
    log_run_step(run_id, "parsing", f"Document Parser Agent checking statement: {os.path.basename(file_path)}")
    
    # Track the detection and parsing results
    _result = {"parsed": False}
    _detected_format = {"format": "unknown"}
    
    def detect_statement_format_tracked() -> str:
        """Reads the statement file and detects its bank statement format layout."""
        fmt = detect_statement_format(file_path)
        _detected_format["format"] = fmt
        return fmt
    
    def parse_and_persist_statement_tracked(format_type: str) -> str:
        """Parses the statement file and persists its transactions to the database.
        Args:
            format_type: The detected format code.
        """
        result = parse_and_persist_statement(file_path, format_type)
        if not result.startswith("error"):
            _result["parsed"] = True
        return result
    
    config = LocalAgentConfig(
        system_instructions=(
            "You are Super Agent 1 (Document Parser). Your task is to process the bank statement file. "
            "1. First, call `detect_statement_format_tracked` to find out what format the file is. "
            "2. If it returns 'axis_pdf', 'hdfc_txt', 'generic_csv', or any custom format (starting with 'custom_'), "
            "   parse the statement by calling `parse_and_persist_statement_tracked`. "
            "3. If it returns 'unknown' or an error, keep your final response clear that a new parser is required."
        ),
        tools=[detect_statement_format_tracked, parse_and_persist_statement_tracked]
    )
    
    async with Agent(config) as agent:
        prompt = f"Process the statement file located at: {file_path}"
        response = await agent.chat(prompt)
        text_out = await response.text()
        
        log_run_step(run_id, "parsing", f"Document Parser Agent result: {text_out}")
        
        if _result["parsed"]:
            return True
        if "successfully processed" in text_out.lower() or "saved" in text_out.lower():
            return True
        if _detected_format["format"] == "unknown":
            if raise_on_unknown:
                raise UnknownLayoutException("Unrecognized statement layout format.")
            else:
                notify_missing_parser(file_path)
                return False
        return False

