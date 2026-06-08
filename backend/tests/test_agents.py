import os
import json
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.orm import Session

from backend.app.database import SessionLocal, Base, engine
from backend.app.models import Transaction, Category, AgentRun
from backend.app.agents.utility_agents import (
    init_agent_run, log_run_step, fetch_historical_rules,
    fetch_historical_embeddings, persist_transactions_to_db,
    fetch_uncategorized_transactions, update_transaction_categories,
    send_notification_email
)
from backend.app.agents.parser_agent import (
    detect_statement_format, parse_and_persist_statement,
    notify_missing_parser, run_parser_agent
)
from backend.app.agents.mapper_agent import run_mapper_agent
from backend.app.agents.insights_agent import run_insights_agent
from backend.app.agents.frontend_agent import run_frontend_agent
from backend.app.agents.orchestrator import orchestrate_statement_processing
from backend.app.agents.triggers import scan_folder_manually, scan_emails_manually

# =============================================================================
# Pytest Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Seed predefined categories
        for name in ["Online Cab Service", "Grocery", "Bank Transfer", "Self-Transfers", "Others", "Drinks", "Food and Drinks outside"]:
            if not db.query(Category).filter(Category.name == name).first():
                db.add(Category(name=name, description=""))
        db.commit()
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

@pytest.fixture
def mock_dirs(tmp_path, monkeypatch):
    stmt_dir = tmp_path / "statements"
    email_dir = tmp_path / "emails"
    stmt_dir.mkdir()
    email_dir.mkdir()
    
    import backend.app.agents.triggers as triggers
    monkeypatch.setattr(triggers, "STATEMENTS_DIR", str(stmt_dir))
    monkeypatch.setattr(triggers, "EMAIL_INBOX_DIR", str(email_dir))
    
    return stmt_dir, email_dir

# =============================================================================
# Mock classes for google.antigravity Agent
# =============================================================================

class MockResponse:
    def __init__(self, text_val):
        self.text_val = text_val
    async def text(self):
        return self.text_val

class MockAgent:
    def __init__(self, response_text):
        self.response_text = response_text
    async def chat(self, prompt):
        return MockResponse(self.response_text)
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

# =============================================================================
# Tests
# =============================================================================

def test_detect_statement_format(tmp_path):
    # Test file doesn't exist
    assert detect_statement_format(str(tmp_path / "nonexistent.pdf")) == "error: file not found"
    
    # Test unknown formats
    unknown_pdf = tmp_path / "unknown.pdf"
    unknown_pdf.write_bytes(b"Dummy PDF content")
    with patch("backend.app.agents.parser_agent.detect_bank_from_pdf", return_value="unknown"):
        assert detect_statement_format(str(unknown_pdf)) == "unknown"
    
    unknown_txt = tmp_path / "unknown.txt"
    unknown_txt.write_bytes(b"Dummy TXT content")
    with patch("backend.app.agents.parser_agent.detect_bank_from_txt", return_value="unknown"):
        assert detect_statement_format(str(unknown_txt)) == "unknown"
    
    # Test valid formats
    axis_pdf = tmp_path / "axis.pdf"
    axis_pdf.write_bytes(b"Contains word axis in it")
    with patch("backend.app.agents.parser_agent.detect_bank_from_pdf", return_value="axis"):
        assert detect_statement_format(str(axis_pdf)) == "axis_pdf"
    
    hdfc_txt = tmp_path / "hdfc.txt"
    hdfc_txt.write_bytes(b"Contains word hdfc in it")
    with patch("backend.app.agents.parser_agent.detect_bank_from_txt", return_value="hdfc"):
        assert detect_statement_format(str(hdfc_txt)) == "hdfc_txt"
    
    generic_csv = tmp_path / "generic.csv"
    generic_csv.write_bytes(b"Date,Description,Amount,Balance\n")
    with patch("backend.app.agents.parser_agent.detect_bank_from_csv", return_value="generic"):
        assert detect_statement_format(str(generic_csv)) == "generic_csv"

def test_parse_and_persist_statement(tmp_path, setup_db):
    csv_file = tmp_path / "transactions.csv"
    csv_content = (
        "Date,Description,Amount,Balance\n"
        "2026-05-01,Salary,5000.00,5000.00\n"
        "2026-05-02,Uber Trip,-25.50,4974.50\n"
    )
    csv_file.write_text(csv_content)
    
    res = parse_and_persist_statement(str(csv_file), "generic_csv")
    assert "Saved 2 transactions" in res
    
    # Verify in DB
    txs = setup_db.query(Transaction).all()
    assert len(txs) == 2
    assert txs[0].description == "Salary"
    assert txs[0].amount == 5000.00
    assert txs[0].source == "generic_csv_agent_upload"
    assert txs[1].description == "Uber Trip"
    assert txs[1].amount == -25.50
    assert txs[1].source == "generic_csv_agent_upload"

def test_notify_missing_parser(tmp_path):
    # We remove notifications.jsonl first to start fresh
    notif_file = "/Users/bhaveshpachnanda/.gemini/antigravity/scratch/notifications.jsonl"
    if os.path.exists(notif_file):
        try:
            os.remove(notif_file)
        except Exception:
            pass
            
    res = notify_missing_parser(str(tmp_path / "invalid_layout.pdf"))
    assert "Mock email dispatched successfully" in res
    assert os.path.exists(notif_file)
    
    with open(notif_file, "r") as f:
        line = f.readline()
        data = json.loads(line)
        assert "invalid_layout.pdf" in data["subject"]

@pytest.mark.anyio
async def test_run_parser_agent_success(tmp_path, setup_db):
    csv_file = tmp_path / "transactions.csv"
    csv_file.write_text("Date,Description,Amount,Balance\n2026-05-01,Salary,5000.00,5000.00\n")
    
    run_id = init_agent_run("test_source")
    
    # Mock google.antigravity Agent to return success text
    mock_agent_class = lambda config: MockAgent("Successfully processed statement. Saved 1 transactions.")
    with patch("backend.app.agents.parser_agent.Agent", side_effect=mock_agent_class):
        success = await run_parser_agent(str(csv_file), run_id)
        assert success is True
        
    # Check that AgentRun log records the steps
    run = setup_db.query(AgentRun).filter(AgentRun.id == run_id).first()
    assert run is not None
    logs = json.loads(run.log_output)
    assert any("Parser Agent result" in l for l in logs)

@pytest.mark.anyio
async def test_run_parser_agent_unknown_fallback(tmp_path, setup_db):
    unknown_file = tmp_path / "unknown_stmt.txt"
    unknown_file.write_text("Invalid content structure")
    
    run_id = init_agent_run("test_source")
    
    # Mock Agent to return unknown / notification sent text
    mock_agent_class = lambda config: MockAgent("Layout is unknown. Dispatched email notification to admin.")
    with patch("backend.app.agents.parser_agent.Agent", side_effect=mock_agent_class):
        success = await run_parser_agent(str(unknown_file), run_id)
        assert success is False

@pytest.mark.anyio
async def test_run_mapper_agent(setup_db):
    # Add uncategorized transactions to DB
    tx1 = Transaction(
        date=date(2026, 5, 1),
        description="Fresh Grocery Store",
        amount=-50.0,
        category="Others",
        account_id="Test Bank",
        source="test"
    )
    setup_db.add(tx1)
    setup_db.commit()
    
    run_id = init_agent_run("test_source")
    
    # Mock Agent for mapper
    mock_agent_class = lambda config: MockAgent("Successfully matched 1 transactions to Grocery.")
    with patch("backend.app.agents.mapper_agent.Agent", side_effect=mock_agent_class):
        res = await run_mapper_agent(run_id)
        assert "Successfully matched" in res
        
    # Ensure logs contain it
    run = setup_db.query(AgentRun).filter(AgentRun.id == run_id).first()
    logs = json.loads(run.log_output)
    assert any("Mapper Agent result" in l for l in logs)

@pytest.mark.anyio
async def test_run_insights_agent(setup_db):
    # Seed enough transactions for correlation (at least 5 monthly aggregates or 5 txs)
    # We can write 5 transactions across a few months
    for i in range(5):
        tx = Transaction(
            date=date(2026, 1 + i, 10),
            description=f"Transaction {i}",
            amount=-100.0,
            category="Grocery",
            account_id="Test Bank",
            source="test"
        )
        setup_db.add(tx)
    setup_db.commit()
    
    run_id = init_agent_run("test_source")
    
    # Mock Agent for insights
    mock_agent_class = lambda config: MockAgent("Insights computed. Top category: Grocery.")
    with patch("backend.app.agents.insights_agent.Agent", side_effect=mock_agent_class):
        res = await run_insights_agent(run_id)
        assert "Top category: Grocery" in res

@pytest.mark.anyio
async def test_run_frontend_agent(setup_db):
    # Seed transactions with a linked pair
    tx1 = Transaction(
        id="t1",
        date=date(2026, 5, 1),
        description="Linked Outflow",
        amount=-100.0,
        category="Self-Transfers",
        account_id="Test Bank A",
        linked_transaction_id="t2",
        source="test"
    )
    tx2 = Transaction(
        id="t2",
        date=date(2026, 5, 2),
        description="Linked Inflow",
        amount=100.0,
        category="Self-Transfers",
        account_id="Test Bank B",
        linked_transaction_id="t1",
        source="test"
    )
    setup_db.add(tx1)
    setup_db.add(tx2)
    setup_db.commit()
    
    run_id = init_agent_run("test_source")
    
    # Mock Agent for frontend agent
    mock_agent_class = lambda config: MockAgent("Verification: leak check PASSED. Data ready.")
    with patch("backend.app.agents.frontend_agent.Agent", side_effect=mock_agent_class):
        res = await run_frontend_agent(run_id)
        assert "Verification: leak check PASSED" in res
        
    # Verify AgentRun status is completed
    run = setup_db.query(AgentRun).filter(AgentRun.id == run_id).first()
    assert run.status == "completed"

@pytest.mark.anyio
async def test_orchestrator_success(tmp_path, setup_db):
    csv_file = tmp_path / "valid_layout.csv"
    csv_file.write_text("Date,Description,Amount,Balance\n2026-05-01,Salary,5000.00,5000.00\n")
    
    # Mock all 4 super agent functions to succeed
    with patch("backend.app.agents.orchestrator.run_parser_agent", return_value=True) as mock_parser, \
         patch("backend.app.agents.orchestrator.run_mapper_agent", return_value="success") as mock_mapper, \
         patch("backend.app.agents.orchestrator.run_insights_agent", return_value="success") as mock_insights, \
         patch("backend.app.agents.orchestrator.run_frontend_agent", return_value="success") as mock_frontend:
             
        status = await orchestrate_statement_processing(str(csv_file), "test_trigger")
        assert status == "completed"
        
        # Verify file is deleted after successful run
        assert not os.path.exists(csv_file)
        
        mock_parser.assert_called_once()
        mock_mapper.assert_called_once()
        mock_insights.assert_called_once()
        mock_frontend.assert_called_once()

@pytest.mark.anyio
async def test_orchestrator_failure_unsupported(tmp_path, setup_db):
    invalid_file = tmp_path / "invalid_layout.csv"
    invalid_file.write_text("Invalid text contents that standard parsers fail to parse")
    
    # Mock parser to return False (i.e. parsing failed / missing parser, human notified)
    with patch("backend.app.agents.orchestrator.run_parser_agent", return_value=False):
        status = await orchestrate_statement_processing(str(invalid_file), "test_trigger")
        assert status == "human_required"
        
        # Verify file is deleted after run to prevent trigger loops
        assert not os.path.exists(invalid_file)

@pytest.mark.anyio
async def test_trigger_manual_scans(mock_dirs, setup_db):
    stmt_dir, email_dir = mock_dirs
    
    # Put a dummy file in statements_to_process
    valid_csv = stmt_dir / "statement1.csv"
    valid_csv.write_text("dummy")
    
    # Put a dummy file in email_inbox
    valid_pdf = email_dir / "statement2.pdf"
    valid_pdf.write_text("dummy")
    
    # Mock orchestrator call
    with patch("backend.app.agents.triggers.orchestrate_statement_processing", return_value="completed") as mock_orch:
        processed_folder = await scan_folder_manually()
        processed_emails = await scan_emails_manually()
        
        assert processed_folder == 1
        assert processed_emails == 1
        assert mock_orch.call_count == 2
