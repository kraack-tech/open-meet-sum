from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.config import DATABASE_URL
from db.base import Base

_engine = None
_SessionLocal = None

if DATABASE_URL:
    _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def is_db_enabled() -> bool:
    return _SessionLocal is not None


def _run_column_migrations(connection) -> None:
    """Safely add new columns to existing tables that were created outside create_all."""
    migrations = [
        "ALTER TABLE IF EXISTS public.meeting_summary ADD COLUMN IF NOT EXISTS hitl_model_runtime_name VARCHAR",
        "ALTER TABLE IF EXISTS public.meeting_summary_point ADD COLUMN IF NOT EXISTS matched_phrases JSONB",
        "ALTER TABLE IF EXISTS public.meeting_summary_point ADD COLUMN IF NOT EXISTS point_speakers JSONB",
        """
        CREATE TABLE IF NOT EXISTS public.speaker_profile (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_user_id UUID NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
            display_name VARCHAR NOT NULL,
            normalized_name VARCHAR NOT NULL,
            embedding JSONB NOT NULL,
            sample_count INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (owner_user_id, normalized_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS public.meeting_attendee (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            meeting_id UUID NOT NULL REFERENCES public.meeting(id) ON DELETE CASCADE,
            speaker_profile_id UUID NULL REFERENCES public.speaker_profile(id) ON DELETE SET NULL,
            normalized_name VARCHAR NOT NULL,
            display_name VARCHAR NOT NULL,
            created_by UUID NULL REFERENCES public.app_user(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (meeting_id, normalized_name)
        )
        """,
    ]
    for stmt in migrations:
        connection.execute(text(stmt))


def init_db_schema() -> None:
    if _engine is None:
        return

    import models  # noqa: F401

    managed_table_names = [
        "public.user_settings",
        "public.group_workspace",
        "public.group_membership",
        "public.admin_setting",
    ]
    managed_tables = [
        table
        for table_name in managed_table_names
        for table in [Base.metadata.tables.get(table_name)]
        if table is not None
    ]
    if managed_tables:
        Base.metadata.create_all(bind=_engine, tables=managed_tables)

    with _engine.begin() as conn:
        _run_column_migrations(conn)


@contextmanager
def get_db_session():
    if _SessionLocal is None:
        yield None
        return

    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
