import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text

from api.deps.auth import get_current_user
from db.session import get_db_session, is_db_enabled
from services.app_knowledge_base import lookup_app_knowledge
from services import chat_agent_service
from services.summary_service import _extract_lines, _find_sources_and_phrases_for_bullet
from schemas.sidebar import ChatCreateRequest, ChatMessageRequest, ChatRenameRequest, ChatTurnRequest, MeetingRenameRequest

router = APIRouter(prefix="/sidebar", tags=["sidebar"])

_CAPABILITY_REPLY_TEXT = (
    "Here are my agentic options in MeetSum:\n"
    "Use the action buttons shown below this message and click Go on the one you want."
)

_MEETING_CHOICE_REPLY_TEXT = (
    "I can open meeting options. Choose one below (Start a live meeting or Upload a meeting recording), or tell me which one to open."
)

_AGENTIC_UNKNOWN_REPLY_TEXT = (
    "I do not have a verified MeetSum answer for that yet. "
    "I can only run supported in-app actions."
)


def _capability_actions_fallback() -> list[dict]:
    return [
        {"type": "start_meeting", "label": "Start a live meeting"},
        {"type": "upload_meeting", "label": "Upload a meeting recording"},
        {"type": "start_speaker_enrollment", "label": "Start speaker enrollment"},
        {"type": "chat_general_mode", "label": "Switch to general chat mode"},
        {"type": "open_settings", "label": "Open user settings"},
        {"type": "set_theme_light", "label": "Set theme to Light"},
        {"type": "set_theme_dark", "label": "Set theme to Dark"},
        {"type": "set_language_en", "label": "Set app language to English"},
        {"type": "set_spoken_language", "label": "Set spoken language to Auto-detect", "payload": {"spoken_language": "auto"}},
        {"type": "set_sidebar_label_auto", "label": "Sidebar label: Auto"},
        {"type": "set_sidebar_label_username", "label": "Sidebar label: Username"},
        {"type": "set_sidebar_label_email", "label": "Sidebar label: Email"},
    ]


def _looks_like_capability_query(user_message: str) -> bool:
    text = (user_message or "").strip().lower()
    if not text:
        return False

    # Extra-tolerant fallback matcher for typos and variants; keeps capability replies deterministic.
    patterns = [
        r"\bagentic\b.{0,20}\b(option|options|capabil[a-z]*|capability|capabilities)\b",
        r"\bwhat\b.{0,20}\bcan\b.{0,20}\byou\b.{0,20}\b(do|help)\b",
        r"\bshow\b.{0,20}\b(option|options|capabil[a-z]*|capability|capabilities)\b",
        r"\bmeet\s*sum\b.{0,40}\b(option|options|capabil[a-z]*|capability|capabilities)\b",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _looks_like_generic_meeting_request(user_message: str) -> bool:
    text = (user_message or "").strip().lower()
    if not text:
        return False
    if "meeting" not in text:
        return False
    if re.search(r"\b(upload|import|file|audio|recording|transcribe)\b", text):
        return False
    if re.search(r"\b(rename|title|name)\b.{0,20}\bmeeting\b", text):
        return False
    return bool(re.search(r"\b(open|start|begin|launch|create|new|help)\b", text))


def _looks_like_speaker_enrollment_request(user_message: str) -> bool:
    text = (user_message or "").strip().lower()
    if not text:
        return False
    if not re.search(r"\b(speaker|voice|employee|attendee|participant)\b", text):
        return False
    return bool(re.search(r"\b(enroll|enrollment|involvement|add|register|new|setup|set up|onboard|open|start)\b", text))


def _looks_like_in_app_request(user_message: str) -> bool:
    text = (user_message or "").strip().lower()
    if not text:
        return False
    app_terms = r"\b(meetsum|meeting|chat|settings|theme|language|speaker|record|upload|sidebar|note|notes|summary|summaries|minutes|action items|workspace|workspaces)\b"
    action_terms = r"\b(open|start|begin|launch|create|new|set|switch|change|update|enable|disable|enroll|add|register|generate|make|get|show)\b"
    return bool(re.search(app_terms, text) and re.search(action_terms, text))


def _looks_like_agentic_request(user_message: str) -> bool:
    text = (user_message or "").strip().lower()
    if not text:
        return False

    if _looks_like_capability_query(text):
        return True

    if _looks_like_in_app_request(text):
        return True

    if _looks_like_generic_meeting_request(text):
        return True

    if _looks_like_speaker_enrollment_request(text):
        return True

    # Broad signal for app-operation phrasing even when strict regex misses specifics.
    return bool(re.search(r"\b(can you|help me|please|in this app|in meetsum)\b", text) and re.search(r"\b(open|start|create|set|switch|change|manage|generate|workspace|meeting|settings|notes|summary|speaker)\b", text))


def _normalize_actions(actions: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    for item in actions:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or "").strip()
        label = str(item.get("label") or "").strip()
        if not action_type or not label:
            continue
        if action_type == "set_sidebar_label_display_name":
            continue
        if action_type in seen:
            continue
        seen.add(action_type)
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else None
        if payload is None:
            normalized.append({"type": action_type, "label": label})
        else:
            normalized.append({"type": action_type, "label": label, "payload": payload})
    return normalized


def _merge_actions(primary: list[dict], secondary: list[dict]) -> list[dict]:
    return _normalize_actions([*primary, *secondary])


def _action_reply(action: dict) -> str:
    action_type = str(action.get("type") or "").strip()
    if action_type == "open_settings":
        return "I can do that. Click Go on Open user settings below."
    if action_type in {"set_theme_light", "set_theme_dark"}:
        return "I can do that. Click Go on the theme action below."
    if action_type in {"set_language_en", "set_spoken_language"}:
        return "I can do that. Click Go on the language action below."
    if action_type.startswith("set_sidebar_label_"):
        return "I can do that. Click Go on the sidebar label action below."
    if action_type == "start_meeting":
        return "Opening meeting options now (live/upload)."
    if action_type == "upload_meeting":
        return "Opening meeting options now (live/upload)."
    if action_type == "start_speaker_enrollment":
        return "I can open speaker enrollment. Click Go on Start speaker enrollment below."
    if action_type == "chat_general_mode":
        return "I can switch this chat back to general mode. Click Go below."
    if action_type in {"new_chat", "rename_meeting"}:
        return "I can do that. Click Go on the action below."
    return "I can do that. Click Go on the action below."


def _detect_action_intent(user_message: str):
    detector = getattr(chat_agent_service, "detect_action_intent", None)
    if callable(detector):
        detected = detector(user_message)
        if detected:
            return detected
    if _looks_like_speaker_enrollment_request(user_message):
        return {"type": "start_speaker_enrollment", "label": "Start speaker enrollment"}
    return None


def _list_capability_actions(user_message: str) -> list[dict]:
    lister = getattr(chat_agent_service, "list_capability_actions", None)
    if callable(lister):
        actions = lister(user_message)
        if isinstance(actions, list):
            return actions
    return []


def _is_capability_query(user_message: str) -> bool:
    checker = getattr(chat_agent_service, "_is_capability_query", None)
    if callable(checker):
        return bool(checker(user_message))
    return False


def _generate_chat_reply(user_message: str, history: list[dict]) -> str:
    generator = getattr(chat_agent_service, "generate_chat_reply", None)
    if not callable(generator):
        raise RuntimeError("Chat agent reply generator is unavailable")
    return generator(user_message=user_message, history=history)


def _generate_chat_title(seed_text: str) -> str:
    title_generator = getattr(chat_agent_service, "generate_chat_title", None)
    if callable(title_generator):
        return title_generator(seed_text)
    return "New chat"


def _coerce_line_number(value) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _parse_source_refs(source_refs) -> tuple[list[int], list[str]]:
    lines: list[int] = []
    phrases: list[str] = []

    if isinstance(source_refs, list):
        for entry in source_refs:
            parsed_line = _coerce_line_number(entry)
            if parsed_line:
                lines.append(parsed_line)
                continue
            if isinstance(entry, dict):
                maybe_line = _coerce_line_number(entry.get("line") or entry.get("source") or entry.get("line_number"))
                if maybe_line:
                    lines.append(maybe_line)
                phrase = entry.get("phrase") or entry.get("matched_phrase")
                if isinstance(phrase, str) and phrase.strip():
                    phrases.append(phrase.strip())
    elif isinstance(source_refs, dict):
        line_values = source_refs.get("lines")
        if isinstance(line_values, list):
            for value in line_values:
                parsed_line = _coerce_line_number(value)
                if parsed_line:
                    lines.append(parsed_line)
        phrase_values = source_refs.get("matched_phrases") or source_refs.get("phrases")
        if isinstance(phrase_values, list):
            phrases.extend([str(value).strip() for value in phrase_values if isinstance(value, str) and value.strip()])

    deduped_lines = list(dict.fromkeys(lines))
    deduped_phrases = list(dict.fromkeys(phrases))
    return deduped_lines, deduped_phrases


def _summarize_provenance_status(stored_count: int, recomputed_count: int) -> str:
    if stored_count and recomputed_count:
        return "mixed"
    if stored_count:
        return "stored"
    if recomputed_count:
        return "recomputed"
    return "none"


def _enrich_summary_items_with_provenance(summary_items: list[dict], transcript_text: str) -> tuple[list[dict], dict[str, int | str]]:
    line_items = _extract_lines(transcript_text or "")
    line_lookup = {lnum: str(item.get("text") or "") for item in line_items for lnum in [item.get("line")] if isinstance(lnum, int)}

    enriched: list[dict] = []
    stored_count = 0
    recomputed_count = 0
    for item in summary_items:
        base_text = str(item.get("text") or "").strip()

        # If matched_phrases were already loaded from DB, skip recomputation entirely
        existing_phrases = item.get("matched_phrases")
        if isinstance(existing_phrases, list) and existing_phrases:
            matched_phrases = [str(v).strip() for v in existing_phrases if isinstance(v, str) and v.strip()]
            source_lines = [line for line in (item.get("sources") or []) if isinstance(line, int)]
            source_texts = [line_lookup.get(line, "") for line in source_lines if line in line_lookup]
            stored_count += 1
            enriched.append({**item, "source_texts": source_texts, "matched_phrases": matched_phrases, "provenance_source": "stored"})
            continue

        source_lines, ref_phrases = _parse_source_refs(item.get("sources"))
        if not source_lines:
            source_lines = [line for line in (item.get("sources") or []) if isinstance(line, int)]

        source_texts = [line_lookup.get(line, "") for line in source_lines if line in line_lookup]

        matched_phrases = [str(v).strip() for v in ref_phrases if isinstance(v, str) and v.strip()]
        provenance_source = "stored" if matched_phrases else "none"
        if matched_phrases:
            stored_count += 1

        if not matched_phrases and base_text:
            recomputed_count += 1
            scoped_line_items = [li for li in line_items for lnum in [li.get("line")] if isinstance(lnum, int) and lnum in source_lines]
            probe_lines = scoped_line_items or line_items
            recomputed_sources, recomputed_phrases = _find_sources_and_phrases_for_bullet(base_text, probe_lines)
            if not source_lines and recomputed_sources:
                source_lines = recomputed_sources
                source_texts = [line_lookup.get(line, "") for line in source_lines if line in line_lookup]
            if recomputed_phrases:
                matched_phrases = recomputed_phrases
            provenance_source = "recomputed"

        enriched.append(
            {
                **item,
                "sources": source_lines,
                "source_texts": source_texts,
                "matched_phrases": matched_phrases,
                "provenance_source": provenance_source,
            }
        )

    return enriched, {
        "status": _summarize_provenance_status(stored_count, recomputed_count),
        "stored_items": stored_count,
        "recomputed_items": recomputed_count,
        "total_items": len(enriched),
    }


def _require_db_enabled():
    if not is_db_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured")


@router.get("/chats")
def list_chats(current_user=Depends(get_current_user)):
    _require_db_enabled()
    with get_db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT id, title, updated_at, created_at
                FROM chat_thread
                WHERE owner_user_id = :owner_user_id
                ORDER BY updated_at DESC
                """
            ),
            {"owner_user_id": current_user["id"]},
        ).fetchall()
    return {"items": [dict(row._mapping) for row in rows]}


@router.post("/chats")
def create_chat(payload: ChatCreateRequest, current_user=Depends(get_current_user)):
    _require_db_enabled()
    title = (payload.title or "New chat").strip() or "New chat"

    with get_db_session() as db:
        row = db.execute(
            text(
                """
                INSERT INTO chat_thread (title, owner_user_id)
                VALUES (:title, :owner_user_id)
                RETURNING id, title, updated_at, created_at
                """
            ),
            {"title": title, "owner_user_id": current_user["id"]},
        ).fetchone()
        db.commit()

    return dict(row._mapping)


@router.patch("/chats/{chat_id}")
def rename_chat(chat_id: str, payload: ChatRenameRequest, current_user=Depends(get_current_user)):
    _require_db_enabled()
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title cannot be empty")

    with get_db_session() as db:
        row = db.execute(
            text(
                """
                UPDATE chat_thread
                SET title = :title
                WHERE id = :chat_id AND owner_user_id = :owner_user_id
                RETURNING id, title, updated_at
                """
            ),
            {"chat_id": chat_id, "owner_user_id": current_user["id"], "title": title},
        ).fetchone()
        if not row:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
        db.commit()

    return dict(row._mapping)


@router.delete("/chats/{chat_id}")
def delete_chat(chat_id: str, current_user=Depends(get_current_user)):
    _require_db_enabled()

    with get_db_session() as db:
        row = db.execute(
            text(
                """
                DELETE FROM chat_thread
                WHERE id = :chat_id AND owner_user_id = :owner_user_id
                RETURNING id
                """
            ),
            {"chat_id": chat_id, "owner_user_id": current_user["id"]},
        ).fetchone()
        if not row:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
        db.commit()

    return {"deleted": True, "id": chat_id}


@router.post("/chats/{chat_id}/messages")
def add_chat_message(chat_id: str, payload: ChatMessageRequest, current_user=Depends(get_current_user)):
    _require_db_enabled()
    role = payload.role if payload.role in {"user", "assistant", "system"} else "user"
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")

    with get_db_session() as db:
        owner_row = db.execute(
            text("SELECT id FROM chat_thread WHERE id = :chat_id AND owner_user_id = :owner_user_id LIMIT 1"),
            {"chat_id": chat_id, "owner_user_id": current_user["id"]},
        ).fetchone()
        if not owner_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

        msg_row = db.execute(
            text(
                """
                INSERT INTO chat_message (chat_id, role, content, created_by)
                VALUES (:chat_id, :role, :content, :created_by)
                RETURNING id, chat_id, role, content, created_at
                """
            ),
            {
                "chat_id": chat_id,
                "role": role,
                "content": content,
                "created_by": current_user["id"],
            },
        ).fetchone()

        db.execute(
            text("UPDATE chat_thread SET updated_at = NOW() WHERE id = :chat_id"),
            {"chat_id": chat_id},
        )

        db.commit()

    return dict(msg_row._mapping)


@router.get("/chats/{chat_id}/messages")
def list_chat_messages(chat_id: str, current_user=Depends(get_current_user)):
    _require_db_enabled()

    with get_db_session() as db:
        owner_row = db.execute(
            text("SELECT id FROM chat_thread WHERE id = :chat_id AND owner_user_id = :owner_user_id LIMIT 1"),
            {"chat_id": chat_id, "owner_user_id": current_user["id"]},
        ).fetchone()
        if not owner_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

        rows = db.execute(
            text(
                """
                SELECT id, chat_id, role, content, created_at
                FROM chat_message
                WHERE chat_id = :chat_id
                ORDER BY created_at ASC
                """
            ),
            {"chat_id": chat_id},
        ).fetchall()

    return {"items": [dict(row._mapping) for row in rows]}


@router.post("/chats/{chat_id}/turn")
def chat_turn(chat_id: str, payload: ChatTurnRequest, current_user=Depends(get_current_user)):
    _require_db_enabled()
    user_message = (payload.message or "").strip()
    if not user_message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")

    with get_db_session() as db:
        chat_row = db.execute(
            text(
                """
                SELECT id, title
                FROM chat_thread
                WHERE id = :chat_id AND owner_user_id = :owner_user_id
                LIMIT 1
                """
            ),
            {"chat_id": chat_id, "owner_user_id": current_user["id"]},
        ).fetchone()
        if not chat_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

        history_rows = db.execute(
            text(
                """
                SELECT role, content
                FROM chat_message
                WHERE chat_id = :chat_id
                ORDER BY created_at ASC
                """
            ),
            {"chat_id": chat_id},
        ).fetchall()
        history = [
            {"role": row.role, "content": row.content}
            for row in history_rows
        ]

        is_capability_query = _is_capability_query(user_message) or _looks_like_capability_query(user_message)
        is_agentic_query = _looks_like_agentic_request(user_message)
        action = _detect_action_intent(user_message)
        actions = _normalize_actions(_list_capability_actions(user_message))
        if action and not any(item.get("type") == action.get("type") for item in actions):
            actions.insert(0, action)

        if is_capability_query:
            assistant_reply = _CAPABILITY_REPLY_TEXT
            actions = _merge_actions(_capability_actions_fallback(), _list_capability_actions(user_message))
            action = None
        elif action:
            assistant_reply = _action_reply(action)
        elif _looks_like_generic_meeting_request(user_message):
            assistant_reply = _MEETING_CHOICE_REPLY_TEXT
            actions = actions or [
                {"type": "start_meeting", "label": "Start a live meeting"},
                {"type": "upload_meeting", "label": "Upload a meeting recording"},
            ]
        else:
            knowledge = lookup_app_knowledge(user_message)
            if knowledge:
                assistant_reply = str(knowledge.get("answer") or "").strip()
                actions = _merge_actions(actions, knowledge.get("actions") or [])
                if is_agentic_query and not actions:
                    actions = _capability_actions_fallback()
            elif is_agentic_query:
                assistant_reply = _AGENTIC_UNKNOWN_REPLY_TEXT
                actions = _capability_actions_fallback()
            else:
                try:
                    assistant_reply = _generate_chat_reply(user_message=user_message, history=history)
                except RuntimeError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=str(exc),
                    ) from exc

        user_row = db.execute(
            text(
                """
                INSERT INTO chat_message (chat_id, role, content, created_by)
                VALUES (:chat_id, 'user', :content, :created_by)
                RETURNING id, chat_id, role, content, created_at
                """
            ),
            {
                "chat_id": chat_id,
                "content": user_message,
                "created_by": current_user["id"],
            },
        ).fetchone()

        assistant_row = db.execute(
            text(
                """
                INSERT INTO chat_message (chat_id, role, content, created_by)
                VALUES (:chat_id, 'assistant', :content, :created_by)
                RETURNING id, chat_id, role, content, created_at
                """
            ),
            {
                "chat_id": chat_id,
                "content": assistant_reply,
                "created_by": current_user["id"],
            },
        ).fetchone()

        updated_title = None
        current_title = (chat_row.title or "").strip().lower()
        # Only generate a title if: (1) chat has no title yet, AND (2) message is NOT a capability query
        # This prevents generic titles like "MeetSum Agentic Options" from capability queries
        if current_title in {"", "new chat"} and not _is_capability_query(user_message):
            generated_title = _generate_chat_title(user_message)
            renamed = db.execute(
                text(
                    """
                    UPDATE chat_thread
                    SET title = :title, updated_at = NOW()
                    WHERE id = :chat_id
                    RETURNING title
                    """
                ),
                {"chat_id": chat_id, "title": generated_title},
            ).fetchone()
            if renamed:
                updated_title = renamed.title
        else:
            db.execute(
                text("UPDATE chat_thread SET updated_at = NOW() WHERE id = :chat_id"),
                {"chat_id": chat_id},
            )

        db.commit()

    return {
        "user_message": dict(user_row._mapping),
        "assistant_message": dict(assistant_row._mapping),
        "title": updated_title,
        "action": action,
        "actions": actions,
    }


@router.get("/meetings")
def list_meetings(current_user=Depends(get_current_user)):
    _require_db_enabled()
    with get_db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT id, title, source, meeting_date, status, updated_at, created_at
                FROM meeting
                WHERE owner_user_id = :owner_user_id
                ORDER BY COALESCE(meeting_date, created_at) DESC
                """
            ),
            {"owner_user_id": current_user["id"]},
        ).fetchall()
    return {"items": [dict(row._mapping) for row in rows]}


@router.patch("/meetings/{meeting_id}")
def rename_meeting(meeting_id: str, payload: MeetingRenameRequest, current_user=Depends(get_current_user)):
    _require_db_enabled()
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title cannot be empty")

    with get_db_session() as db:
        row = db.execute(
            text(
                """
                UPDATE meeting
                SET title = :title
                WHERE id = :meeting_id AND owner_user_id = :owner_user_id
                RETURNING id, title, updated_at
                """
            ),
            {"meeting_id": meeting_id, "owner_user_id": current_user["id"], "title": title},
        ).fetchone()
        if not row:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
        db.commit()

    return dict(row._mapping)


@router.get("/meetings/{meeting_id}")
def get_meeting_detail(meeting_id: str, current_user=Depends(get_current_user)):
    _require_db_enabled()

    with get_db_session() as db:
        meeting_row = db.execute(
            text(
                """
                SELECT id, title, source, meeting_date, status, updated_at, created_at
                FROM meeting
                WHERE id = :meeting_id AND owner_user_id = :owner_user_id
                LIMIT 1
                """
            ),
            {"meeting_id": meeting_id, "owner_user_id": current_user["id"]},
        ).fetchone()
        if not meeting_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

        transcript_row = db.execute(
            text(
                """
                SELECT transcript_text
                FROM meeting_transcript
                WHERE meeting_id = :meeting_id
                ORDER BY version DESC, created_at DESC
                LIMIT 1
                """
            ),
            {"meeting_id": meeting_id},
        ).fetchone()

        summary_row = db.execute(
            text(
                """
                SELECT id, summary_text, model_runtime_name, hitl_model_runtime_name
                FROM meeting_summary
                WHERE meeting_id = :meeting_id
                ORDER BY version DESC, created_at DESC
                LIMIT 1
                """
            ),
            {"meeting_id": meeting_id},
        ).fetchone()

        summary_items = []
        provenance = {"status": "none", "stored_items": 0, "recomputed_items": 0, "total_items": 0}
        meeting_attendees: list[str] = []
        transcript_text = transcript_row.transcript_text if transcript_row else ""
        if summary_row:
            point_rows = db.execute(
                text(
                    """
                    SELECT ordinal, point_text, source_refs, matched_phrases, point_speakers
                    FROM meeting_summary_point
                    WHERE summary_id = :summary_id
                    ORDER BY ordinal ASC
                    """
                ),
                {"summary_id": summary_row.id},
            ).fetchall()
            summary_items = [
                {
                    "text": row.point_text,
                    "sources": row.source_refs or [],
                    "matched_phrases": row.matched_phrases or [],
                    "point_speakers": row.point_speakers or [],
                }
                for row in point_rows
            ]
            summary_items, provenance = _enrich_summary_items_with_provenance(summary_items, transcript_text)

        attendee_rows = db.execute(
            text(
                """
                SELECT display_name
                FROM public.meeting_attendee
                WHERE meeting_id = :meeting_id
                ORDER BY created_at ASC
                """
            ),
            {"meeting_id": meeting_id},
        ).fetchall()
        meeting_attendees = [str(row.display_name) for row in attendee_rows if getattr(row, "display_name", None)]

    return {
        "meeting": dict(meeting_row._mapping),
        "transcript": transcript_text,
        "summary": summary_row.summary_text if summary_row else "",
        "model_label": summary_row.model_runtime_name if summary_row else "",
        "hitl_model_label": summary_row.hitl_model_runtime_name if summary_row else "",
        "provenance": provenance,
        "meeting_attendees": meeting_attendees,
        "summary_items": summary_items,
    }


@router.delete("/meetings/{meeting_id}")
def delete_meeting(meeting_id: str, current_user=Depends(get_current_user)):
    _require_db_enabled()

    with get_db_session() as db:
        row = db.execute(
            text(
                """
                DELETE FROM meeting
                WHERE id = :meeting_id AND owner_user_id = :owner_user_id
                RETURNING id
                """
            ),
            {"meeting_id": meeting_id, "owner_user_id": current_user["id"]},
        ).fetchone()
        if not row:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
        db.commit()

    return {"deleted": True, "id": meeting_id}
