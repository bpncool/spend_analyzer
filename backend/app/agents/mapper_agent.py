import os
import json
from google.antigravity import Agent, LocalAgentConfig
from .utility_agents import (
    fetch_uncategorized_transactions, fetch_historical_rules,
    fetch_historical_embeddings, update_transaction_categories, log_run_step
)
from ..categorizer import find_rule_match, compute_cosine_similarity, get_embeddings_batch, PREDEFINED_CATEGORIES, gemini_client
from google.genai import types
from ..schemas import BatchCategorizationResponse

# =============================================================================
# Tools for Transaction Mapper Agent
# =============================================================================

def get_uncategorized() -> str:
    """Fetches all transactions that do not currently have a category from the database.
    Returns:
        A JSON string of a list of transaction dicts (id, description, amount, date).
    """
    return fetch_uncategorized_transactions()

def match_locally(txs_json: str) -> str:
    """Runs rule matching and local semantic vector similarity against existing database entries.
    Args:
        txs_json: JSON string of transactions to map.
    Returns:
        JSON string containing two keys:
        'matched': list of mappings dicts [{"id": "uuid", "category": "Grocery"}]
        'unmatched': list of original transaction dicts that could not be matched locally.
    """
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        txs = json.loads(txs_json)
        if not txs:
            return json.dumps({"matched": [], "unmatched": []})
            
        # 1. Fetch rules and history
        rules_data = json.loads(fetch_historical_rules())
        history_data = json.loads(fetch_historical_embeddings())
        
        matched_mappings = []
        unmatched_txs = []
        
        # We need to generate embeddings for all unmatched items to do semantic matching
        descriptions = [t["description"] for t in txs]
        embeddings = get_embeddings_batch(descriptions)
        
        for tx, emb in zip(txs, embeddings):
            # Check Rule Matches
            rule_category = find_rule_match(db, tx["description"])
            if rule_category:
                matched_mappings.append({"id": tx["id"], "category": rule_category})
                continue
                
            # Check Semantic Vector Match
            semantic_category = None
            if emb and history_data:
                best_similarity = -1.0
                best_category = None
                
                for hist in history_data:
                    hist_emb = hist["embedding"]
                    if not hist_emb:
                        continue
                    sim = compute_cosine_similarity(emb, hist_emb)
                    if sim > best_similarity:
                        best_similarity = sim
                        best_category = hist["category"]
                        
                if best_similarity >= 0.88:
                    semantic_category = best_category
                    
            if semantic_category:
                matched_mappings.append({"id": tx["id"], "category": semantic_category})
            else:
                unmatched_txs.append(tx)
                
        return json.dumps({"matched": matched_mappings, "unmatched": unmatched_txs})
    finally:
        db.close()

async def map_with_gemini(unmatched_txs_json: str) -> str:
    """Queries the Gemini model in batch to categorize any remaining transactions.
    Args:
        unmatched_txs_json: JSON string of transactions that need LLM classification.
    Returns:
        JSON string of mappings, e.g. [{"id": "uuid", "category": "Food"}]
    """
    txs = json.loads(unmatched_txs_json)
    if not txs:
        return json.dumps([])
        
    from ..database import SessionLocal
    db = SessionLocal()
    
    try:
        # Fetch categories from DB
        from ..models import Category
        db_categories = db.query(Category.name).all()
        categories = [c[0] for c in db_categories] if db_categories else PREDEFINED_CATEGORIES
    finally:
        db.close()

    llm_input = []
    for idx, tx in enumerate(txs):
        from ..categorizer import sanitize_description
        llm_input.append({
            "index": idx,
            "description": sanitize_description(tx["description"]),
            "amount": tx["amount"]
        })

    system_instruction = (
        "You are an expert personal finance auditor. Your task is to categorize a batch "
        "of bank transactions into the allowed categories.\n"
        "Choose the most appropriate category based on the description and amount. Guidelines:\n"
        "- 'Online Food delivery': Swiggy, Zomato, Uber Eats\n"
        "- 'Food and Drinks outside': restaurants, cafes, Starbucks, McDonald's, bars, pub, coffee, bakery\n"
        "- 'Online Cab Service': Uber, Ola, Rapido, cab, taxi\n"
        "- 'Grocery' or 'Online Grocery': supermarket, Blinkit, Instacart, grocery store\n"
        "- 'Self-Transfers': transfers between user's own bank accounts, credit card payment transfers, self-settlements.\n"
        "- 'Bank Transfer': transfers/payments to other individuals (P2P), salary credits, cash transfers, payments to third-party entities/merchants.\n"
        "- 'Investment': mutual funds, stocks, shares, SIP, broker transfers\n"
        "Use 'Others' only if absolutely no specific category fits."
    )

    chunk_size = 100
    results_map = {}
    
    for i in range(0, len(llm_input), chunk_size):
        chunk = llm_input[i:i + chunk_size]
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
                results_map[item.index] = item.category
        except Exception as e:
            print(f"Gemini Mapper fallback batch call failed: {e}")
            
    # Map responses back to transaction IDs
    mappings = []
    for idx, tx in enumerate(txs):
        category = results_map.get(idx, "Others")
        mappings.append({"id": tx["id"], "category": category})
        
    return json.dumps(mappings)

def save_mappings_to_db(mappings_json: str) -> str:
    """Saves the final category assignments to the database.
    Args:
        mappings_json: JSON string of mappings [{"id": "uuid", "category": "Food"}]
    Returns:
        Confirmation status text.
    """
    return update_transaction_categories(mappings_json)

# =============================================================================
# Agent Config and Exec Runner
# =============================================================================

async def run_mapper_agent(run_id: str) -> str:
    """Orchestrates Super Agent 2 task to map uncategorized transactions."""
    log_run_step(run_id, "mapping", "Transaction Mapper Agent starting mapping sweep.")
    
    config = LocalAgentConfig(
        system_instructions=(
            "You are Super Agent 2 (Transaction Mapper). Your task is to categorize uncategorized transactions. "
            "1. First, call `get_uncategorized` to fetch transactions that need category assignment. "
            "2. If there are none, return 'No transactions require mapping.' "
            "3. If there are transactions, call `match_locally` to check them against rules and vector similarity. "
            "4. If there are matched items, call `save_mappings_to_db` to write them. "
            "5. If there are unmatched items left, call `map_with_gemini` to categorize them using LLM. "
            "6. Call `save_mappings_to_db` to persist the LLM results as well. "
            "Maintain execution sequence and summarize final results."
        ),
        tools=[get_uncategorized, match_locally, map_with_gemini, save_mappings_to_db]
    )
    
    async with Agent(config) as agent:
        response = await agent.chat("Map all uncategorized transactions in the database.")
        text_out = await response.text()
        
        log_run_step(run_id, "mapping", f"Transaction Mapper Agent result: {text_out}")
        return text_out
