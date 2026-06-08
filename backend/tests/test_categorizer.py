import pytest
from backend.app.categorizer import sanitize_description, compute_cosine_similarity, find_rule_match
from backend.app.database import SessionLocal, Base, engine
from backend.app.models import CategorizationRule, Category

@pytest.fixture(scope="module")
def db_session():
    # Setup in-memory sqlite db for tests
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Seed categories
        db.add(Category(name="Online Cab Service", description=""))
        db.add(Category(name="Food and Drinks outside", description=""))
        db.commit()
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

def test_sanitize_description():
    # Remove account/card numbers
    assert sanitize_description("UBER TRIP *123456789012 SF") == "UBER TRIP XXXX SF"
    # Remove dates
    assert sanitize_description("STARBUCKS 12-05-2026 CA") == "STARBUCKS DATE CA"
    assert sanitize_description("STARBUCKS 2026/05/25 CA") == "STARBUCKS DATE CA"
    # Simple descriptions remain unaltered (ignoring formatting spaces)
    assert sanitize_description("NETFLIX COM") == "NETFLIX COM"

def test_compute_cosine_similarity():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    v4 = [0.707, 0.707, 0.0]
    
    assert pytest.approx(compute_cosine_similarity(v1, v2), 0.001) == 1.0
    assert pytest.approx(compute_cosine_similarity(v1, v3), 0.001) == 0.0
    assert pytest.approx(compute_cosine_similarity(v1, v4), 0.001) == 0.707

def test_find_rule_match(db_session):
    # Add rules
    rule1 = CategorizationRule(pattern="UBER", category="Online Cab Service", is_regex=False)
    rule2 = CategorizationRule(pattern=r"MCDONALD.*", category="Food and Drinks outside", is_regex=True)
    db_session.add(rule1)
    db_session.add(rule2)
    db_session.commit()
    
    assert find_rule_match(db_session, "UBER TRIP RIDE") == "Online Cab Service"
    assert find_rule_match(db_session, "MCDONALDS STORE 12") == "Food and Drinks outside"
    assert find_rule_match(db_session, "NETFLIX SUBSCRIPTION") is None

def test_exclude_from_matching(db_session):
    from datetime import date
    from backend.app.models import Transaction
    from backend.app.categorizer import find_semantic_match
    
    # Add two transactions: one normal and one marked as exclude_from_matching
    tx1 = Transaction(
        id="tx-normal",
        date=date(2026, 5, 1),
        description="Normal transaction for coffee",
        amount=-100.0,
        category="Drinks",
        source="test",
        description_embedding=[1.0, 0.0, 0.0],
        exclude_from_matching=False
    )
    tx2 = Transaction(
        id="tx-excluded",
        date=date(2026, 5, 2),
        description="Excluded transaction for coffee",
        amount=-120.0,
        category="Food and Drinks outside",
        source="test",
        description_embedding=[1.0, 0.0, 0.0],
        exclude_from_matching=True
    )
    db_session.add(tx1)
    db_session.add(tx2)
    db_session.commit()
    
    # We query with the same embedding [1.0, 0.0, 0.0]
    # It should match tx1 (Drinks) but NOT tx2 (Food and Drinks outside)
    match_category = find_semantic_match(db_session, [1.0, 0.0, 0.0], threshold=0.88)
    assert match_category == "Drinks"
    
    # Clean up
    db_session.delete(tx1)
    db_session.delete(tx2)
    db_session.commit()

def test_transaction_linking(db_session):
    from datetime import date
    from backend.app.models import Transaction, Category
    from backend.app.main import get_link_candidates, link_transactions, unlink_transactions
    from backend.app.schemas import LinkRequest, UnlinkRequest
    
    # Ensure Self-Transfers and Bank Transfer categories exist in test DB session
    self_trans = db_session.query(Category).filter(Category.name == "Self-Transfers").first()
    if not self_trans:
        db_session.add(Category(name="Self-Transfers", description=""))
    bank_trans = db_session.query(Category).filter(Category.name == "Bank Transfer").first()
    if not bank_trans:
        db_session.add(Category(name="Bank Transfer", description=""))
    db_session.commit()
    
    # Create two transactions in different accounts
    tx_bank = Transaction(
        id="tx-bank",
        date=date(2026, 5, 10),
        description="Transfer to CC",
        amount=-10000.0,
        category="Bank Transfer",
        source="test",
        account_id="Axis Bank"
    )
    tx_cc = Transaction(
        id="tx-cc",
        date=date(2026, 5, 11),
        description="CC Payment received",
        amount=10000.0,
        category="Bank Transfer",
        source="test",
        account_id="HDFC CC"
    )
    db_session.add(tx_bank)
    db_session.add(tx_cc)
    db_session.commit()
    
    # Fetch candidates for tx_bank
    candidates = get_link_candidates(transaction_id="tx-bank", db=db_session)
    assert len(candidates) > 0
    assert candidates[0].id == "tx-cc"
    
    # Link them
    link_transactions(LinkRequest(transaction_id_1="tx-bank", transaction_id_2="tx-cc"), db=db_session)
    
    # Refresh and assert they are linked symmetrically and categorized as Self-Transfers
    db_session.refresh(tx_bank)
    db_session.refresh(tx_cc)
    
    assert tx_bank.linked_transaction_id == "tx-cc"
    assert tx_cc.linked_transaction_id == "tx-bank"
    assert tx_bank.category == "Self-Transfers"
    assert tx_cc.category == "Self-Transfers"
    assert tx_bank.exclude_from_matching is True
    
    # Unlink them
    unlink_transactions(UnlinkRequest(transaction_id="tx-bank"), db=db_session)
    
    # Refresh and assert they are unlinked
    db_session.refresh(tx_bank)
    db_session.refresh(tx_cc)
    
    assert tx_bank.linked_transaction_id is None
    assert tx_cc.linked_transaction_id is None
    assert tx_bank.category == "Bank Transfer"
    assert tx_cc.category == "Bank Transfer"
    assert tx_bank.exclude_from_matching is False
    
    # Clean up
    db_session.delete(tx_bank)
    db_session.delete(tx_cc)
    db_session.commit()


