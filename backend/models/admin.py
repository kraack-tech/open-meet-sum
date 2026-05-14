from sqlalchemy import Column, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from db.base import Base


class GroupWorkspace(Base):
    __tablename__ = "group_workspace"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    sharing_scope = Column(String, nullable=False, server_default=text("'group_admins'"))
    permissions = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class GroupMembership(Base):
    __tablename__ = "group_membership"
    __table_args__ = {"schema": "public"}

    group_id = Column(UUID(as_uuid=False), ForeignKey("public.group_workspace.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("public.app_user.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String, nullable=False, server_default=text("'member'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class AdminSetting(Base):
    __tablename__ = "admin_setting"
    __table_args__ = {"schema": "public"}

    key = Column(String, primary_key=True)
    value = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))