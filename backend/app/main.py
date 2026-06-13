from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional, Any, Dict
import os
import uuid

from .database import engine, Base, get_db, SessionLocal
from .models import Category, Transaction, CategorizationRule, AgentRun
from .schemas import (
    TransactionOut, CategoryOut, CategoryBase, 
    OverrideRequest, InsightOut, AIConfirmRequest,
    LinkRequest, UnlinkRequest, AgentRunOut,
    ReclassifyRequest
)
from .parser import (
    parse_generic_csv_statement, parse_axis_bank_pdf_statement, parse_hdfc_bank_txt_statement,
    parse_statement_with_gemini, detect_bank_from_pdf, detect_bank_from_txt, detect_bank_from_csv
)
from .categorizer import categorize_transaction, categorize_transactions_batch, PREDEFINED_CATEGORIES, get_embedding, get_embeddings_batch, compute_cosine_similarity
from .analytics import generate_natural_language_insights

app = FastAPI(title="Personal Finance Intelligence API")

# Configure CORS for local React development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup DB initialization & seeding
@app.on_event("startup")
async def startup_event():
    Base.metadata.create_all(bind=engine)
    
    # Ensure columns exist in transactions table for existing databases
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "transactions" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("transactions")]
        
        # 1. Add exclude_from_matching
        if "exclude_from_matching" not in columns:
            db = SessionLocal()
            try:
                db.execute(text("ALTER TABLE transactions ADD COLUMN exclude_from_matching BOOLEAN DEFAULT FALSE;"))
                db.commit()
                print("Successfully added column exclude_from_matching to transactions table.")
            except Exception as e:
                print(f"Error adding exclude_from_matching column: {e}")
                db.rollback()
            finally:
                db.close()
                
        # 2. Add linked_transaction_id
        if "linked_transaction_id" not in columns:
            db = SessionLocal()
            try:
                db.execute(text("ALTER TABLE transactions ADD COLUMN linked_transaction_id VARCHAR(36);"))
                db.commit()
                print("Successfully added column linked_transaction_id to transactions table.")
            except Exception as e:
                print(f"Error adding linked_transaction_id column: {e}")
                db.rollback()
            finally:
                db.close()
                
        # 3. Add ai_rate_limited
        if "ai_rate_limited" not in columns:
            db = SessionLocal()
            try:
                db.execute(text("ALTER TABLE transactions ADD COLUMN ai_rate_limited BOOLEAN DEFAULT FALSE;"))
                db.commit()
                print("Successfully added column ai_rate_limited to transactions table.")
            except Exception as e:
                print(f"Error adding ai_rate_limited column: {e}")
                db.rollback()
            finally:
                db.close()


    db = SessionLocal()
    try:
        for cat_name in PREDEFINED_CATEGORIES:
            existing = db.query(Category).filter(Category.name == cat_name).first()
            if not existing:
                db.add(Category(name=cat_name, description=f"Default category for {cat_name}"))
        db.commit()
    finally:
        db.close()

    # Start the background folder/email triggers loop
    import asyncio
    from .agents.triggers import start_background_triggers_loop
    asyncio.create_task(start_background_triggers_loop())



# In-memory cache for statements requiring AI confirmation
temp_file_cache: Dict[str, Dict[str, Any]] = {}

@app.post("/api/upload")
async def upload_bank_statement(
    file: UploadFile = File(...), 
    db: Session = Depends(get_db)
):
    """
    Secure statement ingestion:
    Receives statement file, tries standard code parser.
    If fails or extracts 0 rows, falls back to AI statement parser (Gemini)
    with a cost estimation and human confirmation flow.
    """
    contents = await file.read()
    filename = file.filename.lower()
    parsed_txs = []
    source_type = ""
    parse_error = None
    
    # 1. Try standard parser
    try:
        if filename.endswith(".csv"):
            bank = detect_bank_from_csv(contents)
            parsed_txs = parse_generic_csv_statement(contents)
            source_type = f"{bank}_csv_upload"
        elif filename.endswith(".pdf"):
            bank = detect_bank_from_pdf(contents)
            if bank == "axis":
                parsed_txs = parse_axis_bank_pdf_statement(contents)
                source_type = "axis_bank_pdf_upload"
            else:
                raise ValueError("Unsupported PDF bank statement format. Fall back to AI parsing.")
        elif filename.endswith(".txt"):
            bank = detect_bank_from_txt(contents)
            if bank == "hdfc":
                parsed_txs = parse_hdfc_bank_txt_statement(contents)
                source_type = "hdfc_bank_txt_upload"
            else:
                raise ValueError("Unsupported TXT bank statement format. Fall back to AI parsing.")
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported file format. Please upload a .csv, .pdf, or .txt file."
            )
    except Exception as e:
        parse_error = e

    # 2. Trigger AI Fallback if standard parser failed or found no transactions
    if parse_error or not parsed_txs:
        file_text = ""
        if filename.endswith(".pdf"):
            try:
                import pdfplumber
                import io
                text_parts = []
                with pdfplumber.open(io.BytesIO(contents)) as pdf:
                    for page in pdf.pages:
                        t = page.extract_text()
                        if t:
                            text_parts.append(t)
                file_text = "\n".join(text_parts)
            except Exception:
                file_text = ""
        else:
            try:
                file_text = contents.decode("utf-8", errors="ignore")
            except Exception:
                file_text = ""

        if file_text.strip():
            file_id = str(uuid.uuid4())
            est_tokens = len(file_text) // 4
            input_cost = (est_tokens / 1000000.0) * 0.075
            output_cost = (1500 / 1000000.0) * 0.30
            estimated_cost_usd = max(0.0002, round(input_cost + output_cost, 6))
            
            temp_file_cache[file_id] = {
                "text": file_text,
                "filename": file.filename,
                "source_type": filename.split(".")[-1] + "_upload"
            }
            
            return {
                "status": "parse_failed",
                "file_id": file_id,
                "estimated_cost_usd": estimated_cost_usd,
                "detail": f"Standard parser failed to read statement. AI parsing fallback is available. Error: {str(parse_error)}" if parse_error else "Standard parser found 0 transactions in this statement. AI parsing fallback is available."
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to parse statement and no readable text found: {str(parse_error)}" if parse_error else "Statement contains no readable text."
            )

    added_count = 0
    duplicate_count = 0
    
    # 3. Standard parsing duplicates filtering & persist
    non_duplicates = []
    for item in parsed_txs:
        existing = db.query(Transaction).filter(
            Transaction.date == item["date"],
            Transaction.description == item["description"],
            Transaction.amount == item["amount"]
        ).first()
        
        if existing:
            duplicate_count += 1
        else:
            non_duplicates.append(item)

    if non_duplicates:
        categorized_txs = await categorize_transactions_batch(db, non_duplicates)
        account_name = source_type.replace("_", " ").title().replace("Upload", "Statement").strip()
        
        for item in categorized_txs:
            tx = Transaction(
                date=item["date"],
                description=item["description"],
                amount=item["amount"],
                balance_after=item.get("balance_after"),
                category=item.get("category", "Others"),
                source=source_type,
                raw_payload=item.get("raw_payload"),
                description_embedding=item.get("description_embedding"),
                account_id=account_name,
                ai_rate_limited=item.get("ai_rate_limited", False)
            )
            db.add(tx)
            added_count += 1

            
        db.commit()
    
    return {
        "status": "success",
        "message": f"Successfully processed statement: {file.filename}",
        "transactions_imported": added_count,
        "duplicates_skipped": duplicate_count
    }

@app.post("/api/upload/ai-confirm")
async def confirm_ai_parsing(
    req: AIConfirmRequest,
    db: Session = Depends(get_db)
):
    """
    Called after user approves the AI parsing cost. Calls Gemini,
    runs categorization, and persists transactions.
    """
    file_id = req.file_id
    if file_id not in temp_file_cache:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Statement data not found in cache or expired."
        )
        
    cached_data = temp_file_cache.pop(file_id)
    file_text = cached_data["text"]
    filename = cached_data["filename"]
    source_type = cached_data["source_type"] + "_ai"
    
    try:
        parsed_txs = await parse_statement_with_gemini(file_text)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"AI Statement Parsing failed: {str(e)}"
        )
        
    added_count = 0
    duplicate_count = 0
    
    non_duplicates = []
    for item in parsed_txs:
        existing = db.query(Transaction).filter(
            Transaction.date == item["date"],
            Transaction.description == item["description"],
            Transaction.amount == item["amount"]
        ).first()
        
        if existing:
            duplicate_count += 1
        else:
            non_duplicates.append(item)

    if non_duplicates:
        categorized_txs = await categorize_transactions_batch(db, non_duplicates)
        account_name = filename.replace("_", " ").title().split(".")[0] + " (AI)"
        
        for item in categorized_txs:
            tx = Transaction(
                date=item["date"],
                description=item["description"],
                amount=item["amount"],
                balance_after=item.get("balance_after"),
                category=item.get("category", "Others"),
                source=source_type,
                raw_payload=item.get("raw_payload"),
                description_embedding=item.get("description_embedding"),
                account_id=account_name,
                ai_rate_limited=item.get("ai_rate_limited", False)
            )
            db.add(tx)
            added_count += 1

            
        db.commit()
        
    return {
        "status": "success",
        "message": f"Successfully processed statement with AI: {filename}",
        "transactions_imported": added_count,
        "duplicates_skipped": duplicate_count
    }

@app.get("/api/transactions", response_model=List[TransactionOut])
def get_transactions(db: Session = Depends(get_db)):
    """Retrieves all transactions sorted by date descending."""
    return db.query(Transaction).order_by(Transaction.date.desc()).all()

@app.get("/api/accounts", response_model=List[str])
def get_accounts(db: Session = Depends(get_db)):
    """Retrieves all distinct account_ids in transactions."""
    results = db.query(Transaction.account_id).distinct().all()
    return [r[0] for r in results if r[0] is not None]

@app.get("/api/transactions/link-candidates", response_model=List[TransactionOut])
def get_link_candidates(transaction_id: str, db: Session = Depends(get_db)):
    """Retrieves candidate transactions to link to the target transaction."""
    tx = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found."
        )
    
    from datetime import timedelta
    start_date = tx.date - timedelta(days=7)
    end_date = tx.date + timedelta(days=7)
    
    query = db.query(Transaction).filter(
        Transaction.account_id != tx.account_id,
        Transaction.linked_transaction_id == None,
        Transaction.date >= start_date,
        Transaction.date <= end_date
    )
    
    if tx.amount < 0:
        query = query.filter(Transaction.amount > 0)
    else:
        query = query.filter(Transaction.amount < 0)
        
    candidates = query.all()
    
    def sort_key(c):
        date_diff = abs((c.date - tx.date).days)
        amount_diff = abs(abs(c.amount) - abs(tx.amount))
        return (date_diff, amount_diff)
        
    candidates.sort(key=sort_key)
    return candidates

@app.post("/api/transactions/link")
def link_transactions(req: LinkRequest, db: Session = Depends(get_db)):
    """Symmetrically links two transactions and categorizes them as Self-Transfers."""
    t1 = db.query(Transaction).filter(Transaction.id == req.transaction_id_1).first()
    t2 = db.query(Transaction).filter(Transaction.id == req.transaction_id_2).first()
    
    if not t1 or not t2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both transactions not found."
        )
        
    t1.linked_transaction_id = t2.id
    t2.linked_transaction_id = t1.id
    
    t1.category = "Self-Transfers"
    t2.category = "Self-Transfers"
    
    t1.exclude_from_matching = True
    t2.exclude_from_matching = True
    
    db.commit()
    return {"message": "Transactions linked successfully."}

@app.post("/api/transactions/unlink")
def unlink_transactions(req: UnlinkRequest, db: Session = Depends(get_db)):
    """Unlinks two transactions and resets their categories back to Bank Transfer."""
    t1 = db.query(Transaction).filter(Transaction.id == req.transaction_id).first()
    if not t1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found."
        )
        
    partner_id = t1.linked_transaction_id
    if partner_id:
        t2 = db.query(Transaction).filter(Transaction.id == partner_id).first()
        if t2:
            t2.linked_transaction_id = None
            t2.category = "Bank Transfer"
            t2.exclude_from_matching = False
            
    t1.linked_transaction_id = None
    t1.category = "Bank Transfer"
    t1.exclude_from_matching = False
    
    db.commit()
    return {"message": "Transactions unlinked successfully."}


@app.get("/api/agent-runs", response_model=List[AgentRunOut])
def get_agent_runs(db: Session = Depends(get_db)):
    """Retrieves all agent execution runs sorted by timestamp descending."""
    return db.query(AgentRun).order_by(AgentRun.timestamp.desc()).all()


@app.post("/api/agent-runs/trigger")
async def trigger_agent_run(db: Session = Depends(get_db)):
    """Manually triggers the agentic statement scan and processing pipeline."""
    from .agents.triggers import scan_folder_manually, scan_emails_manually
    try:
        run_count = await scan_folder_manually(db)
        email_count = await scan_emails_manually(db)
        return {
            "status": "success",
            "message": f"Agentic trigger executed. Processed {run_count} statements from folder and {email_count} from emails."
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agentic processing failed: {str(e)}"
        )


@app.get("/api/categories", response_model=List[CategoryOut])

def get_categories(db: Session = Depends(get_db)):
    """Retrieves all categories."""
    return db.query(Category).all()

@app.post("/api/categories", response_model=CategoryOut)
def create_category(category: CategoryBase, db: Session = Depends(get_db)):
    """Adds a custom category."""
    existing = db.query(Category).filter(Category.name == category.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category '{category.name}' already exists."
        )
    db_cat = Category(
        name=category.name,
        description=category.description,
        is_custom=True
    )
    db.add(db_cat)
    db.commit()
    db.refresh(db_cat)
    return db_cat

@app.post("/api/override")
async def override_transaction_category(
    req: OverrideRequest, 
    db: Session = Depends(get_db)
):
    """
    Applies a manual category override. If requested, creates a rule
    to automatically tag future (and existing) transactions with a matching description.
    """
    tx = db.query(Transaction).filter(Transaction.id == req.transaction_id).first()
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found."
        )
        
    old_category = tx.category
    tx.category = req.category
    
    if req.apply_to_all_matching:
        tx.exclude_from_matching = False
        
        # Create a new rule pattern (exact string match in description)
        pattern = tx.description.strip()
        
        # Check if rule exists
        existing_rule = db.query(CategorizationRule).filter(
            CategorizationRule.pattern == pattern
        ).first()
        
        if existing_rule:
            existing_rule.category = req.category
        else:
            new_rule = CategorizationRule(
                pattern=pattern,
                category=req.category,
                is_regex=False,
                user_confirmed=True
            )
            db.add(new_rule)
            
        # Ensure target transaction has an embedding
        if not tx.description_embedding:
            tx.description_embedding = get_embedding(tx.description)
            
        # Re-categorize all historical transactions matching this pattern (Exact Match)
        db.query(Transaction).filter(
            Transaction.description == pattern
        ).update({
            Transaction.category: req.category,
            Transaction.exclude_from_matching: False
        })
        
        # Re-categorize all historical transactions matching semantically (Vector Similarity Match)
        target_emb = tx.description_embedding
        if isinstance(target_emb, str):
            import json
            try:
                target_emb = json.loads(target_emb)
            except Exception:
                pass
                
        if target_emb:
            all_txs = db.query(Transaction).all()
            
            # Generate missing embeddings for other transactions first in batch
            missing_txs = [t for t in all_txs if t.description_embedding is None]
            if missing_txs:
                descriptions = [t.description for t in missing_txs]
                embs = get_embeddings_batch(descriptions)
                for t, emb in zip(missing_txs, embs):
                    if emb:
                        t.description_embedding = emb
            
            # Now calculate similarities and update matching ones
            import json
            for other_tx in all_txs:
                if other_tx.id == tx.id:
                    continue
                    
                other_emb = other_tx.description_embedding
                if isinstance(other_emb, str):
                    try:
                        other_emb = json.loads(other_emb)
                    except Exception:
                        continue
                if not other_emb:
                     continue
                    
                similarity = compute_cosine_similarity(target_emb, other_emb)
                if similarity >= 0.88:
                    other_tx.category = req.category
                    other_tx.exclude_from_matching = False
    else:
        tx.exclude_from_matching = True
        
    db.commit()
    return {"message": "Category override applied successfully."}

@app.get("/api/analytics/insights", response_model=List[InsightOut])
async def get_analytics_insights(db: Session = Depends(get_db)):
    """Retrieves correlation metrics and text recommendation insights."""
    return await generate_natural_language_insights(db)

@app.get("/api/ai-status")
def get_ai_status():
    """Retrieves the rate limit status of the AI engine."""
    from .rate_limiter import is_ai_rate_limited, get_rate_limit_seconds_remaining
    return {
        "is_rate_limited": is_ai_rate_limited(),
        "seconds_remaining": get_rate_limit_seconds_remaining()
    }

@app.post("/api/transactions/reclassify")
async def reclassify_transactions(req: ReclassifyRequest, db: Session = Depends(get_db)):
    """
    Force re-classification of selected transactions through the entire mapping loop:
    1. Rule match (internal)
    2. Semantic vector match (internal)
    3. Gemini API (external)
    """
    txs = db.query(Transaction).filter(Transaction.id.in_(req.transaction_ids)).all()
    if not txs:
        return {"message": "No transactions found to reclassify."}

    txs_data = []
    for tx in txs:
        txs_data.append({
            "id": tx.id,
            "description": tx.description,
            "amount": float(tx.amount),
            "date": str(tx.date),
            "balance_after": float(tx.balance_after) if tx.balance_after is not None else None,
            "category": tx.category,
            "description_embedding": tx.description_embedding,
            "ai_rate_limited": False
        })

    categorized = await categorize_transactions_batch(db, txs_data)

    updated_count = 0
    for item in categorized:
        tx = db.query(Transaction).filter(Transaction.id == item["id"]).first()
        if tx:
            tx.category = item.get("category", "Others")
            tx.ai_rate_limited = item.get("ai_rate_limited", False)
            if item.get("description_embedding") is not None:
                tx.description_embedding = item["description_embedding"]
            updated_count += 1
            
    db.commit()
    return {"message": f"Successfully processed re-classification for {updated_count} transactions."}

