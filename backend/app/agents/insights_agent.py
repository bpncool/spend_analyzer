import os
import json
from google.antigravity import Agent, LocalAgentConfig
from .utility_agents import log_run_step
from ..analytics import calculate_correlations, generate_natural_language_insights
from ..database import SessionLocal

# =============================================================================
# Tools for Insights Agent
# =============================================================================

def get_spend_correlations() -> str:
    """Executes Pearson correlation on historical monthly category expenses vs net account balances.
    Returns:
        JSON string of correlations list: [{"category": "Drinks", "correlation": -0.65, ...}]
    """
    db = SessionLocal()
    try:
        correlations = calculate_correlations(db)
        return json.dumps(correlations)
    finally:
        db.close()

async def generate_and_log_nlp_insights() -> str:
    """Calls Gemini to draft highly personalized behavior recommendations based on correlations.
    Returns:
        JSON string of final recommendation objects.
    """
    db = SessionLocal()
    try:
        insights = await generate_natural_language_insights(db)
        # Convert schema outputs to list of dicts
        insights_data = [
            {
                "category": i.category,
                "correlation": i.correlation,
                "impact_level": i.impact_level,
                "savings_rate_impact": i.savings_rate_impact,
                "recommendation": i.recommendation
            }
            for i in insights
        ]
        return json.dumps(insights_data)
    finally:
        db.close()

# =============================================================================
# Agent Config and Exec Runner
# =============================================================================

async def run_insights_agent(run_id: str) -> str:
    """Orchestrates Super Agent 3 task to run statistical models and generate finance insights."""
    log_run_step(run_id, "analyzing", "Insights Agent computing spending correlations.")
    
    config = LocalAgentConfig(
        system_instructions=(
            "You are Super Agent 3 (Insights & Correlation Agent). Your task is to calculate "
            "correlation metrics and generate natural language recommendations.\n"
            "1. First, call `get_spend_correlations` to see which categories impact the monthly savings rate negative trends.\n"
            "2. Next, call `generate_and_log_nlp_insights` to run the Gemini analysis and generate behavior tips.\n"
            "3. Finally, review the output. Summarize the highest negative impact category and what behavior shift is needed."
        ),
        tools=[get_spend_correlations, generate_and_log_nlp_insights]
    )
    
    async with Agent(config) as agent:
        response = await agent.chat("Calculate spending correlations and generate insights.")
        text_out = await response.text()
        
        log_run_step(run_id, "analyzing", f"Insights Agent result: {text_out}")
        return text_out
