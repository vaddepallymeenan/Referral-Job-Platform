import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
import uuid
from backend.app.database import Base, is_postgres

# Dynamic Vector Type definition to support both pgvector (PostgreSQL) and JSON storage (SQLite fallback)
if is_postgres():
    from pgvector.sqlalchemy import Vector
    VectorType = Vector(768)
else:
    from sqlalchemy.types import TypeDecorator
    class SQLiteVector(TypeDecorator):
        impl = Text
        cache_ok = True
        
        def process_bind_param(self, value, dialect):
            """Serializes float vector arrays to text strings for SQLite storage."""
            if value is None:
                return None
            import json
            return json.dumps(value)
            
        def process_result_value(self, value, dialect):
            """Deserializes database text strings back to Python float vector lists."""
            if value is None:
                return None
            import json
            return json.loads(value)
    
    VectorType = SQLiteVector()

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    subscription_tier = Column(String, default="free", nullable=False)
    outreach_count = Column(Integer, default=0, nullable=False)

class Resume(Base):
    __tablename__ = "resumes"
    
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    raw_text = Column(Text, nullable=False)
    structured_json = Column(JSON, nullable=False)
    embedding = Column(VectorType, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=False)
    url = Column(String, unique=True, nullable=False, index=True)
    source = Column(String, nullable=False) # e.g. 'greenhouse', 'lever', etc.
    ats_type = Column(String, nullable=False)
    posted_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    embedding = Column(VectorType, nullable=True)

class FitScore(Base):
    __tablename__ = "fit_scores"
    
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    job_id = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    score = Column(Integer, nullable=False)
    gaps_json = Column(JSON, nullable=False)
    scored_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    model_version = Column(String, default="v1.0", nullable=False)

class Application(Base):
    __tablename__ = "applications"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, default="prioritized", nullable=False) # prioritized, applied, interviewing, rejected, offer
    applied_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

class SavedSearchProfile(Base):
    __tablename__ = "saved_search_profiles"
    
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    is_remote = Column(Boolean, default=False, nullable=False)
    location = Column(String, default="Any", nullable=False) # e.g. "India", "US", "Any"
    company_stage = Column(String, default="Any", nullable=False) # e.g. "Series A", "Growth", "Any"
    keywords = Column(String, default="", nullable=False) # comma-separated list of keywords

class CompanySignal(Base):
    __tablename__ = "company_signals"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company = Column(String, nullable=False, index=True)
    signal_type = Column(String, nullable=False) # funding, product_launch
    description = Column(Text, nullable=True)
    weight_boost = Column(Integer, default=15, nullable=False)
    recorded_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

