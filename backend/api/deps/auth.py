from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import text

from core.config import JWT_ALGORITHM, JWT_SECRET_KEY
from db.session import get_db_session, is_db_enabled

bearer_scheme = HTTPBearer(auto_error=False)


def _resolve_user_from_credentials(credentials: HTTPAuthorizationCredentials | None):
    if not is_db_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured")

    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    with get_db_session() as db:
        row = db.execute(
            text(
                """
                SELECT id, email, username, display_name, is_active, is_superuser
                FROM app_user
                WHERE id = :id
                LIMIT 1
                """
            ),
            {"id": user_id},
        ).fetchone()

    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    user = dict(row._mapping)
    if not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    return _resolve_user_from_credentials(credentials)


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    if not is_db_enabled() or credentials is None or not credentials.credentials:
        return None
    try:
        return _resolve_user_from_credentials(credentials)
    except HTTPException:
        return None
