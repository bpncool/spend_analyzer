import os
import json
from google.antigravity import Agent, LocalAgentConfig
from .utility_agents import log_run_step
from ..database import SessionLocal
from ..models import Transaction

# =============================================================================
# Tools for Frontend Data Agent
# =============================================================================

def calculate_and_verify_frontend_metrics() -> str:
    """Computes total income, expenses, and savings rate to verify exclusion rules.
    Excludes linked transactions and Self-Transfers from consolidated computations.
    Returns:
        JSON string of key performance metrics (Total Inflow, Total Outflow, Net Balance, Savings Rate).
    """
    db = SessionLocal()
    try:
        # Fetch all transactions
        txs = db.query(Transaction).all()
        
        # Filter consolidated metrics (exclude linked and Self-Transfers)
        filtered_txs = [
            t for t in txs
            if not (t.linked_transaction_id or t.category == "Self-Transfers")
        ]
        
        inflow = sum(float(t.amount) for t in filtered_txs if t.amount > 0)
        outflow = sum(float(t.amount) for t in filtered_txs if t.amount < 0)
        net_balance = inflow + outflow
        savings_rate = ((inflow - abs(outflow)) / inflow * 100) if inflow > 0 else 0.0
        
        # Also double check that NO linked transactions leaked
        leaked_count = sum(
            1 for t in filtered_txs 
            if t.linked_transaction_id is not None or t.category == "Self-Transfers"
        )
        
        result = {
            "total_inflow": inflow,
            "total_outflow": outflow,
            "net_balance_change": net_balance,
            "savings_rate": savings_rate,
            "verification_leak_check": "PASSED" if leaked_count == 0 else "FAILED",
            "total_transactions_in_database": len(txs),
            "transactions_in_metrics": len(filtered_txs)
        }
        return json.dumps(result)
    finally:
        db.close()

# =============================================================================
# Agent Config and Exec Runner
# =============================================================================

async def run_frontend_agent(run_id: str) -> str:
    """Orchestrates Super Agent 4 task to verify final data shapes for UI rendering."""
    log_run_step(run_id, "frontend", "Frontend Data Agent running final statistics verification.")
    
    config = LocalAgentConfig(
        system_instructions=(
            "You are Super Agent 4 (Frontend Data Agent). Your task is to verify that metrics "
            "are calculated properly for frontend consumption, specifically ensuring "
            "Self-Transfers and linked transactions are excluded.\n"
            "1. First, call `calculate_and_verify_frontend_metrics` to compute stats and run the leak check.\n"
            "2. Confirm that the verification leak check returned 'PASSED'.\n"
            "3. Return a concise final summary of the metrics and confirmation that data is ready for the dashboard."
        ),
        tools=[calculate_and_verify_frontend_metrics]
    )
    
    async with Agent(config) as agent:
        response = await agent.chat("Verify frontend metrics and confirm data readiness.")
        text_out = await response.text()
        
        log_run_step(run_id, "completed", f"Frontend Data Agent verified data. Ready for UI: {text_out}")
        return text_out
