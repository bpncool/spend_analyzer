import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./finance.db")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", "super-secret-temporary-32-byte-key!!")
    
settings = Settings()
