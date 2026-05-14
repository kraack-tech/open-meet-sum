from sqlalchemy import Column, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID

from db.base import Base


class UserSettings(Base):
    __tablename__ = "user_settings"
    __table_args__ = {"schema": "public"}

    user_id = Column(UUID(as_uuid=False), ForeignKey("public.app_user.id", ondelete="CASCADE"), primary_key=True)
    theme = Column(String, nullable=False, server_default=text("'dark'"))
    language = Column(String, nullable=False, server_default=text("'en'"))
    spoken_language = Column(String, nullable=False, server_default=text("'auto'"))
    account_label_mode = Column(String, nullable=False, server_default=text("'auto'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))