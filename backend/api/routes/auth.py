from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from api.deps.auth import get_current_user
from core.security import create_access_token, hash_password, verify_password
from db.session import get_db_session, is_db_enabled
from schemas.auth import AppSettingsUpdateRequest, LoginRequest, ProfileUpdateRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])

_SUPPORTED_APP_LANGUAGES = {
    "en", "es", "fr", "de", "it", "pt", "nl", "sv", "da", "no", "fi",
    "pl", "cs", "ro", "hu", "tr", "ru", "uk", "el", "he", "ar", "hi",
    "bn", "ta", "te", "ja", "ko", "zh", "id", "vi", "th", "ms",
}


def _raise_schema_not_initialized(exc: Exception):
    pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
    if pgcode in {"42P01", "42703"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database schema is missing or outdated. Ensure the backend startup can initialize the SQLAlchemy models and that the core tables already exist.",
        ) from exc

def _default_settings_payload():
    return {
        "theme": "dark",
        "language": "en",
        "spoken_language": "auto",
        "account_label_mode": "auto",
    }


def _normalize_settings_payload(payload: AppSettingsUpdateRequest | dict | None):
    raw = payload.model_dump() if isinstance(payload, AppSettingsUpdateRequest) else (payload or {})
    defaults = _default_settings_payload()
    theme = str(raw.get("theme", defaults["theme"]))
    language = str(raw.get("language", defaults["language"]))
    spoken_language = str(raw.get("spoken_language", defaults["spoken_language"]))
    account_label_mode = str(raw.get("account_label_mode", defaults["account_label_mode"]))

    if theme not in {"dark", "light"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid theme")
    if language not in _SUPPORTED_APP_LANGUAGES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid language")
    if not spoken_language:
        spoken_language = defaults["spoken_language"]
    if account_label_mode not in {"auto", "display_name", "username", "email"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid account label mode")

    return {
        "theme": theme,
        "language": language,
        "spoken_language": spoken_language,
        "account_label_mode": account_label_mode,
    }


@router.post("/register")
def register(payload: RegisterRequest):
    if not is_db_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured")
    if len(payload.password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters")

    try:
        with get_db_session() as db:
            first_user = db.execute(text("SELECT COUNT(*) = 0 FROM public.app_user")).scalar_one()
            existing = db.execute(
                text("SELECT id FROM public.app_user WHERE email = :email LIMIT 1"),
                {"email": payload.email.strip().lower()},
            ).fetchone()
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

            user_row = db.execute(
                text(
                    """
                    INSERT INTO public.app_user (email, username, password_hash, display_name, is_superuser)
                    VALUES (:email, :username, :password_hash, :display_name, :is_superuser)
                    RETURNING id, email, username, display_name, is_superuser
                    """
                ),
                {
                    "email": payload.email.strip().lower(),
                    "username": (payload.username or "").strip() or None,
                    "password_hash": hash_password(payload.password),
                    "display_name": (payload.display_name or "").strip() or None,
                    "is_superuser": first_user,
                },
            ).fetchone()
            db.commit()
    except ProgrammingError as exc:
        _raise_schema_not_initialized(exc)
        raise

    user = dict(user_row._mapping)
    token = create_access_token(str(user["id"]))
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.post("/login")
def login(payload: LoginRequest):
    if not is_db_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured")

    try:
        with get_db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT id, email, username, display_name, password_hash, is_active, is_superuser
                    FROM public.app_user
                    WHERE email = :email
                    LIMIT 1
                    """
                ),
                {"email": payload.email.strip().lower()},
            ).fetchone()
    except ProgrammingError as exc:
        _raise_schema_not_initialized(exc)
        raise

    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user = dict(row._mapping)
    if not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    token = create_access_token(str(user["id"]))
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "username": user["username"],
            "display_name": user["display_name"],
            "is_superuser": user.get("is_superuser", False),
        },
    }


@router.get("/me")
def get_me(current_user=Depends(get_current_user)):
    return {
        "user": {
            "id": current_user["id"],
            "email": current_user["email"],
            "username": current_user.get("username"),
            "display_name": current_user.get("display_name"),
            "is_active": current_user.get("is_active", True),
            "is_superuser": current_user.get("is_superuser", False),
        }
    }


@router.patch("/me")
def update_me(payload: ProfileUpdateRequest, current_user=Depends(get_current_user)):
    if not is_db_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured")

    username = (payload.username or "").strip() or None
    display_name = (payload.display_name or "").strip() or None

    try:
        with get_db_session() as db:
            if username:
                existing = db.execute(
                    text(
                        """
                        SELECT id
                        FROM public.app_user
                        WHERE username = :username AND id <> :user_id
                        LIMIT 1
                        """
                    ),
                    {"username": username, "user_id": current_user["id"]},
                ).fetchone()
                if existing:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already in use")

            row = db.execute(
                text(
                    """
                    UPDATE public.app_user
                    SET username = :username,
                        display_name = :display_name
                    WHERE id = :user_id
                    RETURNING id, email, username, display_name, is_active, is_superuser
                    """
                ),
                {
                    "user_id": current_user["id"],
                    "username": username,
                    "display_name": display_name,
                },
            ).fetchone()
            db.commit()
    except ProgrammingError as exc:
        _raise_schema_not_initialized(exc)
        raise

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return {"user": dict(row._mapping)}


@router.get("/settings")
def get_my_settings(current_user=Depends(get_current_user)):
    if not is_db_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured")

    try:
        with get_db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT theme, language, spoken_language, account_label_mode
                    FROM public.user_settings
                    WHERE user_id = :user_id
                    LIMIT 1
                    """
                ),
                {"user_id": current_user["id"]},
            ).fetchone()
    except ProgrammingError as exc:
        _raise_schema_not_initialized(exc)
        raise

    return {"settings": dict(row._mapping) if row else _default_settings_payload()}


@router.patch("/settings")
def update_my_settings(payload: AppSettingsUpdateRequest, current_user=Depends(get_current_user)):
    if not is_db_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured")

    normalized = _normalize_settings_payload(payload)

    try:
        with get_db_session() as db:
            row = db.execute(
                text(
                    """
                                        INSERT INTO public.user_settings (user_id, theme, language, spoken_language, account_label_mode)
                                        VALUES (:user_id, :theme, :language, :spoken_language, :account_label_mode)
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                      theme = EXCLUDED.theme,
                      language = EXCLUDED.language,
                      spoken_language = EXCLUDED.spoken_language,
                                            account_label_mode = EXCLUDED.account_label_mode,
                      updated_at = NOW()
                                        RETURNING theme, language, spoken_language, account_label_mode
                    """
                ),
                {
                    "user_id": current_user["id"],
                    **normalized,
                },
            ).fetchone()
            db.commit()
    except ProgrammingError as exc:
        _raise_schema_not_initialized(exc)
        raise

    return {"settings": dict(row._mapping) if row else normalized}


@router.get("/admin/overview")
def admin_overview(current_user=Depends(get_current_user)):
    if not current_user.get("is_superuser", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    if not is_db_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured")

    try:
        with get_db_session() as db:
            totals = db.execute(
                text(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM public.app_user) AS user_count,
                      (SELECT COUNT(*) FROM public.chat_thread) AS chat_count,
                      (SELECT COUNT(*) FROM public.meeting) AS meeting_count,
                      (SELECT COUNT(*) FROM public.meeting_summary) AS summary_count
                    """
                )
            ).fetchone()

            recent_users = db.execute(
                text(
                    """
                    SELECT id, email, username, display_name, is_active, is_superuser, created_at
                    FROM public.app_user
                    ORDER BY created_at DESC
                    LIMIT 5
                    """
                )
            ).fetchall()
    except ProgrammingError as exc:
        _raise_schema_not_initialized(exc)
        raise

    return {
        "totals": dict(totals._mapping) if totals else {
            "user_count": 0,
            "chat_count": 0,
            "meeting_count": 0,
            "summary_count": 0,
        },
        "recent_users": [dict(row._mapping) for row in recent_users],
        "roadmap": [
            "Knowledge base management",
            "Hosted model providers",
            "Audit and access policies",
        ],
    }
