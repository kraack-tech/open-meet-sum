from sqlalchemy import Column, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID

from db.base import Base


class ChatThread(Base):
    __tablename__ = "chat_thread"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    title = Column(String, nullable=False)
    owner_user_id = Column(UUID(as_uuid=False), ForeignKey("public.app_user.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class ChatMessage(Base):
    __tablename__ = "chat_message"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    chat_id = Column(UUID(as_uuid=False), ForeignKey("public.chat_thread.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_by = Column(UUID(as_uuid=False), ForeignKey("public.app_user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))