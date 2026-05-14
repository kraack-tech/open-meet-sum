from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from db.base import Base


class Meeting(Base):
    __tablename__ = "meeting"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    title = Column(String, nullable=False)
    source = Column(String, nullable=True)
    owner_user_id = Column(UUID(as_uuid=False), ForeignKey("public.app_user.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(UUID(as_uuid=False), nullable=True)
    meeting_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=True)
    visibility = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class MeetingTranscript(Base):
    __tablename__ = "meeting_transcript"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id = Column(UUID(as_uuid=False), ForeignKey("public.meeting.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    transcript_text = Column(Text, nullable=False)
    speaker_labels_enabled = Column(Boolean, nullable=False, server_default=text("false"))
    created_by = Column(UUID(as_uuid=False), ForeignKey("public.app_user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class MeetingSummary(Base):
    __tablename__ = "meeting_summary"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    meeting_id = Column(UUID(as_uuid=False), ForeignKey("public.meeting.id", ondelete="CASCADE"), nullable=False)
    transcript_id = Column(UUID(as_uuid=False), ForeignKey("public.meeting_transcript.id", ondelete="CASCADE"), nullable=True)
    version = Column(Integer, nullable=False)
    summary_text = Column(Text, nullable=False)
    model_runtime_name = Column(String, nullable=True)
    hitl_model_runtime_name = Column(String, nullable=True)
    created_by = Column(UUID(as_uuid=False), ForeignKey("public.app_user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class MeetingSummaryPoint(Base):
    __tablename__ = "meeting_summary_point"
    __table_args__ = {"schema": "public"}

    id = Column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    summary_id = Column(UUID(as_uuid=False), ForeignKey("public.meeting_summary.id", ondelete="CASCADE"), nullable=False)
    ordinal = Column(Integer, nullable=False)
    point_text = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    status = Column(String, nullable=True)
    source_refs = Column(JSONB, nullable=True)
    matched_phrases = Column(JSONB, nullable=True)
    point_speakers = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))