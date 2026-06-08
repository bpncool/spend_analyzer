import json
import uuid
import os
from datetime import date, datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from ..database import SessionLocal
from ..models import Transaction, Category, CategorizationRule, AgentRun

def get_db_session():
    """Helper to get a database session."""
    return SessionLocal()

# =============================================================================
# Logging and Run Status Utilities (Internal DB Helpers)
# =============================================================================

def init_agent_run(statement_source: str) -> str:
    """Initializes a new AgentRun record in the database and returns its run_id."""
    db = get_db_session()
    run_id = str(uuid.uuid4())
    try:
        run = AgentRun(
            id=run_id,
            status="started",
            statement_source=statement_source,
            log_output=json.dumps([f"[{datetime.now().isoformat()}] Agentic pipeline triggered by: {statement_source}"]),
            error_message=None
        )
        db.add(run)
        db.commit()
        return run_id
    finally:
        db.close()

def log_run_step(run_id: str, status: str, log_message: str, error_message: Optional[str] = None):
    """Appends a log message and updates the status of an AgentRun."""
    db = get_db_session()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        if run:
            run.status = status
            if error_message:
                run.error_message = error_message
            
            # Load logs, append new, dump
            try:
                logs = json.loads(run.log_output)
            except Exception:
                logs = []
            
            logs.append(f"[{datetime.now().isoformat()}] [{status.upper()}] {log_message}")
            run.log_output = json.dumps(logs)
            db.commit()
    finally:
        db.close()

# =============================================================================
# Agent Tools: Database Operations (High-level Structured Tools)
# =============================================================================

def fetch_historical_rules() -> str:
    """Fetches all existing rules from the database to map transactions.
    Returns:
        A JSON string containing a list of rule dicts (pattern, category, is_regex).
    """
    db = get_db_session()
    try:
        rules = db.query(CategorizationRule).all()
        result = [{"pattern": r.pattern, "category": r.category, "is_regex": r.is_regex} for r in rules]
        return json.dumps(result)
    finally:
        db.close()

def fetch_historical_embeddings() -> str:
    """Fetches historical transactions that have valid categories and description embeddings.
    Returns:
        A JSON string of a list of transaction dicts (description, category, description_embedding).
    """
    db = get_db_session()
    try:
        # Fetch non-excluded transactions with category and description_embedding
        txs = db.query(Transaction).filter(
            Transaction.description_embedding != None,
            Transaction.category != None,
            Transaction.exclude_from_matching == False
        ).all()
        result = []
        for t in txs:
            emb = t.description_embedding
            if isinstance(emb, str):
                try:
                    emb = json.loads(emb)
                except Exception:
                    continue
            result.append({
                "description": t.description,
                "category": t.category,
                "embedding": emb
            })
        return json.dumps(result)
    finally:
        db.close()

def persist_transactions_to_db(transactions_json: str, account_name: str, source: str) -> str:
    """Saves parsed transactions to the SQLite database, skipping duplicates.
    Args:
        transactions_json: A JSON string containing a list of transaction dicts (date, description, amount, balance_after).
        account_name: Name of the account/bank statement.
        source: Ingestion source name (e.g. axis_pdf_agent_upload).
    Returns:
        A message string summarizing the result.
    """
    db = get_db_session()
    try:
        txs = json.loads(transactions_json)
        added_count = 0
        duplicate_count = 0
        
        for item in txs:
            # Try to parse date
            try:
                date_val = datetime.strptime(item["date"], "%Y-%m-%d").date()
            except Exception:
                try:
                    # Try other common formats
                    from ..parser import parse_date
                    date_val = parse_date(item["date"])
                except Exception:
                    date_val = date.today()
                    
            if not date_val:
                date_val = date.today()
                
            existing = db.query(Transaction).filter(
                Transaction.date == date_val,
                Transaction.description == item["description"],
                Transaction.amount == item["amount"]
            ).first()
            
            if existing:
                duplicate_count += 1
            else:
                tx = Transaction(
                    date=date_val,
                    description=item["description"],
                    amount=item["amount"],
                    balance_after=item.get("balance_after"),
                    category="Others", # Default before mapping agent runs
                    source=source,
                    account_id=account_name
                )
                db.add(tx)
                added_count += 1
        
        db.commit()
        return f"Successfully processed statement. Saved {added_count} transactions, skipped {duplicate_count} duplicates."
    finally:
        db.close()

def fetch_uncategorized_transactions() -> str:
    """Fetches all transactions that currently have category 'Others' or are None.
    Returns:
        A JSON string of a list of transaction dicts (id, description, amount, account_id, date).
    """
    db = get_db_session()
    try:
        txs = db.query(Transaction).filter(
            (Transaction.category == "Others") | (Transaction.category == None)
        ).all()
        result = [
            {
                "id": t.id,
                "description": t.description,
                "amount": float(t.amount),
                "account_id": t.account_id,
                "date": str(t.date)
            }
            for t in txs
        ]
        return json.dumps(result)
    finally:
        db.close()

def update_transaction_categories(category_mappings_json: str) -> str:
    """Updates the categories and generates embeddings for transactions.
    Args:
        category_mappings_json: A JSON string mapping transaction IDs to categories, e.g. [{"id": "uuid", "category": "Grocery"}, ...]
    Returns:
        A success message.
    """
    db = get_db_session()
    try:
        mappings = json.loads(category_mappings_json)
        updated_count = 0
        
        for item in mappings:
            tx = db.query(Transaction).filter(Transaction.id == item["id"]).first()
            if tx:
                tx.category = item["category"]
                
                # Proactively generate embedding
                from ..categorizer import get_embedding
                emb = get_embedding(tx.description)
                if emb:
                    tx.description_embedding = emb
                
                updated_count += 1
        db.commit()
        return f"Successfully updated categories and generated embeddings for {updated_count} transactions."
    finally:
        db.close()

# =============================================================================
# Agent Tools: Notifications (Human-In-The-Loop Mock Email)
# =============================================================================

def send_notification_email(subject: str, body: str) -> str:
    """Sends a notification email to the human administrator (e.g. request for new parser).
    Args:
        subject: The email subject line.
        body: The email text body contents.
    Returns:
        A status message verifying if email was sent or logged.
    """
    # Print clearly to stdout so it shows up in task logs
    print("\n" + "="*80)
    print(f"📧 EMAIL NOTIFICATION DISPATCHED")
    print(f"Subject: {subject}")
    print(f"Body:\n{body}")
    print("="*80 + "\n")
    
    # Store email notification log under scratch folder for tracking
    scratch_dir = "/Users/bhaveshpachnanda/.gemini/antigravity/scratch"
    os.makedirs(scratch_dir, exist_ok=True)
    notif_path = os.path.join(scratch_dir, "notifications.jsonl")
    try:
        with open(notif_path, "a") as f:
            f.write(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "subject": subject,
                "body": body
            }) + "\n")
    except Exception as e:
         print(f"Error saving mock email to file: {e}")
         
    return f"Mock email dispatched successfully: '{subject}'"
