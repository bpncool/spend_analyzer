from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class CategoryBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_custom: bool = False

class CategoryOut(CategoryBase):
    class Config:
        from_attributes = True

class TransactionOut(BaseModel):
    id: str
    date: date
    description: str
    amount: float
    balance_after: Optional[float] = None
    category: Optional[str] = None
    source: str
    account_id: Optional[str] = None
    linked_transaction_id: Optional[str] = None
    ai_rate_limited: bool = False
    
    class Config:
        from_attributes = True

class CategorizationRuleCreate(BaseModel):
    pattern: str
    category: str
    is_regex: bool = False

class CategorizationRuleOut(BaseModel):
    id: str
    pattern: str
    category: str
    is_regex: bool
    user_confirmed: bool

    class Config:
        from_attributes = True

class OverrideRequest(BaseModel):
    transaction_id: str
    category: str
    apply_to_all_matching: bool = True

class LinkRequest(BaseModel):
    transaction_id_1: str
    transaction_id_2: str

class UnlinkRequest(BaseModel):
    transaction_id: str

class ReclassifyRequest(BaseModel):
    transaction_ids: List[str]


class CategorizationResponse(BaseModel):
    category: str = Field(description="The category from the allowed categories list.")
    confidence: float = Field(description="Confidence score of classification, between 0.0 and 1.0.")
    reasoning: str = Field(description="Brief explanation of the choice.")

class InsightOut(BaseModel):
    category: str
    correlation: float
    impact_level: str  # 'High Negative', 'Medium Negative', 'Neutral/Positive'
    savings_rate_impact: float
    recommendation: str

class BatchCategorizationItem(BaseModel):
    index: int = Field(description="The index matching the input transaction.")
    category: str = Field(description="The matched category from the allowed categories list.")
    confidence: float = Field(description="Confidence score of classification, between 0.0 and 1.0.")
    reasoning: str = Field(description="Brief explanation of the choice.")

class BatchCategorizationResponse(BaseModel):
    results: List[BatchCategorizationItem]

class AITransactionItem(BaseModel):
    date: str = Field(description="Transaction date in YYYY-MM-DD format.")
    description: str = Field(description="Transaction narration details.")
    amount: float = Field(description="Transaction amount. Negative for debits/withdrawals, positive for deposits/credits.")
    balance_after: Optional[float] = Field(description="Running balance after this transaction (if visible).")

class AIParsingResponse(BaseModel):
    transactions: List[AITransactionItem]

class AIConfirmRequest(BaseModel):
    file_id: str


class AgentRunOut(BaseModel):
    id: str
    timestamp: datetime
    status: str
    statement_source: str
    log_output: str
    error_message: Optional[str] = None

    class Config:
        from_attributes = True



