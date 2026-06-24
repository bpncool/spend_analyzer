import pytest
from unittest.mock import patch, MagicMock
import os
import sys
from backend.app.database import SessionLocal, Base, engine
from backend.app.models import Category, AgentRun
from backend.app.agents.utility_agents import init_agent_run

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

@pytest.mark.anyio
@patch("backend.app.agents.parser_creator_agent.gemini_client")
async def test_parser_creator_success(mock_gemini, tmp_path):
    # Setup mock response
    mock_response = MagicMock()
    mock_response.text = (
        '{"format_name": "custom_test_bank", '
        '"detect_keywords": ["TESTBANK", "Particulars"], '
        '"python_code": "def detect_format(text: str) -> bool:\\n    return \\"TESTBANK\\" in text\\n\\ndef parse_statement(file_bytes: bytes) -> list:\\n    return [{\\"date\\": \\"2026-06-25\\", \\"description\\": \\"TEST TRANS\\", \\"amount\\": -50.0, \\"balance_after\\": 1000.0}]"}'
    )
    mock_gemini.models.generate_content.return_value = mock_response

    # Create a dummy statement file to parse
    test_stmt_path = os.path.join(tmp_path, "test_statement.txt")
    with open(test_stmt_path, "w") as f:
        f.write("TESTBANK statement\nDate,Particulars,Amount\n2026-06-25,TEST TRANS,-50.0")

    # Mock open specifically for parser.py to avoid modifying the real one
    original_open = open
    parser_write_content = []
    
    def mock_open_fn(file, mode="r", *args, **kwargs):
        file_str = str(file)
        if "parser.py" in file_str:
            mock_file = MagicMock()
            if "r" in mode:
                mock_file.read.return_value = "def register_custom_parser(name, d, p):\n    pass\n\n# === REGISTERED CUSTOM PARSERS ===\n"
            else:
                def write_hook(data):
                    parser_write_content.append(data)
                mock_file.write.side_effect = write_hook
            mock_file.__enter__.return_value = mock_file
            return mock_file
        return original_open(file, mode, *args, **kwargs)

    # Run the parser creator agent
    from backend.app.agents.parser_creator_agent import run_parser_creator_agent
    run_id = init_agent_run("test-run-id")
    
    # We clean up any existing custom_test_bank files first
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    custom_parser_file = os.path.join(current_dir, "app", "custom_parsers", "custom_test_bank.py")
    if os.path.exists(custom_parser_file):
        try:
            os.remove(custom_parser_file)
        except Exception:
            pass

    with patch("builtins.open", side_effect=mock_open_fn):
        success = await run_parser_creator_agent(test_stmt_path, run_id)
        
    assert success is True
    
    # Check that custom_test_bank file was created
    assert os.path.exists(custom_parser_file) is True
    
    # Check that it appended to parser.py
    assert len(parser_write_content) > 0
    assert "register_custom_parser" in parser_write_content[0]
    
    # Clean up test artifact
    try:
        os.remove(custom_parser_file)
    except Exception:
        pass
