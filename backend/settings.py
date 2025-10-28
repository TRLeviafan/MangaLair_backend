from pydantic import BaseModel
import os
from dotenv import load_dotenv

# Load .env if present at project root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
env_path = os.path.join(ROOT, ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)

class Settings(BaseModel):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    PUBLIC_BASE: str = os.getenv("PUBLIC_BASE", "")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:8000")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data.db")

settings = Settings()
