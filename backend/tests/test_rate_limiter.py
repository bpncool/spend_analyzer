import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from backend.app.rate_limiter import (
    is_ai_rate_limited, trigger_ai_rate_limit,
    get_rate_limit_seconds_remaining, should_send_notification, clear_ai_rate_limit
)
from backend.app.categorizer import _is_rate_limit_error, categorize_transactions_batch
from backend.app.database import SessionLocal, Base, engine
from backend.app.models import Category, Transaction
from google.genai.errors import APIError

@pytest.fixture(autouse=True)
def run_around_tests():
    # Clear rate limiter state before each test
    clear_ai_rate_limit()
    yield
    clear_ai_rate_limit()

@pytest.fixture(scope="module")
def db_session():
    # Setup in-memory sqlite db for tests
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Seed categories
        db.add(Category(name="Online Cab Service", description=""))
        db.add(Category(name="Food and Drinks outside", description=""))
        db.add(Category(name="Others", description=""))
        db.commit()
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

def test_rate_limiter_state():
    assert is_ai_rate_limited() is False
    assert get_rate_limit_seconds_remaining() == 0

    trigger_ai_rate_limit(5)
    assert is_ai_rate_limited() is True
    assert get_rate_limit_seconds_remaining() > 290
    assert get_rate_limit_seconds_remaining() <= 300

    clear_ai_rate_limit()
    assert is_ai_rate_limited() is False

def test_notification_cooldown():
    # First notification should send
    assert should_send_notification() is True
    # Immediate second one should be rate limited (cooldown active)
    assert should_send_notification() is False

def test_rate_limit_error_detector():
    # Test APIError matching code 429
    mock_response = MagicMock()
    mock_response.status_code = 429
    
    api_err = APIError(code=429, response_json={"error": {"code": 429, "message": "RESOURCE_EXHAUSTED", "status": "RESOURCE_EXHAUSTED"}}, response=mock_response)
    assert _is_rate_limit_error(api_err) is True

    # Test generic exception with code attribute
    generic_err_429 = Exception("API error")
    generic_err_429.code = 429
    assert _is_rate_limit_error(generic_err_429) is True

    # Test generic exception with message text
    generic_err_text = Exception("Error: RESOURCE_EXHAUSTED details here")
    assert _is_rate_limit_error(generic_err_text) is True

    # Test non-rate-limit exception
    generic_err_other = Exception("Connection Timeout")
    assert _is_rate_limit_error(generic_err_other) is False

@pytest.mark.anyio
async def test_batch_categorization_rate_limit_fallback(db_session):
    txs_data = [
        {"description": "UBER TRIP", "amount": -150.0},
        {"description": "ZOMATO ORDER", "amount": -450.0}
    ]
    
    # Trigger active rate limit first
    trigger_ai_rate_limit(5)
    
    # Run batch categorization. Since rules and semantic might not match (we haven't seeded rules),
    # it should skip Gemini entirely and flag transactions as rate-limited.
    result = await categorize_transactions_batch(db_session, txs_data)
    
    for tx in result:
        assert tx["category"] == "Others"
        assert tx["ai_rate_limited"] is True

@pytest.mark.anyio
@patch("backend.app.categorizer.gemini_client")
async def test_batch_categorization_429_exception(mock_gemini, db_session):
    # Setup mock to raise 429 APIError on generate_content
    mock_response = MagicMock()
    mock_response.status_code = 429
    api_err = APIError(
        code=429, 
        response_json={"error": {"code": 429, "message": "RESOURCE_EXHAUSTED", "status": "RESOURCE_EXHAUSTED"}}, 
        response=mock_response
    )
    mock_gemini.models.generate_content.side_effect = api_err
    
    txs_data = [
        {"description": "SWIGGY SUPER", "amount": -200.0}
    ]
    
    # Ensure rate limit is clear
    clear_ai_rate_limit()
    
    with patch("backend.app.categorizer.send_notification_email") as mock_email:
        result = await categorize_transactions_batch(db_session, txs_data)
        
        # Verify rate limit got triggered
        assert is_ai_rate_limited() is True
        # Verify transaction got flagged
        assert result[0]["category"] == "Others"
        assert result[0]["ai_rate_limited"] is True
        # Verify notification email was sent
        mock_email.assert_called_once()

@pytest.mark.anyio
@patch("backend.app.categorizer.gemini_client")
async def test_batch_chunking_pacing(mock_gemini, db_session):
    # Setup mock generate_content to return empty/mock response
    mock_response = MagicMock()
    mock_response.text = '{"results": []}'
    mock_gemini.models.generate_content.return_value = mock_response
    
    # 250 transactions with chunk size 120 should result in 3 chunks -> 2 pacing sleep calls
    txs_data = [{"description": f"TX {i}", "amount": -10.0} for i in range(250)]
    
    clear_ai_rate_limit()
    
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await categorize_transactions_batch(db_session, txs_data)
        # Verify pacing sleep was called 2 times with 1.5s
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(1.5)
