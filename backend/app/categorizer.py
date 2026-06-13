import re
import numpy as np
import json
import asyncio
from typing import List, Optional
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from google import genai
from google.genai import types
from google.genai.errors import APIError
from fastembed import TextEmbedding

from .config import settings
from .models import Category, Transaction, CategorizationRule
from .schemas import CategorizationResponse, BatchCategorizationItem, BatchCategorizationResponse
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


# Initialize Gemini Client if API key is provided
gemini_client = None
if settings.GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    except Exception as e:
        print(f"Failed to initialize Gemini Client: {e}")
else:
    print("WARNING: GEMINI_API_KEY is not set. GenAI fallback categorization will tag transactions as 'Others'. Please configure it in your environment or a .env file.")

# Initialize fastembed locally (downloads BAAI/bge-small-en-v1.5 once and caches it)
try:
    local_embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
except Exception as e:
    print(f"Failed to initialize local fastembed TextEmbedding: {e}")
    local_embedder = None

PREDEFINED_CATEGORIES = [
    "Online Cab Service",
    "Investment",
    "Food and Drinks outside",
    "Online Food delivery",
    "Online Grocery",
    "Grocery",
    "Bank Transfer",
    "Self-Transfers",
    "Drinks",
    "Others"
]


def sanitize_description(description: str) -> str:
    """Security Protocol: Strips out PII before passing description to LLM."""
    desc = re.sub(r'\d{2,4}[-/]\d{2}[-/]\d{2,4}', 'DATE', description)
    desc = re.sub(r'[\d*xX]{4,16}', 'XXXX', desc)
    return " ".join(desc.split())

def get_embedding(text: str) -> Optional[List[float]]:
    """Helper to generate dense vectors locally using ONNX runtime and BAAI/bge-small-en-v1.5."""
    if not local_embedder:
        return None
    try:
        embeddings = list(local_embedder.embed([text]))
        if embeddings:
            return embeddings[0].tolist()
    except Exception as e:
        print(f"Local embedding generation failed: {e}")
    return None

def get_embeddings_batch(texts: List[str]) -> List[Optional[List[float]]]:
    """Helper to generate embeddings for a batch of texts locally using fastembed."""
    if not local_embedder or not texts:
        return [None] * len(texts)
    try:
        embeddings = list(local_embedder.embed(texts))
        return [emb.tolist() if emb is not None else None for emb in embeddings]
    except Exception as e:
        print(f"Local batch embedding generation failed: {e}")
        return [None] * len(texts)

def compute_cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Computes cosine similarity between two float arrays."""
    a = np.array(v1)
    b = np.array(v2)
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))

def find_rule_match(db: Session, description: str) -> Optional[str]:
    """Tier 1: Checks rule matching tables (substring matches)."""
    rules = db.query(CategorizationRule).all()
    for rule in rules:
        if rule.is_regex:
            try:
                if re.search(rule.pattern, description, re.IGNORECASE):
                    return rule.category
            except Exception:
                continue
        else:
            if rule.pattern.lower() in description.lower():
                return rule.category
    return None

def find_semantic_match(db: Session, new_embedding: List[float], threshold: float = 0.88) -> Optional[str]:
    """Tier 2: Vector semantic similarity match (SQLite Python fallback or Postgres pgvector)."""
    if not new_embedding:
        return None
        
    # Check if Postgres pgvector can be used
    if settings.DATABASE_URL.startswith("postgresql"):
        try:
            # Query using pgvector cosine distance: distance = 1 - similarity.
            # So distance < (1 - threshold) -> distance < 0.12 for 0.88 similarity.
            max_dist = 1.0 - threshold
            sql = f"""
                SELECT category FROM transactions 
                WHERE description_embedding IS NOT NULL 
                AND category IS NOT NULL
                AND exclude_from_matching = FALSE
                AND description_embedding <=> :emb < :max_dist
                ORDER BY description_embedding <=> :emb 
                LIMIT 1
            """
            result = db.execute(select(Transaction.category).text(sql), {
                "emb": str(new_embedding),
                "max_dist": max_dist
            }).first()
            if result:
                return result[0]
        except Exception as e:
            print(f"Postgres pgvector query failed, falling back to python match: {e}")
            
    # SQLite fallback: load historical transactions with embeddings into memory and calculate similarity
    stmt = select(Transaction).where(
        Transaction.description_embedding != None, 
        Transaction.category != None,
        Transaction.exclude_from_matching == False
    )

    history = db.scalars(stmt).all()
    
    best_similarity = -1.0
    best_category = None
    
    for tx in history:
        tx_emb = tx.description_embedding
        if isinstance(tx_emb, str):
            import json
            try:
                tx_emb = json.loads(tx_emb)
            except Exception:
                continue
        if not tx_emb:
            continue
            
        sim = compute_cosine_similarity(new_embedding, tx_emb)
        if sim > best_similarity:
            best_similarity = sim
            best_category = tx.category
            
    if best_similarity >= threshold:
        return best_category
        
    return None

async def query_gemini_categorizer(description: str, amount: float, categories: List[str]) -> Optional[str]:
    """Tier 3: Structured Gemini API call."""
    if not gemini_client or is_ai_rate_limited():
        return None
        
    sanitized = sanitize_description(description)
    system_instruction = (
        "You are an expert personal finance auditor. Your task is to categorize bank "
        "transaction descriptions into one of the allowed categories. "
        "Choose the most appropriate category based on the description and transaction details."
    )
    
    prompt = f"""
    Please categorize the following transaction:
    - Description: {sanitized}
    - Amount: {amount} (Negative indicates expense, Positive indicates credit/income)

    Allowed Categories:
    {", ".join(categories)}

    You must return a JSON object conforming to the target schema.
    If none of the categories apply, use 'Others'.
    """
    
    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=CategorizationResponse,
                temperature=0.1,
            ),
        )
        result = CategorizationResponse.model_validate_json(response.text)
        if result.category in categories:
            return result.category
    except Exception as e:
        print(f"Gemini generation call failed: {e}")
        if _is_rate_limit_error(e):
            trigger_ai_rate_limit(5)
            if should_send_notification():
                send_notification_email(
                    "Spend Analyzer: Gemini API Rate Limit Triggered",
                    "The Gemini API rate limit has been reached (429/RESOURCE_EXHAUSTED). The system is falling back to local rule and vector similarity matching."
                )
        
    return None


async def categorize_transaction(db: Session, description: str, amount: float) -> str:
    """Core pipeline entry: Rule-based -> Semantic pgvector -> Gemini LLM."""
    # Load all active categories from DB
    db_categories = db.query(Category.name).all()
    categories = [c[0] for c in db_categories] if db_categories else PREDEFINED_CATEGORIES
    
    # 1. Rule Match
    rule_category = find_rule_match(db, description)
    if rule_category:
        return rule_category
        
    # Generate embedding
    new_embedding = get_embedding(description)
    
    # 2. Semantic Match
    if new_embedding:
        semantic_category = find_semantic_match(db, new_embedding)
        if semantic_category:
            return semantic_category
            
    # 3. Gemini Fallback
    llm_category = await query_gemini_categorizer(description, amount, categories)
    if llm_category:
        return llm_category
        
    return "Others"

async def categorize_transactions_batch(db: Session, transactions_data: List[dict]) -> List[dict]:
    """
    Categorizes a list of transactions in a single batch, reducing input tokens
    and API call costs by up to 87%.
    
    Modifies transactions_data in-place to attach:
    - 'category'
    - 'description_embedding'
    - 'ai_rate_limited'
    """
    # Initialize all with default flags
    for tx in transactions_data:
        tx["ai_rate_limited"] = tx.get("ai_rate_limited", False)

    db_categories = db.query(Category.name).all()
    categories = [c[0] for c in db_categories] if db_categories else PREDEFINED_CATEGORIES

    unmatched_indices = []
    unmatched_payloads = []

    # Step 1: Pattern Rule Match (Fast & Free)
    for idx, tx in enumerate(transactions_data):
        rule_cat = find_rule_match(db, tx["description"])
        if rule_cat:
            tx["category"] = rule_cat
            tx["description_embedding"] = None
            tx["ai_rate_limited"] = False
        else:
            unmatched_indices.append(idx)
            unmatched_payloads.append(tx)

    if not unmatched_indices:
        return transactions_data

    # Step 2: Semantic Match (Free Local Vector Computation)
    still_unmatched_indices = []
    still_unmatched_payloads = []
    
    # Generate embeddings in batch
    descriptions = [tx["description"] for tx in unmatched_payloads]
    embeddings = get_embeddings_batch(descriptions)
    
    # Check vector similarity
    for idx, tx, emb in zip(unmatched_indices, unmatched_payloads, embeddings):
        tx["description_embedding"] = emb
        
        semantic_cat = None
        if emb:
            semantic_cat = find_semantic_match(db, emb)
            
        if semantic_cat:
            tx["category"] = semantic_cat
            tx["ai_rate_limited"] = False
        else:
            still_unmatched_indices.append(idx)
            still_unmatched_payloads.append(tx)

    if not still_unmatched_indices:
        return transactions_data

    # Step 3: Batch LLM Ingestion (Single cheap API call instead of N separate calls)
    llm_input = []
    for idx, tx in zip(still_unmatched_indices, still_unmatched_payloads):
        llm_input.append({
            "index": idx,
            "description": sanitize_description(tx["description"]),
            "amount": tx["amount"]
        })

    if gemini_client and llm_input:
        system_instruction = (
            "You are an expert personal finance auditor. Your task is to categorize a batch "
            "of bank transactions. You must choose categories strictly from the 'Allowed Categories' "
            "list provided in the prompt.\n"
            "Here are examples of how descriptions should map to categories (select the closest matching category from the 'Allowed Categories' list):\n"
            "- Food delivery descriptions (e.g. Swiggy, Zomato, Uber Eats) -> map to a food delivery/drinks category.\n"
            "- Restaurant, cafe, bar, pub, coffee, bakery descriptions (e.g. Starbucks, McDonald's) -> map to a dining out/food category.\n"
            "- Cab/transport service descriptions (e.g. Uber rides, Ola, Rapido) -> map to a cab/transport category.\n"
            "- Supermarket, grocery store, market descriptions (e.g. Blinkit, Instacart) -> map to a grocery category.\n"
            "- Own bank transfer, credit card payment, or self-settlement descriptions -> map to a self-transfers category.\n"
            "- P2P transfer, salary credit, cash transfer, or third-party merchant descriptions -> map to a bank transfer category.\n"
            "- Mutual funds, stocks, shares, SIP, or broker descriptions -> map to an investment category.\n"
            "If none of the allowed categories in the prompt fit the transaction, default to 'Others'. Do NOT return any category name that is not explicitly in the 'Allowed Categories' list."
        )

        # Chunk requests to prevent exceeding output token limits
        chunk_size = 120
        results_map = {}
        
        # If rate limit is already active at the start of Step 3, block immediately
        if is_ai_rate_limited():
            for idx in still_unmatched_indices:
                results_map[idx] = ("Others", True)
        else:
            for i in range(0, len(llm_input), chunk_size):
                chunk = llm_input[i:i + chunk_size]
                
                # Check rate limit before chunk request
                if is_ai_rate_limited():
                    for item in chunk:
                        results_map[item["index"]] = ("Others", True)
                    continue

                if i > 0:
                    await asyncio.sleep(1.5)

                # Check rate limit again after delay
                if is_ai_rate_limited():
                    for item in chunk:
                        results_map[item["index"]] = ("Others", True)
                    continue

                prompt = f"""
                Please categorize the following batch of bank transactions:
                Transactions:
                {json.dumps(chunk, indent=2)}

                Allowed Categories:
                {", ".join(categories)}

                You must return a JSON object containing a list of results conforming strictly to the target schema.
                If none of the categories apply to a transaction, use 'Others'.
                """
                
                try:
                    response = gemini_client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            response_mime_type="application/json",
                            response_schema=BatchCategorizationResponse,
                            temperature=0.1,
                        ),
                    )
                    batch_result = BatchCategorizationResponse.model_validate_json(response.text)
                    for item in batch_result.results:
                        results_map[item.index] = (item.category, False)
                except Exception as e:
                    print(f"Batch GenAI categorization call failed for chunk {i//chunk_size}: {e}")
                    if _is_rate_limit_error(e):
                        trigger_ai_rate_limit(5)
                        if should_send_notification():
                            send_notification_email(
                                "Spend Analyzer: Gemini API Rate Limit Triggered",
                                "The Gemini API rate limit has been reached (429/RESOURCE_EXHAUSTED). The system is falling back to local rule and vector similarity matching."
                            )
                        # Mark current chunk as rate-limited
                        for item in chunk:
                            results_map[item["index"]] = ("Others", True)
                    else:
                        for item in chunk:
                            results_map[item["index"]] = ("Others", False)
                    
        # Populate responses back in place
        for idx, tx in zip(still_unmatched_indices, still_unmatched_payloads):
            cat, rate_limited = results_map.get(idx, ("Others", False))
            tx["category"] = cat
            tx["ai_rate_limited"] = rate_limited
    else:
        # Fallback if Gemini client is not initialized
        for tx in still_unmatched_payloads:
            tx["category"] = "Others"
            tx["ai_rate_limited"] = False

    return transactions_data
