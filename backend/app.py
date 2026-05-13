from fastapi import FastAPI, UploadFile, File, WebSocket, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi import HTTPException
from pydantic import BaseModel
import os
import re
import json
import uuid
import logging
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
import whisper
import soundfile as sf
from services.summary_service import (
    generate_summary,
    generate_summary_with_sources,
    generate_summary_hitl,
    generate_meeting_title,
    revise_summary_bullet_with_feedback,
    converse_about_bullet,
)
from speaker_recognition import LocalSpeakerRecognizer
import numpy as np 
import shutil
from fastapi import FastAPI, WebSocket
import tempfile

try:
    from faster_whisper import WhisperModel
except Exception as exc:
    WhisperModel = None
    logging.getLogger("meetsum.db").warning(
        "faster-whisper unavailable; falling back to whisper for segment transcription: %s",
        exc,
    )

import tempfile
import subprocess
from sqlalchemy import text

from api.routes.auth import router as auth_router
from api.routes.admin import router as admin_router
from api.routes.sidebar import router as sidebar_router
from api.deps.auth import get_current_user
from core.config import DEFAULT_OWNER_USER_ID, DEFAULT_TEAM_ID, PERSIST_MEETINGS, CORS_ORIGINS
from db.session import get_db_session, init_db_schema, is_db_enabled


app = FastAPI()
logger = logging.getLogger("meetsum.db")
uvicorn_logger = logging.getLogger("uvicorn.error")
if uvicorn_logger.handlers:
    logger.handlers = uvicorn_logger.handlers
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

def _init_speaker_recognizer_with_logs() -> LocalSpeakerRecognizer:
    start = time.time()
    done = threading.Event()
    holder: dict[str, LocalSpeakerRecognizer] = {}
    error_holder: dict[str, Exception] = {}

    def _build() -> None:
        try:
            holder["value"] = LocalSpeakerRecognizer()
        except Exception as exc:
            error_holder["error"] = exc
        finally:
            done.set()

    print("[startup] Initializing speaker recognizer...", flush=True)
    logger.info("Initializing speaker recognizer")
    worker = threading.Thread(target=_build, daemon=True)
    worker.start()

    while not done.wait(10):
        elapsed = int(time.time() - start)
        print(f"[startup] Speaker recognizer still initializing... elapsed={elapsed}s", flush=True)
        logger.info("Speaker recognizer still initializing... elapsed=%ss", elapsed)

    if "error" in error_holder:
        raise error_holder["error"]

    elapsed = int(time.time() - start)
    print(f"[startup] Speaker recognizer ready: elapsed={elapsed}s", flush=True)
    logger.info("Speaker recognizer ready: elapsed=%ss", elapsed)
    return holder["value"]


speaker_recognizer = _init_speaker_recognizer_with_logs()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(sidebar_router)


@app.on_event("startup")
def initialize_db_models():
    init_db_schema()
    ensure_first_user_superuser()


def ensure_first_user_superuser():
    if not is_db_enabled():
        return

    try:
        with get_db_session() as db:
            if db is None:
                return
            promoted_user = db.execute(
                text(
                    """
                    UPDATE public.app_user
                    SET is_superuser = TRUE,
                        updated_at = NOW()
                    WHERE id = (
                      SELECT id
                      FROM public.app_user
                      ORDER BY created_at ASC, id ASC
                      LIMIT 1
                    )
                      AND NOT EXISTS (
                        SELECT 1
                        FROM public.app_user
                        WHERE is_superuser = TRUE
                      )
                    RETURNING id
                    """
                )
            ).fetchone()
            db.commit()
            if promoted_user:
                logger.info("Promoted initial user %s to superuser", promoted_user.id)
    except Exception as exc:
        logger.exception("Failed to ensure initial superuser: %s", exc)

class SummaryRequest(BaseModel):
    transcript: str
    meeting_id: str | None = None


def _resolve_owner_user_id(owner_user_id: str | None) -> str:
    return str(owner_user_id or "").strip() or DEFAULT_OWNER_USER_ID


def _normalize_person_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip()).lower()


def _display_person_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip())


def _serialize_embedding(embedding: np.ndarray) -> list[float]:
    return [float(v) for v in embedding.tolist()]


def _deserialize_embedding(raw_value) -> np.ndarray | None:
    if isinstance(raw_value, list):
        values = raw_value
    elif isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except Exception:
            return None
        values = parsed if isinstance(parsed, list) else None
    else:
        values = None
    if not isinstance(values, list) or not values:
        return None
    arr = np.array(values, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm <= 0:
        return None
    return arr / norm


def _load_speaker_profiles_for_owner(owner_user_id: str) -> dict[str, np.ndarray]:
    if not is_db_enabled():
        return {}
    with get_db_session() as db:
        if db is None:
            return {}
        rows = db.execute(
            text(
                """
                SELECT display_name, embedding
                FROM public.speaker_profile
                WHERE owner_user_id = :owner_user_id
                ORDER BY updated_at DESC
                """
            ),
            {"owner_user_id": owner_user_id},
        ).fetchall()
    profiles: dict[str, np.ndarray] = {}
    for row in rows:
        emb = _deserialize_embedding(row.embedding)
        if emb is None:
            continue
        profiles[str(row.display_name)] = emb
    return profiles


def _filter_profiles_for_attendees(profiles: dict[str, np.ndarray], attendees: list[str]) -> dict[str, np.ndarray]:
    if not profiles:
        return {}
    if not attendees:
        return {}
    allowed = {
        _normalize_person_name(name)
        for name in attendees
        if _normalize_person_name(name)
    }
    return {
        name: embedding
        for name, embedding in profiles.items()
        if _normalize_person_name(name) in allowed
    }


def _upsert_speaker_profile(owner_user_id: str, name: str, embedding: np.ndarray) -> dict[str, object] | None:
    if not is_db_enabled():
        return None

    display_name = _display_person_name(name)
    normalized_name = _normalize_person_name(name)
    if not display_name or not normalized_name:
        return None

    with get_db_session() as db:
        if db is None:
            return None
        try:
            existing = db.execute(
                text(
                    """
                    SELECT id, display_name, sample_count, embedding
                    FROM public.speaker_profile
                    WHERE owner_user_id = :owner_user_id
                      AND normalized_name = :normalized_name
                    LIMIT 1
                    """
                ),
                {"owner_user_id": owner_user_id, "normalized_name": normalized_name},
            ).fetchone()

            if existing:
                existing_embedding = _deserialize_embedding(existing.embedding)
                existing_count = int(existing.sample_count or 1)
                if existing_embedding is None:
                    merged = embedding
                else:
                    merged = ((existing_embedding * existing_count) + embedding) / (existing_count + 1)
                    merged_norm = float(np.linalg.norm(merged))
                    merged = merged / merged_norm if merged_norm > 0 else embedding

                updated = db.execute(
                    text(
                        """
                        UPDATE public.speaker_profile
                        SET display_name = :display_name,
                            embedding = CAST(:embedding AS jsonb),
                            sample_count = :sample_count,
                            updated_at = NOW()
                        WHERE id = :id
                        RETURNING id, display_name, sample_count
                        """
                    ),
                    {
                        "id": existing.id,
                        "display_name": display_name,
                        "embedding": json.dumps(_serialize_embedding(merged)),
                        "sample_count": existing_count + 1,
                    },
                ).fetchone()
                db.commit()
                if not updated:
                    return None
                return {
                    "id": str(updated.id),
                    "name": str(updated.display_name),
                    "sample_count": int(updated.sample_count or 1),
                    "mode": "updated",
                }

            created = db.execute(
                text(
                    """
                    INSERT INTO public.speaker_profile (
                      owner_user_id, display_name, normalized_name, embedding, sample_count
                    ) VALUES (
                      :owner_user_id, :display_name, :normalized_name, CAST(:embedding AS jsonb), 1
                    )
                    RETURNING id, display_name, sample_count
                    """
                ),
                {
                    "owner_user_id": owner_user_id,
                    "display_name": display_name,
                    "normalized_name": normalized_name,
                    "embedding": json.dumps(_serialize_embedding(embedding)),
                },
            ).fetchone()
            db.commit()
            if not created:
                return None
            return {
                "id": str(created.id),
                "name": str(created.display_name),
                "sample_count": int(created.sample_count or 1),
                "mode": "created",
            }
        except Exception:
            db.rollback()
            raise


def _persist_meeting_attendees(meeting_id: str, owner_user_id: str, attendees: list[str]) -> None:
    if not attendees or not is_db_enabled():
        return
    unique_attendees: list[str] = []
    seen: set[str] = set()
    for attendee in attendees:
        display_name = _display_person_name(attendee)
        normalized_name = _normalize_person_name(attendee)
        if not display_name or not normalized_name or normalized_name in seen:
            continue
        seen.add(normalized_name)
        unique_attendees.append(display_name)

    if not unique_attendees:
        return

    with get_db_session() as db:
        if db is None:
            return
        try:
            for display_name in unique_attendees:
                normalized_name = _normalize_person_name(display_name)
                profile = db.execute(
                    text(
                        """
                        SELECT id
                        FROM public.speaker_profile
                        WHERE owner_user_id = :owner_user_id
                          AND normalized_name = :normalized_name
                        LIMIT 1
                        """
                    ),
                    {"owner_user_id": owner_user_id, "normalized_name": normalized_name},
                ).fetchone()
                db.execute(
                    text(
                        """
                        INSERT INTO public.meeting_attendee (
                          meeting_id, speaker_profile_id, normalized_name, display_name, created_by
                        ) VALUES (
                          :meeting_id, :speaker_profile_id, :normalized_name, :display_name, :created_by
                        )
                        ON CONFLICT (meeting_id, normalized_name)
                        DO UPDATE SET
                          speaker_profile_id = EXCLUDED.speaker_profile_id,
                          display_name = EXCLUDED.display_name
                        """
                    ),
                    {
                        "meeting_id": meeting_id,
                        "speaker_profile_id": str(profile.id) if profile else None,
                        "normalized_name": normalized_name,
                        "display_name": display_name,
                        "created_by": owner_user_id,
                    },
                )
            db.commit()
        except Exception:
            db.rollback()
            raise


def _parse_attendees_payload(raw_attendees: str | None) -> list[str]:
    if not raw_attendees:
        return []
    try:
        parsed = json.loads(raw_attendees)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(value).strip() for value in parsed if str(value).strip()]


def _extract_attendees_from_segments(segments: list[dict]) -> list[str]:
    attendees: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        speaker = str(segment.get("speaker") or "").strip()
        if not speaker or speaker.lower() == "unknown":
            continue
        normalized = _normalize_person_name(speaker)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        attendees.append(_display_person_name(speaker))
    return attendees


def _can_persist_meetings(owner_user_id: str | None) -> bool:
    return PERSIST_MEETINGS and is_db_enabled() and bool(_resolve_owner_user_id(owner_user_id))


def _create_meeting_with_transcript(db, transcript: str, source: str, owner_user_id: str):
    meeting_id = str(uuid.uuid4())
    transcript_id = str(uuid.uuid4())
    meeting_date = datetime.now(timezone.utc)
    fallback_title = f"{source.title()} meeting {meeting_date.strftime('%Y-%m-%d %H:%M')}"
    try:
        title = (generate_meeting_title(transcript=str(transcript), source=source) or "").strip() or fallback_title
    except Exception:
        title = fallback_title

    db.execute(
        text(
            """
            INSERT INTO meeting (
              id, title, source, owner_user_id, team_id, meeting_date, status, visibility
            ) VALUES (
              :id, :title, :source, :owner_user_id, :team_id, :meeting_date, 'completed', 'private'
            )
            """
        ),
        {
            "id": meeting_id,
            "title": title,
            "source": source,
            "owner_user_id": owner_user_id,
            "team_id": DEFAULT_TEAM_ID,
            "meeting_date": meeting_date,
        },
    )

    db.execute(
        text(
            """
            INSERT INTO meeting_transcript (
              id, meeting_id, version, transcript_text, speaker_labels_enabled, created_by
            ) VALUES (
              :id, :meeting_id, 1, :transcript_text, :speaker_labels_enabled, :created_by
            )
            """
        ),
        {
            "id": transcript_id,
            "meeting_id": meeting_id,
            "transcript_text": transcript,
            "speaker_labels_enabled": bool(re.search(r"\]\s*[^:\n]{1,80}:", transcript)),
            "created_by": owner_user_id,
        },
    )

    return meeting_id, transcript_id


def _find_latest_transcript_row(db, transcript: str, owner_user_id: str):
    return db.execute(
        text(
            """
            SELECT mt.id, mt.meeting_id
            FROM meeting_transcript mt
            JOIN meeting m ON m.id = mt.meeting_id
            WHERE mt.transcript_text = :transcript_text
              AND m.owner_user_id = :owner_user_id
            ORDER BY mt.created_at DESC
            LIMIT 1
            """
        ),
        {"transcript_text": transcript, "owner_user_id": owner_user_id},
    ).fetchone()


def _find_latest_transcript_for_meeting(db, meeting_id: str, owner_user_id: str):
    return db.execute(
        text(
            """
            SELECT mt.id, mt.meeting_id
            FROM meeting_transcript mt
            JOIN meeting m ON m.id = mt.meeting_id
            WHERE mt.meeting_id = :meeting_id
              AND m.owner_user_id = :owner_user_id
            ORDER BY mt.version DESC, mt.created_at DESC
            LIMIT 1
            """
        ),
        {"meeting_id": meeting_id, "owner_user_id": owner_user_id},
    ).fetchone()


def _extract_speaker_from_transcript_line(line: str) -> str | None:
    match = re.match(r"^\s*(?:\[(?:\d{2}:\d{2}(?::\d{2})?)\]\s*)?([^:\n]{1,80}):\s*", str(line or ""))
    if not match:
        return None
    speaker = str(match.group(1) or "").strip()
    return speaker or None


def _normalize_source_line_index(source_ref, total_lines: int) -> int | None:
    def _to_index(value) -> int | None:
        try:
            number = int(value)
        except Exception:
            return None
        if 1 <= number <= total_lines:
            return number - 1
        if 0 <= number < total_lines:
            return number
        return None

    if isinstance(source_ref, (int, float, str)):
        return _to_index(source_ref)

    if isinstance(source_ref, dict):
        for key in ("line_number", "line", "index"):
            if key in source_ref:
                idx = _to_index(source_ref.get(key))
                if idx is not None:
                    return idx

    return None


def _collect_point_speakers(transcript_lines: list[str], item: dict) -> list[str]:
    speakers: list[str] = []
    seen: set[str] = set()

    def _push(speaker: str | None) -> None:
        if not speaker:
            return
        normalized = str(speaker).strip()
        if not normalized:
            return
        key = normalized.lower()
        if key in seen:
            return
        seen.add(key)
        speakers.append(normalized)

    source_refs = list(item.get("sources") or []) if isinstance(item.get("sources"), list) else []
    for source_ref in source_refs:
        idx = _normalize_source_line_index(source_ref, len(transcript_lines))
        if idx is None:
            continue
        _push(_extract_speaker_from_transcript_line(transcript_lines[idx]))

    if speakers:
        return speakers

    source_texts = list(item.get("source_texts") or []) if isinstance(item.get("source_texts"), list) else []
    for value in source_texts:
        _push(_extract_speaker_from_transcript_line(str(value or "")))

    if speakers:
        return speakers

    for key in ("matched_phrases", "source_texts"):
        values = list(item.get(key) or []) if isinstance(item.get(key), list) else []
        for value in values:
            needle = str(value or "").strip().lower()
            if not needle:
                continue
            for line in transcript_lines:
                if needle in line.lower():
                    _push(_extract_speaker_from_transcript_line(line))

    if speakers:
        return speakers

    # Final fallback: use lexical overlap between bullet text and transcript lines.
    bullet_text = str(item.get("text") or "").strip().lower()
    bullet_tokens = {token for token in re.findall(r"[a-z0-9]+", bullet_text) if len(token) > 2}
    if not bullet_tokens:
        return speakers

    scored_lines: list[tuple[int, str]] = []
    for line in transcript_lines:
        speaker = _extract_speaker_from_transcript_line(line)
        if not speaker:
            continue
        line_tokens = {token for token in re.findall(r"[a-z0-9]+", line.lower()) if len(token) > 2}
        overlap = len(bullet_tokens.intersection(line_tokens))
        if overlap > 0:
            scored_lines.append((overlap, line))

    scored_lines.sort(key=lambda pair: pair[0], reverse=True)
    for _, line in scored_lines[:3]:
        _push(_extract_speaker_from_transcript_line(line))

    if speakers:
        return speakers

    # Guaranteed fallback: most frequent explicit speakers in transcript.
    speaker_counts: dict[str, int] = {}
    for line in transcript_lines:
        speaker = _extract_speaker_from_transcript_line(line)
        if not speaker:
            continue
        key = speaker.strip()
        if not key:
            continue
        speaker_counts[key] = speaker_counts.get(key, 0) + 1

    top_speakers = sorted(speaker_counts.items(), key=lambda kv: kv[1], reverse=True)[:2]
    for speaker, _ in top_speakers:
        _push(speaker)

    return speakers


def _enrich_summary_items_with_point_speakers(transcript: str, summary_items) -> list[dict]:
    transcript_lines = str(transcript or "").split("\n")
    enriched: list[dict] = []
    for raw_item in summary_items or []:
        if not isinstance(raw_item, dict):
            enriched.append({"text": str(raw_item)})
            continue

        existing = raw_item.get("point_speakers")
        if isinstance(existing, list) and any(str(v).strip() for v in existing):
            point_speakers = [str(v).strip() for v in existing if str(v).strip()]
        else:
            point_speakers = _collect_point_speakers(transcript_lines, raw_item)

        enriched.append({**raw_item, "point_speakers": point_speakers})

    return enriched


def _persist_summary_points(db, summary_id: str, summary_items, hitl_items):
    confidence_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
    for index, item in enumerate(summary_items or [], start=1):
        point_text = ""
        source_refs = []
        confidence = None

        matched_phrases = []
        point_speakers = []
        if isinstance(item, dict):
            point_text = str(item.get("text", "")).strip()
            source_refs = item.get("sources") or []
            raw_phrases = item.get("matched_phrases")
            if isinstance(raw_phrases, list):
                matched_phrases = [str(p) for p in raw_phrases if p]
            raw_speakers = item.get("point_speakers")
            if isinstance(raw_speakers, list):
                point_speakers = [str(s) for s in raw_speakers if s]
        else:
            point_text = str(item).strip()

        if index - 1 < len(hitl_items or []) and isinstance(hitl_items[index - 1], dict):
            raw_confidence = hitl_items[index - 1].get("confidence")
            if isinstance(raw_confidence, str):
                confidence = confidence_map.get(raw_confidence.strip().lower())
            elif isinstance(raw_confidence, (int, float)):
                confidence = float(raw_confidence)

        if not point_text:
            continue

        db.execute(
            text(
                """
                INSERT INTO meeting_summary_point (
                                    id, summary_id, ordinal, point_text, confidence, status, source_refs, matched_phrases, point_speakers
                ) VALUES (
                  :id, :summary_id, :ordinal, :point_text, :confidence, 'pending',
                                    CAST(:source_refs AS jsonb), CAST(:matched_phrases AS jsonb), CAST(:point_speakers AS jsonb)
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "summary_id": summary_id,
                "ordinal": index,
                "point_text": point_text,
                "confidence": confidence,
                "source_refs": json.dumps(source_refs),
                "matched_phrases": json.dumps(matched_phrases),
                "point_speakers": json.dumps(point_speakers),
            },
        )


def persist_transcript_only(
    transcript: str,
    source: str,
    owner_user_id: str | None = None,
    reuse_existing: bool = True,
) -> str | None:
    resolved_owner_user_id = _resolve_owner_user_id(owner_user_id)
    if not transcript.strip() or not _can_persist_meetings(resolved_owner_user_id):
        return None

    try:
        with get_db_session() as db:
            if db is None:
                return
            try:
                if reuse_existing:
                    existing = _find_latest_transcript_row(db, transcript, resolved_owner_user_id)
                    if existing:
                        return str(existing.meeting_id)
                meeting_id, _ = _create_meeting_with_transcript(db, transcript, source, resolved_owner_user_id)
                db.commit()
                return str(meeting_id)
            except Exception:
                db.rollback()
                raise
    except Exception as exc:
        logger.exception("Failed to persist transcript: %s", exc)
        return None


def persist_summary_bundle(
    transcript: str,
    summary_payload: dict,
    source_fallback: str,
    owner_user_id: str | None = None,
    meeting_id: str | None = None,
) -> str | None:
    resolved_owner_user_id = _resolve_owner_user_id(owner_user_id)
    if not transcript.strip() or not _can_persist_meetings(resolved_owner_user_id):
        return None

    try:
        with get_db_session() as db:
            if db is None:
                return None

            try:
                if meeting_id:
                    transcript_row = _find_latest_transcript_for_meeting(db, meeting_id, resolved_owner_user_id)
                    if not transcript_row:
                        return None
                    transcript_id = transcript_row.id
                    persisted_meeting_id = transcript_row.meeting_id
                else:
                    transcript_row = _find_latest_transcript_row(db, transcript, resolved_owner_user_id)
                    if transcript_row:
                        transcript_id = transcript_row.id
                        persisted_meeting_id = transcript_row.meeting_id
                    else:
                        persisted_meeting_id, transcript_id = _create_meeting_with_transcript(
                            db,
                            transcript,
                            source_fallback,
                            resolved_owner_user_id,
                        )

                next_version = db.execute(
                    text(
                        """
                        SELECT COALESCE(MAX(version), 0) + 1 AS next_version
                        FROM meeting_summary
                        WHERE meeting_id = :meeting_id
                        """
                    ),
                    {"meeting_id": persisted_meeting_id},
                ).scalar_one()

                summary_id = str(uuid.uuid4())
                summary_text = str(summary_payload.get("summary", "")).strip()
                if not summary_text:
                    return None

                hitl_model = summary_payload.get("hitl_model_used") or {}
                db.execute(
                    text(
                        """
                        INSERT INTO meeting_summary (
                          id, meeting_id, transcript_id, version, summary_text,
                          model_runtime_name, hitl_model_runtime_name, created_by
                        ) VALUES (
                          :id, :meeting_id, :transcript_id, :version, :summary_text,
                          :model_runtime_name, :hitl_model_runtime_name, :created_by
                        )
                        """
                    ),
                    {
                        "id": summary_id,
                        "meeting_id": persisted_meeting_id,
                        "transcript_id": transcript_id,
                        "version": int(next_version),
                        "summary_text": summary_text,
                        "model_runtime_name": str((summary_payload.get("model_used") or {}).get("runtime") or (summary_payload.get("model_used") or {}).get("label") or os.getenv("DEFAULT_MODEL_RUNTIME", "llama3.2:latest")),
                        "hitl_model_runtime_name": str(hitl_model.get("runtime") or hitl_model.get("label") or "") or None,
                        "created_by": resolved_owner_user_id,
                    },
                )

                _persist_summary_points(
                    db,
                    summary_id=summary_id,
                    summary_items=_enrich_summary_items_with_point_speakers(
                        transcript,
                        summary_payload.get("summary_items") or [],
                    ),
                    hitl_items=summary_payload.get("hitl_items") or [],
                )

                db.commit()
                return str(persisted_meeting_id)
            except Exception:
                db.rollback()
                raise
    except Exception as exc:
        logger.exception("Failed to persist summary bundle: %s", exc)
        return None

def _load_whisper_model_with_logs(model_name: str = "large"):
    start = time.time()
    done = threading.Event()

    def _heartbeat() -> None:
        while not done.wait(10):
            elapsed = int(time.time() - start)
            print(
                f"[startup] Whisper model '{model_name}' still loading/download in progress... elapsed={elapsed}s",
                flush=True,
            )
            logger.info(
                "Whisper model '%s' is still loading/download in progress... elapsed=%ss",
                model_name,
                elapsed,
            )

    print(f"[startup] Starting Whisper model load: model={model_name}", flush=True)
    logger.info("Starting Whisper model load: model=%s", model_name)
    heartbeat = threading.Thread(target=_heartbeat, daemon=True)
    heartbeat.start()
    try:
        model = whisper.load_model(model_name)
    finally:
        done.set()

    elapsed = int(time.time() - start)
    print(f"[startup] Whisper model ready: model={model_name} elapsed={elapsed}s", flush=True)
    logger.info("Whisper model ready: model=%s elapsed=%ss", model_name, elapsed)
    return model


# Load Whisper once at startup
whisper_model = _load_whisper_model_with_logs("large")

@app.post("/upload-audio")
async def upload_audio(
    file: UploadFile = File(...),
    speakers: str = Form("1"),
    attendees: str = Form("[]"),
    current_user=Depends(get_current_user),
):
    print("=== DEBUG upload_audio HIT ===", flush=True)
    enable_speakers = speakers == "1"
    owner_user_id = _resolve_owner_user_id(current_user.get("id"))
    attendee_names = _parse_attendees_payload(attendees)

    if enable_speakers:
        profiles = _filter_profiles_for_attendees(
            _load_speaker_profiles_for_owner(owner_user_id),
            attendee_names,
        )
        print(
            f"[upload-audio scope] owner={owner_user_id} attendees={attendee_names} profile_count={len(profiles)} profile_names={sorted(list(profiles.keys()))}",
            flush=True,
        )
        logger.info(
            "upload-audio speaker scope: owner=%s attendees=%s profile_count=%s profile_names=%s",
            owner_user_id,
            attendee_names,
            len(profiles),
            sorted(list(profiles.keys())),
        )
        speaker_recognizer.set_profiles(profiles)

    # Save file temporarily
    os.makedirs("temp", exist_ok=True)
    audio_path = f"temp/{file.filename}"
    with open(audio_path, "wb") as f:
        f.write(await file.read())

    segments = _transcribe_segments(audio_path)
    audio_samples, sample_rate = sf.read(audio_path, dtype="float32")
    payload_segments = build_payload_segments(
        segments,
        audio_samples,
        sample_rate,
        enable_speakers,
        attendee_whitelist=attendee_names if enable_speakers else None,
    )

    split_segments = []
    for seg in payload_segments:
        segment_text = seg["text"].strip()
        sentences = _split_segment_text(segment_text)
        for sentence in sentences:
            split_segments.append({
                "start": seg["start"],
                "speaker": seg.get("speaker"),
                "text": sentence,
            })

    if enable_speakers:
        transcript_lines = [
            f"[{_format_timestamp(seg['start'] or 0)}] {(seg['speaker'] or 'Unknown')}: {seg['text']}"
            for seg in split_segments
        ]
    else:
        transcript_lines = [
            f"[{_format_timestamp(seg['start'] or 0)}] {seg['text']}" for seg in split_segments
        ]

    transcript = "\n".join(transcript_lines)

    if enable_speakers and not attendee_names:
        attendee_names = _extract_attendees_from_segments(split_segments)

    persisted_meeting_id = persist_transcript_only(
        transcript=str(transcript),
        source="upload",
        owner_user_id=owner_user_id,
        reuse_existing=False,
    )
    if not persisted_meeting_id:
        raise HTTPException(status_code=500, detail="Failed to persist uploaded meeting")

    _persist_meeting_attendees(persisted_meeting_id, owner_user_id, attendee_names)

    meeting_date = None
    if is_db_enabled():
        with get_db_session() as db:
            if db is not None:
                meeting_row = db.execute(
                    text(
                        """
                        SELECT meeting_date
                        FROM meeting
                        WHERE id = :meeting_id
                        LIMIT 1
                        """
                    ),
                    {"meeting_id": persisted_meeting_id},
                ).fetchone()
                if meeting_row:
                    meeting_date = meeting_row.meeting_date

    return {
        "transcript": transcript,
        "meeting_id": persisted_meeting_id,
        "meeting_date": meeting_date,
    }


# -------------------------
# Record meeting endpoint
# -------------------------
@app.post("/record-meeting")
async def record_meeting(file: UploadFile = File(...)):
    os.makedirs("temp", exist_ok=True)
    audio_path = f"temp/{file.filename}"
    with open(audio_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    result = whisper_model.transcribe(audio_path)
    transcript = result["text"]

    summary_payload = generate_summary_with_sources(str(transcript))
    return {
        "transcript": transcript,
        "bullets": summary_payload["summary"],
        "summary_items": summary_payload["summary_items"],
    }


@app.get("/speakers")
async def list_speakers(current_user=Depends(get_current_user)):
    owner_user_id = _resolve_owner_user_id(current_user.get("id"))
    if not is_db_enabled():
        return {"items": []}
    with get_db_session() as db:
        if db is None:
            return {"items": []}
        rows = db.execute(
            text(
                """
                SELECT id, display_name, sample_count, updated_at
                FROM public.speaker_profile
                WHERE owner_user_id = :owner_user_id
                ORDER BY updated_at DESC, display_name ASC
                """
            ),
            {"owner_user_id": owner_user_id},
        ).fetchall()
    return {
        "items": [
            {
                "id": str(row.id),
                "name": str(row.display_name),
                "sample_count": int(row.sample_count or 1),
                "updated_at": row.updated_at,
            }
            for row in rows
        ]
    }


@app.delete("/speakers/{speaker_id}")
async def delete_speaker(speaker_id: str, current_user=Depends(get_current_user)):
    owner_user_id = _resolve_owner_user_id(current_user.get("id"))
    if not is_db_enabled():
        raise HTTPException(status_code=503, detail="Database is not enabled")

    try:
        speaker_uuid = str(uuid.UUID(str(speaker_id).strip()))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid speaker id")

    with get_db_session() as db:
        if db is None:
            raise HTTPException(status_code=503, detail="Database session unavailable")

        deleted = db.execute(
            text(
                """
                DELETE FROM public.speaker_profile
                WHERE id = :speaker_id
                  AND owner_user_id = :owner_user_id
                RETURNING id, display_name
                """
            ),
            {
                "speaker_id": speaker_uuid,
                "owner_user_id": owner_user_id,
            },
        ).fetchone()

        if not deleted:
            db.rollback()
            raise HTTPException(status_code=404, detail="Speaker not found")

        db.commit()

    return {
        "ok": True,
        "id": str(deleted.id),
        "name": str(deleted.display_name),
    }


@app.post("/speakers/enroll")
async def enroll_speaker(
    name: str = Form(...),
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    owner_user_id = _resolve_owner_user_id(current_user.get("id"))
    clean_name = _display_person_name(name)
    if not clean_name:
        raise HTTPException(status_code=400, detail="Speaker name is required")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Speaker sample is empty")

    embedding = speaker_recognizer.embed_bytes(data)
    saved = _upsert_speaker_profile(owner_user_id, clean_name, embedding)
    speaker_recognizer.enroll_embedding(clean_name, embedding)

    return {
        "ok": True,
        "name": clean_name,
        "saved": saved or {},
    }









# -------------------------
# LIVER stranscriber
# -------------------------
fw_model = WhisperModel("base", device="cpu") if WhisperModel is not None else None


def _transcribe_segments(audio_path: str):
    if fw_model is not None:
        segments, _ = fw_model.transcribe(audio_path, beam_size=5)
        return list(segments)

    # Fallback mode for environments where ctranslate2 cannot load.
    result = whisper_model.transcribe(audio_path)
    raw_segments = list(result.get("segments") or [])
    return [
        SimpleNamespace(
            start=float(seg.get("start") or 0.0),
            end=float(seg.get("end") or 0.0),
            text=str(seg.get("text") or ""),
        )
        for seg in raw_segments
    ]


def _format_timestamp(seconds: float) -> str:
    total = int(max(0, seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def build_payload_segments(
    segments,
    audio_samples,
    sample_rate,
    enable_speakers: bool,
    offset_seconds: float = 0.0,
    attendee_whitelist: list[str] | None = None,
):
    payload_segments = []
    if not enable_speakers:
        combined = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        if combined:
            payload_segments.append({
                "speaker": None,
                "text": combined,
                "start": offset_seconds,
                "end": None,
            })
        return payload_segments

    allowed_speakers = None
    if attendee_whitelist is not None:
        allowed_speakers = {
            _normalize_person_name(name)
            for name in attendee_whitelist
            if _normalize_person_name(name)
        }

    recognized_count = 0
    unknown_count = 0

    for seg in segments:
        start = int(seg.start * sample_rate)
        end = int(seg.end * sample_rate)
        if end <= start:
            continue

        seg_samples = audio_samples[start:end]
        speaker = speaker_recognizer.identify_samples(seg_samples, sample_rate, allowed_speakers=allowed_speakers)
        if speaker:
            recognized_count += 1
        else:
            unknown_count += 1
        text = seg.text.strip()
        if not text:
            continue

        if payload_segments and payload_segments[-1]["speaker"] == speaker:
            payload_segments[-1]["text"] += " " + text
            payload_segments[-1]["end"] = seg.end + offset_seconds
        else:
            payload_segments.append({
                "speaker": speaker,
                "text": text,
                "start": seg.start + offset_seconds,
                "end": seg.end + offset_seconds,
            })

    if enable_speakers:
        print(
            f"[speaker assignment] recognized={recognized_count} unknown={unknown_count} allowed={sorted(list(allowed_speakers)) if allowed_speakers is not None else None}",
            flush=True,
        )
        logger.info(
            "Speaker assignment stats: recognized=%s unknown=%s allowed=%s",
            recognized_count,
            unknown_count,
            sorted(list(allowed_speakers)) if allowed_speakers is not None else None,
        )

    return payload_segments


@app.websocket("/ws-transcribe")
async def websocket_transcribe(websocket: WebSocket):
    await websocket.accept()
    print("=== DEBUG ws_transcribe HIT ===", flush=True)

    enable_speakers = websocket.query_params.get("speakers") == "1"
    offset_seconds = float(websocket.query_params.get("offset", "0") or 0)
    attendee_names = _parse_attendees_payload(websocket.query_params.get("attendees"))
    print(f"[ws-transcribe params] enable_speakers={enable_speakers} attendees={attendee_names}", flush=True)
    logger.info("ws-transcribe params: enable_speakers=%s attendees=%s", enable_speakers, attendee_names)

    try:
        # Receive exactly one chunk per WS connection
        data = await websocket.receive_bytes()
        if not data:
            pass
            return  # do nothing, close

        # Write chunk to temp WAV
        # delete=False required on Windows (file lock prevents reading by name while open)
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            tmp.write(data)
            tmp.flush()
            tmp.close()
            segments = _transcribe_segments(tmp.name)
            audio_samples, sample_rate = sf.read(tmp.name, dtype="float32")
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        payload_segments = build_payload_segments(
            segments,
            audio_samples,
            sample_rate,
            enable_speakers,
            offset_seconds=offset_seconds,
            attendee_whitelist=attendee_names if enable_speakers else None,
        )

        # Send transcript back
        await websocket.send_json({"segments": payload_segments})

    except Exception:
        pass
    finally:
        await websocket.close()


def _split_segment_text(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []

    # Primary split on sentence boundaries.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]
    if len(sentences) > 1:
        return sentences

    # Fallback for long, punctuation-free segments.
    if len(cleaned) < 120:
        return [cleaned]

    parts = [p.strip() for p in re.split(r"\s+(?:and then|then|and)\s+", cleaned) if p.strip()]
    if len(parts) > 1:
        return parts

    # Final fallback: chunk by length at word boundaries.
    words = cleaned.split()
    chunks = []
    current = []
    current_len = 0
    for word in words:
        next_len = current_len + len(word) + (1 if current else 0)
        if current and next_len > 120:
            chunks.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len = next_len
    if current:
        chunks.append(" ".join(current))

    return chunks

@app.post("/finalize-meeting")
async def finalize_meeting(
    file: UploadFile = File(...),
    speakers: str = Form("0"),
    attendees: str = Form("[]"),
    current_user=Depends(get_current_user),
):
    print("=== DEBUG finalize_meeting HIT ===", flush=True)
    enable_speakers = speakers == "1"
    owner_user_id = _resolve_owner_user_id(current_user.get("id"))
    attendee_names = _parse_attendees_payload(attendees)

    if enable_speakers:
        profiles = _filter_profiles_for_attendees(
            _load_speaker_profiles_for_owner(owner_user_id),
            attendee_names,
        )
        print(
            f"[finalize-meeting scope] owner={owner_user_id} attendees={attendee_names} profile_count={len(profiles)} profile_names={sorted(list(profiles.keys()))}",
            flush=True,
        )
        logger.info(
            "finalize-meeting speaker scope: owner=%s attendees=%s profile_count=%s profile_names=%s",
            owner_user_id,
            attendee_names,
            len(profiles),
            sorted(list(profiles.keys())),
        )
        speaker_recognizer.set_profiles(profiles)

    os.makedirs("temp", exist_ok=True)
    audio_path = f"temp/{file.filename}"
    with open(audio_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    segments = _transcribe_segments(audio_path)
    audio_samples, sample_rate = sf.read(audio_path, dtype="float32")
    payload_segments = build_payload_segments(
        segments,
        audio_samples,
        sample_rate,
        enable_speakers,
        attendee_whitelist=attendee_names if enable_speakers else None,
    )

    # Split long segments into sentences for better highlighting
    split_segments = []
    for seg in payload_segments:
        text = seg["text"].strip()
        sentences = _split_segment_text(text)
        for sentence in sentences:
            split_segments.append({
                "start": seg["start"],
                "speaker": seg.get("speaker"),
                "text": sentence,
            })

    if enable_speakers:
        transcript_lines = [
            f"[{_format_timestamp(seg['start'] or 0)}] {(seg['speaker'] or 'Unknown')}: {seg['text']}"
            for seg in split_segments
        ]
    else:
        transcript_lines = [
            f"[{_format_timestamp(seg['start'] or 0)}] {seg['text']}" for seg in split_segments
        ]

    
    transcript = "\n".join(transcript_lines)

    if enable_speakers and not attendee_names:
        attendee_names = _extract_attendees_from_segments(split_segments)

    meeting_id = persist_transcript_only(
        transcript,
        source="live",
        owner_user_id=owner_user_id,
        reuse_existing=False,
    )
    if not meeting_id:
        raise HTTPException(status_code=500, detail="Failed to persist live meeting")

    _persist_meeting_attendees(meeting_id, owner_user_id, attendee_names)
    return {"transcript": transcript, "meeting_id": meeting_id}















class TranscriptRequest(BaseModel):
    transcript: str
    meeting_id: str | None = None


class HitlReviseRequest(BaseModel):
    transcript: str
    bullets: list[str]
    bullet_index: int
    user_feedback: str


class ConversationMessage(BaseModel):
    role: str
    content: str


class BulletConversationRequest(BaseModel):
    transcript: str
    original_bullet: str
    conversation_history: list[ConversationMessage]
    user_message: str


class SummaryEditsRequest(BaseModel):
    meeting_id: str
    summary_text: str
    summary_items: list[dict]


def persist_summary_edits(
    meeting_id: str,
    summary_text: str,
    summary_items: list[dict],
    owner_user_id: str | None,
) -> bool:
    resolved_owner_user_id = _resolve_owner_user_id(owner_user_id)
    if not meeting_id or not _can_persist_meetings(resolved_owner_user_id):
        return False

    try:
        with get_db_session() as db:
            if db is None:
                return False

            try:
                summary_row = db.execute(
                    text(
                        """
                        SELECT ms.id
                        FROM meeting_summary ms
                        JOIN meeting m ON m.id = ms.meeting_id
                        WHERE ms.meeting_id = :meeting_id
                          AND m.owner_user_id = :owner_user_id
                        ORDER BY ms.version DESC, ms.created_at DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "meeting_id": meeting_id,
                        "owner_user_id": resolved_owner_user_id,
                    },
                ).fetchone()

                if not summary_row:
                    return False

                summary_id = str(summary_row.id)
                db.execute(
                    text(
                        """
                        UPDATE meeting_summary
                        SET summary_text = :summary_text
                        WHERE id = :summary_id
                        """
                    ),
                    {
                        "summary_text": str(summary_text or "").strip(),
                        "summary_id": summary_id,
                    },
                )

                for ordinal, item in enumerate(summary_items or [], start=1):
                    if not isinstance(item, dict):
                        continue
                    point_text = str(item.get("text", "")).strip()
                    if not point_text:
                        continue

                    db.execute(
                        text(
                            """
                            UPDATE meeting_summary_point
                            SET point_text = :point_text
                            WHERE summary_id = :summary_id
                              AND ordinal = :ordinal
                            """
                        ),
                        {
                            "point_text": point_text,
                            "summary_id": summary_id,
                            "ordinal": ordinal,
                        },
                    )

                db.commit()
                return True
            except Exception:
                db.rollback()
                raise
    except Exception as exc:
        logger.exception("Failed to persist summary edits: %s", exc)
        return False

@app.post("/summarize")
async def summarize(transcript_request: TranscriptRequest, current_user=Depends(get_current_user)):
    transcript = transcript_request.transcript
    try:
        summary_payload = generate_summary_with_sources(str(transcript))
        summary_payload["summary_items"] = _enrich_summary_items_with_point_speakers(
            transcript,
            summary_payload.get("summary_items") or [],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    persisted_meeting_id = persist_summary_bundle(
        transcript=transcript,
        summary_payload=summary_payload,
        source_fallback="import",
        owner_user_id=current_user.get("id"),
        meeting_id=transcript_request.meeting_id,
    )
    if not persisted_meeting_id:
        raise HTTPException(status_code=500, detail="Failed to persist summarized meeting")
    return {
        **summary_payload,
        "meeting_id": persisted_meeting_id,
    }


@app.post("/summarize-hitl")
async def summarize_hitl(transcript_request: TranscriptRequest, current_user=Depends(get_current_user)):
    transcript = transcript_request.transcript
    try:
        summary_payload = generate_summary_hitl(str(transcript))
        summary_payload["summary_items"] = _enrich_summary_items_with_point_speakers(
            transcript,
            summary_payload.get("summary_items") or [],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    persisted_meeting_id = persist_summary_bundle(
        transcript=transcript,
        summary_payload=summary_payload,
        source_fallback="upload",
        owner_user_id=current_user.get("id"),
        meeting_id=transcript_request.meeting_id,
    )
    if not persisted_meeting_id:
        raise HTTPException(status_code=500, detail="Failed to persist summarized meeting")
    return {
        **summary_payload,
        "meeting_id": persisted_meeting_id,
    }


@app.post("/summary/revise-bullet")
async def summary_revise_bullet(payload: HitlReviseRequest):
    try:
        return revise_summary_bullet_with_feedback(
            transcript=payload.transcript,
            bullets=payload.bullets,
            bullet_index=payload.bullet_index,
            user_feedback=payload.user_feedback,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/summary/converse-bullet")
async def summary_converse_bullet(payload: BulletConversationRequest):
    try:
        history = [{"role": msg.role, "content": msg.content} for msg in payload.conversation_history]
        return converse_about_bullet(
            transcript=payload.transcript,
            original_bullet=payload.original_bullet,
            conversation_history=history,
            user_message=payload.user_message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/summary/save-edits")
async def summary_save_edits(payload: SummaryEditsRequest, current_user=Depends(get_current_user)):
    ok = persist_summary_edits(
        meeting_id=str(payload.meeting_id or "").strip(),
        summary_text=str(payload.summary_text or ""),
        summary_items=payload.summary_items or [],
        owner_user_id=current_user.get("id"),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Meeting summary not found or not editable")
    return {"ok": True}


_FRONTEND_DIST_DIR = Path(__file__).resolve().parent / "frontend_dist"
if _FRONTEND_DIST_DIR.exists():
    # Serve bundled SPA assets in single-image deployments.
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST_DIR), html=True), name="frontend")