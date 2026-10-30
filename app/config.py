import os
import sys
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory for application code, templates, and static assets
if getattr(sys, "frozen", False):
    # PyInstaller creates a temp folder and stores path in _MEIPASS
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

# Writable application data directory (for DB, uploads, reports, logs)
def resolve_data_dir() -> Path:
    custom_dir = os.environ.get("GRIPHER_DATA_DIR")
    if custom_dir:
        p = Path(custom_dir)
    elif getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home())
        p = Path(local_app_data) / "Gripher"
    else:
        p = BASE_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p

DATA_DIR = resolve_data_dir()

def resolve_secret_key(data_dir: Path, default_key: str) -> str:
    key_file = data_dir / "secret.key"
    env_key = os.environ.get("SECRET_KEY")
    if env_key and env_key != "finrecon-super-secret-jwt-key-change-in-production-2026-xyz":
        return env_key
    if key_file.exists():
        try:
            stored = key_file.read_text(encoding="utf-8").strip()
            if len(stored) >= 32:
                return stored
        except Exception:
            pass
    # Generate a strong cryptographically secure key and persist it locally
    new_key = secrets.token_hex(32)
    try:
        key_file.write_text(new_key, encoding="utf-8")
    except Exception:
        pass
    return new_key

class Settings(BaseSettings):
    APP_NAME: str = "Gripher"
    APP_TAGLINE: str = "Intelligent Financial Reconciliation Platform"
    APP_ENV: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "127.0.0.1"

    # Security & JWT
    SECRET_KEY: str = "finrecon-super-secret-jwt-key-change-in-production-2026-xyz"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # Database
    DATABASE_URL: str = f"sqlite:///{DATA_DIR / 'finrecon.db'}"

    # Storage paths
    DATA_DIR: Path = DATA_DIR
    UPLOAD_DIR: Path = DATA_DIR / "uploads"
    REPORTS_DIR: Path = DATA_DIR / "generated_reports"
    SAMPLE_DIR: Path = BASE_DIR / "sample_files"
    LOGS_DIR: Path = DATA_DIR / "logs"

    # Reconciliation Weights (Total = 100)
    WEIGHT_INVOICE_NUMBER: float = 40.0
    WEIGHT_CUSTOMER_NAME: float = 25.0
    WEIGHT_AMOUNT: float = 20.0
    WEIGHT_DATE_PROXIMITY: float = 15.0

    # Decision Thresholds & Safeguards
    AUTO_MATCH_THRESHOLD: float = 85.0
    REVIEW_QUEUE_THRESHOLD: float = 60.0
    AMBIGUITY_MARGIN: float = 5.0  # Scores within 5% of top match are sent to review queue
    DATE_TOLERANCE_DAYS: int = 30

    # Initial Admin Setup
    ADMIN_EMAIL: str = "admin@finrecon.ai"
    ADMIN_PASSWORD: str = "Admin@123456"
    ADMIN_NAME: str = "System Administrator"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# Secure the secret key
if settings.APP_ENV != "development" or settings.SECRET_KEY.startswith("finrecon-super-secret"):
    settings.SECRET_KEY = resolve_secret_key(DATA_DIR, settings.SECRET_KEY)

# Ensure directories exist
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
settings.SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
