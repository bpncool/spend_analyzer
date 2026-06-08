import pytest
from datetime import date
from backend.app.parser import (
    clean_amount, parse_date, parse_generic_csv_statement, parse_axis_bank_pdf_statement,
    detect_bank_from_pdf, detect_bank_from_txt, detect_bank_from_csv
)

def test_clean_amount():
    assert clean_amount("1,234.56") == 1234.56
    assert clean_amount("$100.00") == 100.00
    assert clean_amount("-50.25") == -50.25
    assert clean_amount("(150.00)") == -150.00
    assert clean_amount("  ") == 0.0
    assert clean_amount(None) == 0.0
    assert clean_amount(250) == 250.0

def test_parse_date():
    assert parse_date("2026-05-25") == date(2026, 5, 25)
    assert parse_date("25-05-2026") == date(2026, 5, 25)
    assert parse_date("05/25/2026") == date(2026, 5, 25)
    assert parse_date("25/05/2026") == date(2026, 5, 25)
    assert parse_date("25 May 2026") == date(2026, 5, 25)
    assert parse_date("25th May 2026") == date(2026, 5, 25)
    assert parse_date("May 25, 2026") == date(2026, 5, 25)
    assert parse_date("invalid-date") is None

def test_parse_csv_statement():
    csv_content = (
        "Date,Description,Amount,Balance\n"
        "2026-05-01,Salary,5000.00,5000.00\n"
        "2026-05-02,Uber Trip,-25.50,4974.50\n"
        "2026-05-03,Kroger Grocery,-150.00,4824.50\n"
    ).encode("utf-8")
    
    txs = parse_generic_csv_statement(csv_content)
    assert len(txs) == 3
    assert txs[0]["date"] == date(2026, 5, 1)
    assert txs[0]["description"] == "Salary"
    assert txs[0]["amount"] == 5000.00
    assert txs[0]["balance_after"] == 5000.00
    
    assert txs[1]["description"] == "Uber Trip"
    assert txs[1]["amount"] == -25.50
    assert txs[1]["balance_after"] == 4974.50

def test_parse_axis_bank_pdf():
    # Read the local Axis reference statement PDF file
    import os
    pdf_path = os.path.join(os.path.dirname(__file__), "Account_stmt.pdf")
    assert os.path.exists(pdf_path), f"Reference PDF statement not found at {pdf_path}"
    
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()
        
    txs = parse_axis_bank_pdf_statement(file_bytes)
    
    # Verify we successfully extracted transactions
    assert len(txs) > 0
    
    # Row 1 of data: Date 26-08-2025, Particulars "No Sal Credit Chrgs Incl GST", Debit 118.00, Credit empty, Balance 33346.34
    assert txs[0]["date"] == date(2025, 8, 26)
    assert txs[0]["description"] == "No Sal Credit Chrgs Incl GST"
    assert txs[0]["amount"] == -118.00
    assert txs[0]["balance_after"] == 33346.34
    
    # Row 2 of data: Date 26-08-2025, Particulars contains "BHAVESH PACHNANDA", Debit 20000.00, Credit empty, Balance 13346.34
    assert txs[1]["date"] == date(2025, 8, 26)
    assert "BHAVESH" in txs[1]["description"]
    assert txs[1]["amount"] == -20000.00
    assert txs[1]["balance_after"] == 13346.34
    
    # Row 3 of data: Date 29-08-2025, Particulars contains "IMPS/P2A", Debit empty, Credit 20000.00, Balance 33346.34
    assert txs[2]["date"] == date(2025, 8, 29)
    assert txs[2]["amount"] == 20000.00
    assert txs[2]["balance_after"] == 33346.34

def test_detect_bank_from_pdf():
    import os
    pdf_path = os.path.join(os.path.dirname(__file__), "Account_stmt.pdf")
    assert os.path.exists(pdf_path)
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()
    
    assert detect_bank_from_pdf(file_bytes) == "axis"
    assert detect_bank_from_pdf(b"Dummy empty PDF contents") == "unknown"

def test_detect_bank_from_txt():
    hdfc_txt = b"This is a dummy statement for HDFC BANK containing transactions..."
    unknown_txt = b"This is an unknown bank statement layout..."
    
    assert detect_bank_from_txt(hdfc_txt) == "hdfc"
    assert detect_bank_from_txt(unknown_txt) == "unknown"

def test_detect_bank_from_csv():
    axis_csv = b"date,particulars,debit,credit,balance,axis bank statement"
    hdfc_csv = b"date,particulars,debit,credit,balance,hdfc bank statement"
    generic_csv = b"date,particulars,debit,credit,balance"
    
    assert detect_bank_from_csv(axis_csv) == "axis"
    assert detect_bank_from_csv(hdfc_csv) == "hdfc"
    assert detect_bank_from_csv(generic_csv) == "generic"
