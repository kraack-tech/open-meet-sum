import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, cast

from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from services.provider_router import generate_with_active_provider, get_model_info_for_task, get_summary_strategy

MODEL_PATH = "google/flan-t5-large"

logger = logging.getLogger("meetsum.summary")

STOPWORDS = {
	"a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "how", "i", "in", "is", "it",
	"of", "on", "or", "our", "so", "that", "the", "their", "there", "these", "this", "to", "we", "with",
	"will", "would", "can", "could", "should", "do", "does", "did", "have", "has", "had", "about", "into",
	"after", "before", "also", "than", "then", "them", "they", "those", "you", "your", "us", "best", "discussion",
	"meeting", "goal", "goals", "topic", "topics", "point", "points", "importance", "methods", "strategy",
	"strategies", "tracking", "measuring", "performance", "practices", "effective",
}

_tokenizer = None
_model = None
_flan_lock = threading.Lock()


def _ensure_flan_loaded() -> None:
	global _tokenizer, _model
	if _tokenizer is not None and _model is not None:
		return

	with _flan_lock:
		if _tokenizer is not None and _model is not None:
			return

		start = time.time()
		done = threading.Event()
		error_holder: Dict[str, Exception] = {}

		def _load() -> None:
			global _tokenizer, _model
			try:
				_tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
				_model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH)
			except Exception as exc:
				error_holder["error"] = exc
			finally:
				done.set()

		print(f"[startup] Loading summary model: {MODEL_PATH}", flush=True)
		logger.info("Loading summary model: %s", MODEL_PATH)
		threading.Thread(target=_load, daemon=True).start()

		while not done.wait(10):
			elapsed = int(time.time() - start)
			print(
				f"[startup] Summary model '{MODEL_PATH}' still loading/download in progress... elapsed={elapsed}s",
				flush=True,
			)
			logger.info("Summary model still loading... elapsed=%ss", elapsed)

		if "error" in error_holder:
			raise error_holder["error"]

		elapsed = int(time.time() - start)
		print(f"[startup] Summary model ready: {MODEL_PATH} elapsed={elapsed}s", flush=True)
		logger.info("Summary model ready: %s elapsed=%ss", MODEL_PATH, elapsed)


def format_bullets(text: str) -> str:
	cleaned = (text or "").strip()
	cleaned = re.sub(r"^\s*bullet\s*points?\s*:\s*", "", cleaned, flags=re.IGNORECASE)

	if "-" in cleaned:
		lines = [line.strip() for line in re.split(r"-\s*", cleaned) if line.strip()]
	else:
		lines = [line.strip() for line in re.split(r"[.!?]\s+", cleaned) if line.strip()]

	# Remove model-added labels like "Bullet Point 1:" or "2)".
	lines = [
		re.sub(r"^\s*bullet\s*points?\s*\d*\s*[:\-]\s*", "", line, flags=re.IGNORECASE)
		for line in lines
	]
	lines = [re.sub(r"^\s*\d+[\.)\-:]\s*", "", line).strip() for line in lines]
	lines = [line for line in lines if line]
	return "\n".join(f"- {line}" for line in lines)


def _is_refusal_like(text: str | None) -> bool:
	clean = str(text or "").strip().lower()
	if not clean:
		return False
	patterns = [
		r"didn'?t\s+provide.{0,30}transcript",
		r"no\s+transcript\s+provided",
		r"please\s+(?:share|provide|paste).{0,30}transcript",
		r"i'?m\s+happy\s+to\s+help",
	]
	return any(re.search(pattern, clean) for pattern in patterns)


def _flan_generate(prompt: str) -> str:
	_ensure_flan_loaded()
	inputs = _tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
	outputs = _model.generate(
		**inputs,
		max_new_tokens=180,
		num_beams=4,
		early_stopping=True,
		no_repeat_ngram_size=3,
	)
	return _tokenizer.decode(outputs[0], skip_special_tokens=True).strip()


def _build_flan_summary_prompt(transcript_no_speakers: str) -> str:
	return (
		"System instructions:\n"
		"You are a meeting summarization model.\n"
		"Generate only concise bullet points grounded in the transcript.\n"
		"Do not add headings, numbering, commentary, or extra prose.\n"
		"Each distinct topic must be its own bullet.\n"
		"Do not merge separate topics into one bullet.\n"
		"Each bullet should be 8-15 words and start with '-'.\n\n"
		f"Transcript:\n{transcript_no_speakers}\n\n"
		"Bullet Points (one topic per bullet):\n"
	)


def _build_provider_summary_prompt(transcript_units: List[Dict[str, object]]) -> str:
	units_json = json.dumps(transcript_units, ensure_ascii=False)
	return (
		"System instructions:\n"
		"Choose the transcript units that best represent the meeting topics.\n"
		"Return JSON only in this form: {\"items\":[{\"id\":1,\"quote\":\"exact transcript words\"}]}.\n"
		"Rules:\n"
		"- Each item must reference a valid unit id from the provided list.\n"
		"- The quote is optional, but if provided it must be copied exactly from that unit.\n"
		"- Each quote should be 3 to 12 words.\n"
		"- Prefer units that state agenda items, goals, decisions, actions, or concrete topics.\n"
		"- Do not invent ids, facts, or paraphrases.\n"
		"- If the transcript contains only two concrete topics, return only two items.\n"
		"- Do not include headings, explanations, or markdown.\n\n"
		f"Transcript units:\n{units_json}\n\n"
		"JSON:\n"
	)


def _generate_provider_summary_text(transcript_no_speakers: str, transcript: str) -> str:
	transcript_units = _build_transcript_units(transcript)
	if not transcript_units:
		return ""
	raw = generate_with_active_provider(_build_provider_summary_prompt(transcript_units), task="summary")
	if _is_refusal_like(raw):
		return ""
	resolved_items = _extract_provider_summary_items(raw or "", transcript_units)
	if resolved_items:
		return "\n".join(f"- {item}" for item in resolved_items)

	fallback_raw = generate_with_active_provider(
		"Return only bullet points copied as closely as possible from the transcript.\n"
		"No headings. No numbering. No explanation.\n"
		"Each bullet must stay close to the transcript wording.\n\n"
		f"Transcript:\n{transcript_no_speakers}\n\n"
		"Bullets:\n",
		task="summary",
	)
	if _is_refusal_like(fallback_raw):
		return ""
	fallback_summary = format_bullets(fallback_raw or "")
	return _ground_provider_summary(fallback_summary, transcript)


def _generate_summary_result(transcript: Any) -> Dict[str, object]:
	cleaned = _preprocess_transcript(transcript)
	transcript_no_speakers = re.sub(r"^([^:]{1,40}):\s*", "", cleaned, flags=re.MULTILINE)
	flan_prompt = _build_flan_summary_prompt(transcript_no_speakers)

	summary_text = ""
	model_used = {"kind": "", "label": "", "provider": "", "runtime": "", "model_id": "", "model_name": ""}
	strategy = get_summary_strategy()
	prefer_provider = strategy in {"provider_primary", "provider_only"}

	if prefer_provider:
		summary_text = _generate_provider_summary_text(transcript_no_speakers, str(transcript))
		if summary_text:
			info = get_model_info_for_task("summary")
			model_used = {
				"kind": "provider",
				"label": info.get("runtime") or info.get("model_name") or info.get("provider") or "provider",
				"provider": info.get("provider") or "",
				"runtime": info.get("runtime") or "",
				"model_id": info.get("model_id") or "",
				"model_name": info.get("model_name") or "",
			}

	if not summary_text and strategy != "provider_only" and transcript_no_speakers.strip():
		try:
			raw = _flan_generate(flan_prompt)
		except Exception:
			raw = ""
		if raw and raw.strip():
			summary_text = format_bullets(raw)
			model_used = {
				"kind": "flan",
				"label": MODEL_PATH,
				"provider": "local",
				"runtime": MODEL_PATH,
				"model_id": "flan-t5-large",
				"model_name": "FLAN-T5 Large",
			}

	if not summary_text:
		summary_text = _generate_provider_summary_text(transcript_no_speakers, str(transcript))
		if summary_text:
			info = get_model_info_for_task("summary")
			model_used = {
				"kind": "provider",
				"label": info.get("runtime") or info.get("model_name") or info.get("provider") or "provider",
				"provider": info.get("provider") or "",
				"runtime": info.get("runtime") or "",
				"model_id": info.get("model_id") or "",
				"model_name": info.get("model_name") or "",
			}

	if not summary_text:
		raise RuntimeError("Active model provider is unavailable or misconfigured")

	return {
		"summary": summary_text,
		"model_used": model_used,
	}


def generate_summary(transcript: Any) -> str:
	return str(_generate_summary_result(transcript).get("summary") or "")


def generate_summary_with_sources(transcript: Any) -> Dict[str, object]:
	summary_result = _generate_summary_result(transcript)
	summary_text = str(summary_result.get("summary") or "")
	items = _attach_sources(summary_text, transcript)
	return {
		"summary": summary_text,
		"summary_items": items,
		"model_used": summary_result.get("model_used") or {},
	}


def generate_summary_hitl(transcript: Any) -> Dict[str, object]:
	base_payload = generate_summary_with_sources(transcript)
	summary_items = cast(List[Dict[str, object]], base_payload.get("summary_items") or [])
	hitl_items = _build_hitl_items(str(transcript), summary_items)
	hitl_model_info = get_model_info_for_task("hitl")
	return {
		"summary": base_payload["summary"],
		"summary_items": summary_items,
		"model_used": base_payload.get("model_used") or {},
		"hitl_model_used": {
			"kind": "provider",
			"label": hitl_model_info.get("runtime") or hitl_model_info.get("model_name") or hitl_model_info.get("provider") or "provider",
			"provider": hitl_model_info.get("provider") or "",
			"runtime": hitl_model_info.get("runtime") or "",
			"model_id": hitl_model_info.get("model_id") or "",
			"model_name": hitl_model_info.get("model_name") or "",
		},
		"hitl_items": hitl_items,
	}


def generate_meeting_title(transcript: Any, source: str = "meeting") -> str:
	cleaned = _preprocess_transcript(transcript or "")
	if not cleaned:
		return "Untitled meeting"

	snippet = cleaned[:1800]
	prompt = (
		"Generate a short meeting title from this transcript.\n"
		"Rules:\n"
		"- 3 to 8 words\n"
		"- concise and specific\n"
		"- no quotes, no emojis, no trailing punctuation\n"
		"- return title text only\n\n"
		f"Source: {source}\n"
		f"Transcript:\n{snippet}\n\n"
		"Title:"
	)

	raw = generate_with_active_provider(prompt, task="summary")
	candidate = _extract_title_candidate(raw or "")
	if candidate:
		return candidate

	return _fallback_title_from_transcript(cleaned)


def revise_summary_bullet_with_feedback(
	transcript: Any,
	bullets: List[str],
	bullet_index: int,
	user_feedback: str,
) -> Dict[str, object]:
	if bullet_index < 0 or bullet_index >= len(bullets):
		raise ValueError("bullet_index out of range")

	current_bullets = [b.strip() for b in bullets if b and b.strip()]
	if bullet_index >= len(current_bullets):
		raise ValueError("bullet_index out of range")

	revised_bullet = _rewrite_bullet_from_feedback(
		transcript=transcript,
		original_bullet=current_bullets[bullet_index],
		user_feedback=user_feedback,
	)

	if revised_bullet == _REMOVE_SENTINEL:
		current_bullets.pop(bullet_index)
	else:
		current_bullets[bullet_index] = revised_bullet
	summary_text = "\n".join(f"- {bullet}" for bullet in current_bullets)
	summary_items = _attach_sources(summary_text, transcript)
	hitl_items = _build_hitl_items(transcript, summary_items)

	return {
		"summary": summary_text,
		"summary_items": summary_items,
		"hitl_items": hitl_items,
		"revised_index": bullet_index,
		"revised_bullet": revised_bullet,
	}


def converse_about_bullet(
	transcript: Any,
	original_bullet: str,
	conversation_history: List[Dict[str, str]],
	user_message: str,
) -> Dict[str, object]:
	if not user_message.strip():
		raise ValueError("user_message cannot be empty")

	user_feedback_parts = []
	for msg in conversation_history:
		if msg.get("role") == "user":
			content = str(msg.get("content", "")).strip()
			if content:
				user_feedback_parts.append(content)

	user_feedback_parts.append(user_message.strip())
	combined_feedback = "\n".join(user_feedback_parts)

	revised_bullet = _rewrite_bullet_from_feedback(
		transcript=transcript,
		original_bullet=original_bullet,
		user_feedback=combined_feedback,
	)

	if revised_bullet == _REMOVE_SENTINEL:
		assistant_response = "Got it — this point will be removed. Click 'Confirm Remove' to confirm."
	elif revised_bullet != original_bullet:
		assistant_response = "Updated summary point based on your correction."
	else:
		assistant_response = "Kept the original summary point because the correction was not specific enough to revise safely."

	return {
		"assistant_response": assistant_response,
		"revised_bullet": revised_bullet,
		"follow_up_question": "",
	}


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


def _fallback_title_from_transcript(cleaned_transcript: str) -> str:
	lines = [line.strip() for line in cleaned_transcript.splitlines() if line.strip()]
	if not lines:
		return "Untitled meeting"
	first = re.sub(r"[^a-zA-Z0-9\s]", " ", lines[0])
	first = re.sub(r"\s+", " ", first).strip()
	words = first.split(" ")
	if not words:
		return "Untitled meeting"
	return " ".join(words[:6])


def _preprocess_transcript(transcript: Any) -> str:
	text = re.sub(r"^\[\d{2}:\d{2}(?::\d{2})?\]\s*", "", str(transcript), flags=re.MULTILINE)
	lines = [line.strip() for line in text.splitlines() if line.strip()]
	unique_lines = []
	for line in lines:
		normalized = re.sub(r"\s+", " ", line.lower())
		if any(normalized == re.sub(r"\s+", " ", u.lower()) for u in unique_lines):
			continue
		if any(normalized in re.sub(r"\s+", " ", u.lower()) for u in unique_lines):
			continue
		unique_lines.append(line)
	return "\n".join(unique_lines)


def _attach_sources(summary_text: str, transcript: str) -> List[Dict[str, object]]:
	bullets = _split_bullets(summary_text)
	line_items = _extract_lines(transcript)
	items = []
	line_lookup = {item["line"]: item["text"] for item in line_items}
	for bullet in bullets:
		sources, matched_phrases = _find_sources_and_phrases_for_bullet(bullet, line_items)
		source_texts = [line_lookup.get(line, "") for line in sources]
		items.append({
			"text": bullet,
			"sources": sources,
			"source_texts": source_texts,
			"matched_phrases": matched_phrases,
		})
	return items


def _best_grounding_for_bullet(bullet: str, line_items: List[Dict[str, object]]) -> Dict[str, object]:
	bullet_clean = _normalize_text(bullet)
	if not bullet_clean:
		return {"score": 0.0, "line": 0, "text": "", "phrase": ""}
	bullet_tokens = _content_tokens_from_text(bullet_clean)
	if not bullet_tokens:
		bullet_tokens = set(bullet_clean.split())
	best_score = 0.0
	best_line = 0
	best_text = ""
	best_phrase = ""
	for item in line_items:
		line_clean = str(item.get("clean") or "")
		line_tokens = _content_tokens_from_text(line_clean)
		if not line_tokens:
			line_tokens = set(line_clean.split())
		if not line_tokens:
			continue
		overlap = bullet_tokens.intersection(line_tokens)
		score = len(overlap) / max(len(bullet_tokens), 1)
		if score > best_score:
			best_score = score
			best_line_value = item.get("line")
			best_line = int(best_line_value) if isinstance(best_line_value, (int, float, str)) else 0
			best_text = str(item.get("text") or "")
			best_phrase = _find_best_phrase(best_text, bullet_tokens)
	return {
		"score": best_score,
		"line": best_line,
		"text": best_text,
		"phrase": best_phrase,
	}


def _clean_grounded_phrase(text: str) -> str:
	phrase = _strip_prefix(text)
	phrase = re.sub(r"\s+", " ", phrase).strip(" -:;,.\t")
	return phrase


def _extract_provider_summary_items(raw: str, transcript_units: List[Dict[str, object]]) -> List[str]:
	if not raw or not transcript_units:
		return []

	parsed = _parse_json_payload(raw)
	candidates: List[str] = []
	unit_lookup: Dict[int, str] = {}
	for unit in transcript_units:
		unit_id = unit.get("id")
		if isinstance(unit_id, int):
			unit_lookup[unit_id] = str(unit.get("text") or "")
	if isinstance(parsed, dict):
		items = parsed.get("items")
		if isinstance(items, list):
			for item in items:
				if isinstance(item, dict):
					unit_id = item.get("id")
					quote = str(item.get("quote") or item.get("text") or item.get("span") or "").strip()
					candidate = _resolve_provider_unit_selection(unit_id, quote, unit_lookup)
				elif isinstance(item, str):
					candidate = item.strip()
				else:
					candidate = ""
				if candidate:
					candidates.append(candidate)
	if not candidates:
		candidates = _split_bullets(raw)

	resolved: List[str] = []
	seen = set()
	for candidate in candidates:
		resolved_text = _clean_grounded_phrase(candidate)
		resolved_clean = _normalize_text(resolved_text)
		if not resolved_clean or resolved_clean in seen:
			continue
		if len(resolved_clean.split()) < 3:
			continue
		if len(_content_tokens_from_text(resolved_clean)) < 2:
			continue
		seen.add(resolved_clean)
		resolved.append(resolved_text)
	return resolved


def _resolve_provider_unit_selection(unit_id: object, quote: str, unit_lookup: Dict[int, str]) -> str:
	resolved_id = int(unit_id) if isinstance(unit_id, (int, float, str)) and str(unit_id).strip().isdigit() else None
	unit_text = unit_lookup.get(resolved_id or -1, "")
	clean_quote = _clean_grounded_phrase(quote)
	if clean_quote and unit_text and clean_quote.lower() in unit_text.lower():
		return clean_quote
	if unit_text:
		return _compress_transcript_unit(unit_text)
	return clean_quote


def _build_transcript_units(transcript: str) -> List[Dict[str, object]]:
	units: List[Dict[str, object]] = []
	for index, item in enumerate(_extract_lines(transcript), start=1):
		text = _clean_grounded_phrase(str(item.get("text") or ""))
		if not text:
			continue
		units.append({"id": index, "text": text})
	return units


def _compress_transcript_unit(text: str) -> str:
	cleaned = _clean_grounded_phrase(text)
	patterns = [
		r"^(?:in\s+this\s+meeting,?\s*)",
		r"^(?:today,?\s*)",
		r"^(?:we\s+will\s+(?:talk\s+about|discuss|cover)\s+)",
		r"^(?:we\s+will\s+also\s+(?:discuss|cover)\s+)",
		r"^(?:the\s+goal\s+of\s+the\s+meeting\s+is\s+to\s+)",
		r"^(?:something\s+really\s+important\s+and\s+that\s+is\s+)",
	]
	for pattern in patterns:
		cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip(" ,;:-")
	return cleaned or text.strip()


def _resolve_provider_candidate(candidate: str, line_items: List[Dict[str, object]]) -> str:
	clean_candidate = _clean_grounded_phrase(candidate)
	if not clean_candidate:
		return ""
	for item in line_items:
		line_text = _clean_grounded_phrase(str(item.get("text") or ""))
		if not line_text:
			continue
		if clean_candidate.lower() in line_text.lower():
			return clean_candidate

	grounding = _best_grounding_for_bullet(clean_candidate, line_items)
	score_value = grounding.get("score")
	score = float(score_value) if isinstance(score_value, (int, float, str)) else 0.0
	best_text = _clean_grounded_phrase(str(grounding.get("text") or ""))
	if score < 0.35 or not best_text:
		return ""
	phrase = _expand_phrase_from_line(best_text, clean_candidate)
	return phrase or best_text


def _expand_phrase_from_line(line_text: str, candidate: str) -> str:
	words = line_text.split()
	if not words:
		return ""
	normalized_words = [re.sub(r"[^a-z0-9]", "", word.lower()) for word in words]
	target_tokens = _content_tokens_from_text(_normalize_text(candidate))
	if not target_tokens:
		target_tokens = set(_normalize_text(candidate).split())
	indices = [idx for idx, token in enumerate(normalized_words) if token in target_tokens]
	if not indices:
		return ""
	start = indices[0]
	end = indices[-1]
	while start > 0 and end - start + 1 < 8:
		prev_token = normalized_words[start - 1]
		if not prev_token:
			break
		start -= 1
		if prev_token not in STOPWORDS and end - start + 1 >= 5:
			break
	while end + 1 < len(words) and end - start + 1 < 8:
		next_token = normalized_words[end + 1]
		if not next_token:
			break
		end += 1
		if next_token not in STOPWORDS and end - start + 1 >= 6:
			break
	phrase = " ".join(words[start:end + 1]).strip(" -:;,.\t")
	return phrase


def _ground_provider_summary(summary_text: str, transcript: str) -> str:
	bullets = _split_bullets(summary_text)
	line_items = _extract_lines(transcript)
	if not bullets or not line_items:
		return summary_text

	grounded_bullets: List[str] = []
	seen = set()
	for bullet in bullets:
		grounding = _best_grounding_for_bullet(bullet, line_items)
		score_value = grounding.get("score")
		score = float(score_value) if isinstance(score_value, (int, float, str)) else 0.0
		phrase = _clean_grounded_phrase(str(grounding.get("phrase") or ""))
		best_text = _clean_grounded_phrase(str(grounding.get("text") or ""))
		candidate = bullet.strip()

		# Replace provider paraphrases with transcript-near wording aggressively.
		if phrase:
			candidate = phrase
		elif score >= 0.6 and best_text:
			candidate = best_text

		candidate_clean = _normalize_text(candidate)
		phrase_clean = _normalize_text(phrase)
		candidate_tokens = _content_tokens_from_text(candidate_clean)
		if score < 0.35 and len(phrase_clean.split()) < 3:
			continue
		if len(candidate_clean.split()) < 3:
			continue
		if len(candidate_tokens) < 2:
			continue
		if candidate_clean in seen:
			continue
		seen.add(candidate_clean)
		grounded_bullets.append(candidate)

	if grounded_bullets:
		return "\n".join(f"- {bullet}" for bullet in grounded_bullets)
	return summary_text


def _split_bullets(summary_text: str) -> List[str]:
	lines = [line.strip() for line in summary_text.splitlines() if line.strip()]
	bullets = []
	for line in lines:
		if line.startswith("-"):
			text = line.lstrip("- ").strip()
			if text:
				bullets.append(text)
		else:
			bullets.append(line)
	return bullets


def _build_hitl_items(transcript: str, summary_items: List[Dict[str, object]]) -> List[Dict[str, object]]:
	if not summary_items:
		return []
	fallback = [_default_hitl_item(str(item.get("text") or "")) for item in summary_items]
	prompt_items = []
	for item in summary_items:
		prompt_items.append({
			"bullet": item.get("text", ""),
			"source_texts": item.get("source_texts", []),
			"matched_phrases": item.get("matched_phrases", []),
		})
	prompt = (
		"You are assisting a human-in-the-loop meeting summarizer. "
		"For each bullet, decide whether it needs confirmation from a user.\n"
		"Return JSON ONLY with this exact schema:\n"
		"{\"items\": ["
		"{\"confidence\":\"high|medium|low\","
		"\"needs_confirmation\":true|false,"
		"\"assumption\":\"short text\","
		"\"clarification_question\":\"question for user\"}"
		"]}\n"
		"Rules:\n"
		"- confidence is low when the claim appears inferred, ambiguous, or weakly grounded in source_texts.\n"
		"- clarification_question must be specific and answerable in one sentence.\n"
		"- if confidence is high, clarification_question can be empty.\n"
		"- Never add new facts not in transcript or source_texts.\n\n"
		f"Transcript:\n{transcript}\n\n"
		f"Bullets with evidence:\n{json.dumps(prompt_items, ensure_ascii=False)}"
	)
	raw = generate_with_active_provider(prompt, task="hitl")
	parsed = _parse_json_payload(raw) if raw else None
	if not isinstance(parsed, dict):
		return fallback
	items = parsed.get("items")
	if not isinstance(items, list):
		return fallback
	normalized: List[Dict[str, object]] = []
	for idx, base_item in enumerate(summary_items):
		generated = items[idx] if idx < len(items) and isinstance(items[idx], dict) else {}
		base_bullet = str(base_item.get("text") or "")
		normalized_item = _normalize_hitl_item(generated, base_bullet)
		normalized.append(_apply_hitl_guardrails(base_bullet, normalized_item))
	return normalized


def _extract_lines(transcript: str) -> List[Dict[str, object]]:
	lines = []
	for index, line in enumerate(transcript.splitlines(), start=1):
		text = line.strip()
		if not text:
			continue
		clean = _normalize_text(text)
		if clean:
			lines.append({"line": index, "text": text, "clean": clean})
	return lines


def _normalize_text(text: str) -> str:
	text = re.sub(r"^\[\d{2}:\d{2}(?::\d{2})?\]\s*", "", text)
	text = re.sub(r"^([^:]{1,40}):\s*", "", text)
	text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
	text = re.sub(r"\s+", " ", text).strip()
	return text


def _strip_prefix(text: str) -> str:
	text = re.sub(r"^\[\d{2}:\d{2}(?::\d{2})?\]\s*", "", text)
	text = re.sub(r"^([^:]{1,40}):\s*", "", text)
	return text.strip()


def _find_best_phrase(text: str, bullet_tokens: set[str]) -> str:
	cleaned = _strip_prefix(text)
	if not cleaned:
		return ""
	original_words = cleaned.split()
	normalized_words = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in original_words]
	target_tokens = {token for token in bullet_tokens if token and token not in STOPWORDS}
	if not target_tokens:
		target_tokens = {token for token in bullet_tokens if token}
	best_start = 0
	best_end = 0
	best_overlap = 0
	best_score = 0.0
	for start in range(len(normalized_words)):
		overlap = 0
		for end in range(start, len(normalized_words)):
			token = normalized_words[end]
			if token and token in target_tokens:
				overlap += 1
			window_len = end - start + 1
			if window_len < 2:
				continue
			score = overlap / window_len
			if overlap > best_overlap or (overlap == best_overlap and score > best_score):
				best_score = score
				best_overlap = overlap
				best_start = start
				best_end = end + 1
	if best_overlap < 2:
		return ""
	return " ".join(original_words[best_start:best_end])


def _find_sources_and_phrases_for_bullet(bullet: str, line_items: List[Dict[str, object]]) -> tuple[List[int], List[str]]:
	bullet_clean = _normalize_text(bullet)
	if not bullet_clean:
		return [], []
	bullet_tokens = _content_tokens_from_text(bullet_clean)
	if not bullet_tokens:
		bullet_tokens = set(bullet_clean.split())
	scored = []
	for item in line_items:
		line_tokens = _content_tokens_from_text(str(item.get("clean") or ""))
		if not line_tokens:
			line_tokens = set(str(item.get("clean") or "").split())
		if not line_tokens:
			continue
		overlap = bullet_tokens.intersection(line_tokens)
		score = len(overlap) / max(len(bullet_tokens), 1)
		if score > 0:
			line_number = item.get("line") if isinstance(item.get("line"), int) else 0
			text_value = str(item.get("text") or "")
			clean_value = str(item.get("clean") or "")
			scored.append((score, line_number, text_value, clean_value))
	scored.sort(reverse=True)
	top_items = [(line, text) for score, line, text, clean in scored[:1] if score >= 0.05]
	if not top_items and scored:
		top_items = [(scored[0][1], scored[0][2])]
	top_lines = [line for line, _ in top_items]
	matched_phrases = []
	for _, text in top_items:
		phrase = _find_best_phrase(text, bullet_tokens)
		if phrase:
			matched_phrases.append(phrase)
	return top_lines, matched_phrases


def _content_tokens_from_text(text: str) -> set[str]:
	return {token for token in text.split() if token and token not in STOPWORDS and len(token) > 2}


def _default_hitl_item(bullet_text: str) -> Dict[str, object]:
	return {
		"confidence": "medium",
		"needs_confirmation": True,
		"assumption": "This may rely on interpretation of discussion context.",
		"clarification_question": f"Can you confirm this point is accurate: {bullet_text}?",
	}


def _normalize_hitl_item(data: Dict[str, object], bullet_text: str) -> Dict[str, object]:
	confidence = str(data.get("confidence", "medium")).strip().lower()
	if confidence not in {"high", "medium", "low"}:
		confidence = "medium"
	assumption = str(data.get("assumption", "")).strip()
	question = str(data.get("clarification_question", "")).strip()
	needs_confirmation = bool(data.get("needs_confirmation", confidence != "high"))
	if not assumption and confidence != "high":
		assumption = "This point may depend on implied context from the discussion."
	if needs_confirmation and not question:
		question = f"Can you confirm or correct this point: {bullet_text}?"
	if confidence == "high" and not needs_confirmation and not question:
		question = ""
	return {
		"confidence": confidence,
		"needs_confirmation": needs_confirmation,
		"assumption": assumption,
		"clarification_question": question,
	}


def _apply_hitl_guardrails(bullet_text: str, item: Dict[str, object]) -> Dict[str, object]:
	# Pronoun-heavy bullets are often ambiguous for users and should trigger confirmation.
	if re.search(r"\b(those|this|that|it|they|them)\b", bullet_text, flags=re.IGNORECASE):
		item["confidence"] = "low"
		item["needs_confirmation"] = True
		if not str(item.get("assumption") or "").strip():
			item["assumption"] = "The referent in this point may be ambiguous in context."
		if not str(item.get("clarification_question") or "").strip():
			item["clarification_question"] = f"Can you clarify what the referenced item means in: {bullet_text}?"
	return item


_REMOVE_SENTINEL = "__REMOVE__"

_REMOVAL_PHRASES = re.compile(
	r"\b(remove|delete|drop|exclude|omit|erase|discard|leave\s+blank|leave\s+it\s+out|take\s+(it\s+)?out|get\s+rid\s+of|don.?t\s+(include|keep|show|mention)|not\s+(important|relevant|needed))\b",
	re.IGNORECASE,
)


def _is_removal_intent(feedback: str) -> bool:
	return bool(_REMOVAL_PHRASES.search(feedback))


def _rewrite_bullet_from_feedback(transcript: str, original_bullet: str, user_feedback: str) -> str:
	feedback = user_feedback.strip()
	if not feedback:
		return original_bullet

	# Fast-path: if the user is clearly asking to remove this point, return sentinel immediately.
	if _is_removal_intent(feedback):
		return _REMOVE_SENTINEL

	prompt = (
		"Rewrite a single meeting-summary bullet using transcript context and user correction. "
		"Return JSON only in this form: {\"revised_bullet\":\"...\"}.\n"
		"Rules:\n"
		"- Keep it to one concise bullet sentence.\n"
		"- Preserve factual accuracy based on transcript + user correction.\n"
		"- Do not include a leading dash.\n"
		"- Do not add facts that are absent from transcript and user correction.\n"
		"- Do not copy the user correction verbatim; synthesize a clean final claim.\n"
		"- If the user wants this point removed, deleted, or omitted entirely, return {\"revised_bullet\":\"__REMOVE__\"}.\n\n"
		f"Transcript:\n{transcript}\n\n"
		f"Original bullet:\n{original_bullet}\n\n"
		f"User correction:\n{feedback}"
	)
	raw = generate_with_active_provider(prompt)
	if _is_refusal_like(raw):
		raw = ""
	parsed = _parse_json_payload(raw) if raw else None
	if isinstance(parsed, dict):
		revised = str(parsed.get("revised_bullet", "")).strip()
		if revised and _is_meaningful_rewrite(revised, original_bullet):
			return revised
	plain_prompt = (
		"Return only one corrected summary bullet sentence (no JSON, no quotes, no prefix).\n"
		"Use transcript + user correction to rewrite the original bullet accurately.\n"
		"Do not copy user correction verbatim.\n\n"
		f"Transcript:\n{transcript}\n\n"
		f"Original bullet:\n{original_bullet}\n\n"
		f"User correction:\n{feedback}"
	)
	plain_raw = generate_with_active_provider(plain_prompt, task="hitl")
	if _is_refusal_like(plain_raw):
		plain_raw = ""
	candidate = _extract_bullet_candidate(plain_raw or "")
	if candidate and _is_meaningful_rewrite(candidate, original_bullet):
		return candidate

	# Last-resort deterministic fallback keeps HITL edits usable when provider refuses.
	fallback = _extract_bullet_candidate(feedback)
	if fallback and _is_meaningful_rewrite(fallback, original_bullet):
		return fallback
	return original_bullet


def _parse_json_payload(text: str) -> Dict[str, object] | None:
	if not text:
		return None
	candidate = text.strip()
	fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\}|\[[\s\S]*\])\s*```", candidate)
	if fence_match:
		candidate = fence_match.group(1).strip()
	try:
		return json.loads(candidate)
	except Exception:
		pass
	obj_match = re.search(r"(\{[\s\S]*\})", candidate)
	if obj_match:
		try:
			return json.loads(obj_match.group(1))
		except Exception:
			return None
	return None


def _extract_bullet_candidate(text: str) -> str:
	candidate = (text or "").strip()
	if not candidate:
		return ""
	candidate = re.sub(r"^```(?:json)?", "", candidate, flags=re.IGNORECASE).strip()
	candidate = re.sub(r"```$", "", candidate).strip()
	candidate = re.sub(r"^[-*]\s*", "", candidate).strip()
	candidate = candidate.strip('"\'')
	if "\n" in candidate:
		first_line = next((line.strip() for line in candidate.splitlines() if line.strip()), "")
		candidate = re.sub(r"^[-*]\s*", "", first_line).strip()
	if candidate and candidate[-1] not in ".!?":
		candidate += "."
	return candidate


def _is_meaningful_rewrite(candidate: str, feedback: str) -> bool:
	cand_norm = re.sub(r"[^a-z0-9\s]", " ", candidate.lower())
	fb_norm = re.sub(r"[^a-z0-9\s]", " ", feedback.lower())
	cand_norm = re.sub(r"\s+", " ", cand_norm).strip()
	fb_norm = re.sub(r"\s+", " ", fb_norm).strip()
	if not cand_norm:
		return False
	if cand_norm == fb_norm:
		return False
	if len(cand_norm) < 8:
		return False
	return True
