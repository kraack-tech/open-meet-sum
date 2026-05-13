import os
from pathlib import Path

from dotenv import load_dotenv


_BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_DIR / ".env", override=False)


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DEFAULT_OWNER_USER_ID = os.getenv("DEFAULT_OWNER_USER_ID", "").strip()
DEFAULT_TEAM_ID = os.getenv("DEFAULT_TEAM_ID", "").strip() or None
PERSIST_MEETINGS = _as_bool(os.getenv("PERSIST_MEETINGS", "1"), default=True)

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
