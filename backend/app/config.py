import os
from pathlib import Path
from dotenv import load_dotenv

# Load root .env file
root_dir = Path(__file__).resolve().parent.parent.parent
load_dotenv(root_dir / ".env")

class Settings:
    PROJECT_NAME: str = "Honest Job Intelligence Platform"
    VERSION: str = "0.1.0"
    
    # LLM Settings (We leverage user's existing Google Gemini API key!)
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    
    # Database Settings
    # Fallback to local SQLite if PostgreSQL / Supabase URL is not configured in .env yet
    DATABASE_URL: str = os.getenv("DATABASE_URL", os.getenv("SUPABASE_DB_URL", "sqlite:///./job_platform.db"))
    
    # Candidate profile defaults for local parsing
    CANDIDATE_NAME: str = os.getenv("CANDIDATE_NAME", "Candidate")
    CANDIDATE_PHONE: str = os.getenv("CANDIDATE_PHONE", "")
    RESUME_PDF_PATH: str = os.getenv("RESUME_PDF_PATH", "")

settings = Settings()
