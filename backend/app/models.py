import json
import uuid
from sqlalchemy import Column, String, Date, Numeric, Boolean, JSON, Text, TypeDecorator, ForeignKey, DateTime, func
from .database import Base
from .config import settings

# A fallback SQLAlchemy type that stores float lists as JSON string in SQLite
class VectorFallbackType(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, list):
            return json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return json.loads(value)
        except Exception:
            return value

# Determine if pgvector is available and DATABASE_URL is postgresql
if settings.DATABASE_URL.startswith("postgresql"):
    try:
        from pgvector.sqlalchemy import Vector
        EmbeddingType = Vector(384)
    except ImportError:
        EmbeddingType = VectorFallbackType()
else:
    EmbeddingType = VectorFallbackType()

class Category(Base):
    __tablename__ = "categories"

    name = Column(String(50), primary_key=True)
    description = Column(Text, nullable=True)
    is_custom = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(String(100), nullable=True)
    date = Column(Date, nullable=False)
    description = Column(Text, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    balance_after = Column(Numeric(12, 2), nullable=True)
    category = Column(String(50), ForeignKey("categories.name"), nullable=True)
    source = Column(String(50), nullable=False)
    raw_payload = Column(JSON, nullable=True)
    description_embedding = Column(EmbeddingType, nullable=True)
    exclude_from_matching = Column(Boolean, default=False, nullable=False)
    linked_transaction_id = Column(String(36), ForeignKey("transactions.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())



class CategorizationRule(Base):
    __tablename__ = "categorization_rules"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pattern = Column(String(255), unique=True, nullable=False)
    category = Column(String(50), ForeignKey("categories.name"), nullable=False)
    is_regex = Column(Boolean, default=False)
    user_confirmed = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime, server_default=func.now())
    status = Column(String(50), nullable=False)  # started, parsing, mapping, analyzing, frontend, completed, failed
    statement_source = Column(String(255), nullable=False)
    log_output = Column(Text, nullable=False)  # JSON-encoded array of log strings
    error_message = Column(Text, nullable=True)

