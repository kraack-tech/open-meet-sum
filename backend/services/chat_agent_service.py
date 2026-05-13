import re
from typing import Dict, List

from services.provider_router import generate_with_active_provider


def generate_chat_title(seed_text: str) -> str:
	seed = (seed_text or "").strip()
	if not seed:
		return "New chat"

	prompt = (
		"Generate a concise chat title from the user's first message.\n"
		"Rules:\n"
		"- 3 to 7 words\n"
		"- no quotes, no trailing punctuation\n"
		"- plain text only\n\n"
		f"Message:\n{seed[:1000]}\n\n"
		"Title:"
	)

	raw = generate_with_active_provider(prompt, task="chat")
	candidate = _extract_title_candidate(raw or "")
	if candidate:
		return candidate

	cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", seed)
	cleaned = re.sub(r"\s+", " ", cleaned).strip()
	words = [w for w in cleaned.split(" ") if w]
	if not words:
		return "New chat"
	return " ".join(words[:6])


def generate_chat_reply(user_message: str, history: List[Dict[str, str]] | None = None) -> str:
	message = (user_message or "").strip()
	if not message:
		return "Could you share a bit more detail?"

	history = history or []
	history_snippet = []
	for item in history[-12:]:
		role = str(item.get("role", "user")).strip().lower()
		if role not in {"user", "assistant", "system"}:
			continue
		content = str(item.get("content", "")).strip()
		if not content:
			continue
		history_snippet.append(f"{role}: {content}")

	history_text = "\n".join(history_snippet) if history_snippet else "(no prior conversation)"

	prompt = (
		"You are Open MeetSum assistant.\n"
		"Respond helpfully and concisely to the user.\n"
		"If details are missing, ask one short follow-up question.\n"
		"Return plain text only.\n\n"
		f"Conversation so far:\n{history_text}\n\n"
		f"User: {message}\n"
		"Assistant:"
	)

	raw = generate_with_active_provider(prompt, task="chat")
	if raw and raw.strip():
		return raw.strip()
	raise RuntimeError("Active chat model provider is unavailable or misconfigured")


def _extract_title_candidate(text: str) -> str:
	candidate = (text or "").strip()
	if not candidate:
		return ""

	candidate = re.sub(r"^```(?:json)?", "", candidate, flags=re.IGNORECASE).strip()
	candidate = re.sub(r"```$", "", candidate).strip()
	candidate = candidate.splitlines()[0].strip()
	candidate = re.sub(r"^[\-\*\d\.\)\s]+", "", candidate).strip()
	candidate = candidate.strip('"\'` ')
	candidate = re.sub(r"\s+", " ", candidate)
	candidate = re.sub(r"[\.!?;,]+$", "", candidate).strip()

	words = [w for w in candidate.split(" ") if w]
	if len(words) < 2:
		return ""
	if len(words) > 8:
		candidate = " ".join(words[:8])

	if len(candidate) < 8:
		return ""

	return candidate
