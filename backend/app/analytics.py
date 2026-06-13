from typing import List, Dict, Any
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from google.genai.errors import APIError

from .models import Transaction
from .schemas import InsightOut
from .categorizer import gemini_client
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


DISCRETIONARY_CATEGORIES = [
    "Online Cab Service",
    "Food and Drinks outside",
    "Online Food delivery",
    "Online Grocery",
    "Grocery",
    "Drinks",
    "Others"
]

def calculate_correlations(db: Session) -> List[Dict[str, Any]]:
    """
    Groups transaction data by month, computes category expenditures and net balance delta,
    and runs a Pearson correlation to isolate categories hurting the savings rate.
    """
    # Load transactions
    stmt = select(Transaction)
    transactions = db.scalars(stmt).all()
    
    if len(transactions) < 5:
        # Not enough data for correlation
        return []
        
    data = []
    for tx in transactions:
        data.append({
            "date": pd.to_datetime(tx.date),
            "amount": float(tx.amount),
            "category": tx.category or "Others"
        })
        
    df = pd.DataFrame(data)
    df["month"] = df["date"].dt.to_period("M")
    
    # Pivot to get monthly sums per category
    # Columns: categories, Row index: month
    monthly_pivot = df.pivot_table(
        index="month",
        columns="category",
        values="amount",
        aggfunc="sum"
    ).fillna(0.0)
    
    # Calculate net balance delta per month (sum of all incomes and expenses)
    monthly_balance_delta = df.groupby("month")["amount"].sum()
    
    # We want absolute values for expenses to correlate "higher spending" with "lower balance delta"
    # An expense is represented as a negative value, so converting to positive:
    for col in monthly_pivot.columns:
        # Expenses are typically negative. If they are negative, make them positive for expense correlation analysis
        # Income is positive (e.g. Investment payouts or Bank Transfers in)
        # For discretionary categories, we treat them as absolute spending
        monthly_pivot[col] = monthly_pivot[col].apply(lambda x: abs(x) if x < 0 else 0.0)
        
    monthly_pivot["balance_delta"] = monthly_balance_delta
    
    # Calculate Pearson correlation matrix
    correlation_matrix = monthly_pivot.corr()["balance_delta"].drop("balance_delta", errors="ignore").fillna(0.0)
    
    results = []
    for category, corr in correlation_matrix.items():
        # Correlation will be negative if higher category spend is associated with a lower balance delta
        val = float(corr)
        
        # Classify impact level
        if val <= -0.5:
            impact = "High Negative"
        elif val <= -0.2:
            impact = "Medium Negative"
        else:
            impact = "Neutral/Positive"
            
        # Estimate average savings impact per $100 spent in this category
        # Simple estimation: coefficient slope or simplified ratio
        # Let's keep it as a metric: if we decrease category spend, it increases balance delta by -corr * spend
        savings_impact = -val * 100.0
        
        results.append({
            "category": str(category),
            "correlation": val,
            "impact_level": impact,
            "savings_rate_impact": savings_impact
        })
        
    # Sort so categories with highest negative impact (lowest negative correlation coefficient) are first
    results.sort(key=lambda x: x["correlation"])
    return results

async def generate_natural_language_insights(db: Session) -> List[InsightOut]:
    """
    Executes correlation logic and invokes Gemini to draft highly personalized,
    actionable text recommendations for the dashboard.
    """
    correlations = calculate_correlations(db)
    
    if not correlations:
        # Fallback default recommendations if data is sparse
        return [
            InsightOut(
                category="General",
                correlation=0.0,
                impact_level="Neutral/Positive",
                savings_rate_impact=0.0,
                recommendation="Please upload at least two months of statements to unlock behavioral analytics and savings insights."
            )
        ]
        
    insights = []
    
    # If Gemini is configured and not rate-limited, use it to generate highly engaging natural language copy
    if gemini_client and not is_ai_rate_limited():
        corr_summary = ""
        for c in correlations:
            corr_summary += f"- {c['category']}: correlation coefficient={c['correlation']:.2f}, impact level={c['impact_level']}, savings impact per $100={c['savings_rate_impact']:.2f}%\n"
            
        prompt = f"""
        Here is the Pearson correlation summary of a user's discretionary spending categories against their net monthly account balance changes:
        {corr_summary}

        Note: A negative correlation indicates that higher spending in that category is strongly tied to a lower monthly savings delta.

        For each category, write a short, highly actionable 1-sentence recommendation on how the user should adjust their behavior.
        Format your response as a list of bullet points matching the categories exactly.
        Example format:
        [Category Name]: [Short Recommendation]
        """
        
        try:
            response = gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config={"temperature": 0.3}
            )
            # Parse responses out from bullet text lines
            text_lines = response.text.split("\n")
            recommendations_map = {}
            for line in text_lines:
                if ":" in line:
                    parts = line.split(":", 1)
                    cat_key = parts[0].replace("-", "").strip()
                    rec_val = parts[1].strip()
                    recommendations_map[cat_key.lower()] = rec_val
                    
            for c in correlations:
                rec = recommendations_map.get(
                    c["category"].lower(),
                    f"Spending in {c['category']} has a negative correlation of {c['correlation']:.2f} on your savings rate. Consider trimming this."
                )
                insights.append(InsightOut(
                    category=c["category"],
                    correlation=c["correlation"],
                    impact_level=c["impact_level"],
                    savings_rate_impact=c["savings_rate_impact"],
                    recommendation=rec
                ))
            return insights
        except Exception as e:
            print(f"Gemini insight generation failed: {e}")
            if _is_rate_limit_error(e):
                trigger_ai_rate_limit(5)
                if should_send_notification():
                    send_notification_email(
                        "Spend Analyzer: Gemini API Rate Limit Triggered",
                        "The Gemini API rate limit has been reached (429/RESOURCE_EXHAUSTED). The system is falling back to local rule and vector similarity matching."
                    )
            
    # Standard rule-based fallback recommendations
    for c in correlations:
        if c["impact_level"] == "High Negative":
            rec = f"Our model detected a strong negative trend. Reducing spending in {c['category']} is your highest leverage target to increase savings."
        elif c["impact_level"] == "Medium Negative":
            rec = f"Spending in {c['category']} is dragging down your monthly growth. Try setting a strict monthly cap here."
        else:
            rec = f"Spending in {c['category']} has a negligible or positive impact on your net balance."
            
        insights.append(InsightOut(
            category=c["category"],
            correlation=c["correlation"],
            impact_level=c["impact_level"],
            savings_rate_impact=c["savings_rate_impact"],
            recommendation=rec
        ))
        
    return insights

