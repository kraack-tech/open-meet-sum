import re
from typing import Any, Dict, List, Optional


KnowledgeAction = Dict[str, Any]
KnowledgeEntry = Dict[str, Any]


_KNOWLEDGE_ENTRIES: List[KnowledgeEntry] = [
	{
		"id": "speaker_enrollment",
		"title": "Speaker enrollment",
		"keywords": [
			"speaker",
			"speakers",
			"enroll",
			"enrollment",
			"employee",
			"voice",
			"attendee",
			"participant",
		],
		"patterns": [
			r"\b(enroll|add|register|setup|set up|onboard)\b.{0,30}\b(speaker|employee|voice|participant|attendee)\b",
			r"\b(speaker|employee|voice|participant|attendee)\b.{0,30}\b(enroll|add|register|setup|set up|onboard)\b",
		],
		"answer": (
			"To enroll a speaker in MeetSum, open the live meeting flow with speaker labels enabled. "
			"In Meeting attendees, you can select saved speakers and finish the attendee list. "
			"In Speaker enrollments, add a name, record a sample for that speaker, and then finish enrollment. "
			"The enrollment UI uses the on-screen sentence and records up to about 8 seconds per sample."
		),
		"actions": [
			{"type": "start_speaker_enrollment", "label": "Start speaker enrollment"},
			{"type": "start_meeting", "label": "Start a live meeting"},
		],
	},
	{
		"id": "start_live_meeting",
		"title": "Start a live meeting",
		"keywords": ["start", "live", "meeting", "record", "recording", "session"],
		"patterns": [
			r"\b(start|begin|launch|open|create|new)\b.{0,30}\b(meeting|session)\b",
			r"\bstart\b.{0,20}\brecording\b",
		],
		"answer": (
			"Starting a live meeting in MeetSum switches into record mode and immediately starts the live transcriber. "
			"If speaker labels are enabled, the speaker enrollment panel stays available in that flow."
		),
		"actions": [
			{"type": "start_meeting", "label": "Start a live meeting"},
			{"type": "start_speaker_enrollment", "label": "Start speaker enrollment"},
		],
	},
	{
		"id": "upload_meeting_recording",
		"title": "Upload a meeting recording",
		"keywords": ["upload", "audio", "recording", "file", "transcribe", "import"],
		"patterns": [
			r"\b(upload|import|transcribe|add)\b.{0,30}\b(audio|recording|file|meeting)\b",
		],
		"answer": (
			"MeetSum can also process an uploaded recording. "
			"That opens the upload flow instead of the live recorder, and historical meetings show attendees in read-only mode."
		),
		"actions": [
			{"type": "upload_meeting", "label": "Upload a meeting recording"},
		],
	},
	{
		"id": "notes_and_summaries",
		"title": "Notes and summaries",
		"keywords": ["notes", "note", "summary", "summaries", "action items", "minutes"],
		"patterns": [
			r"\b(create|generate|make|get|show)\b.{0,30}\b(notes|summary|summaries|minutes|action items)\b",
			r"\b(notes|summary|summaries|minutes|action items)\b",
		],
		"answer": (
			"MeetSum does not currently expose a standalone chat action to create notes directly. "
			"Notes and summaries come from a live meeting or an uploaded recording after transcription and summary generation. "
			"If you want meeting notes, start a live meeting or upload a recording first."
		),
		"actions": [
			{"type": "start_meeting", "label": "Start a live meeting"},
			{"type": "upload_meeting", "label": "Upload a meeting recording"},
		],
	},
	{
		"id": "workspace_management",
		"title": "Workspace management",
		"keywords": ["workspace", "workspaces", "create workspace", "new workspace"],
		"patterns": [
			r"\b(create|new|add|open|manage)\b.{0,30}\bworkspace(s)?\b",
			r"\bworkspace(s)?\b",
		],
		"answer": (
			"I do not have a verified MeetSum workspace-management flow in this build. "
			"I cannot reliably guide workspace creation from the app yet."
		),
		"actions": [],
	},
	{
		"id": "user_settings",
		"title": "User settings",
		"keywords": ["settings", "preferences", "theme", "language", "spoken", "sidebar", "label"],
		"patterns": [
			r"\b(open|change|update|set|switch)\b.{0,30}\b(settings|preferences|theme|language|sidebar)\b",
			r"\b(settings|preferences|theme|language|sidebar)\b",
		],
		"answer": (
			"MeetSum has user settings for theme, app language, spoken language, and sidebar label mode. "
			"The app can open user settings directly, and changes are saved to your account through the settings API."
		),
		"actions": [
			{"type": "open_settings", "label": "Open user settings"},
			{"type": "set_theme_light", "label": "Set theme to Light"},
			{"type": "set_theme_dark", "label": "Set theme to Dark"},
			{"type": "set_language_en", "label": "Set app language to English"},
			{"type": "set_spoken_language", "label": "Set spoken language to Auto-detect", "payload": {"spoken_language": "auto"}},
			{"type": "set_sidebar_label_auto", "label": "Sidebar label: Auto"},
			{"type": "set_sidebar_label_username", "label": "Sidebar label: Username"},
			{"type": "set_sidebar_label_email", "label": "Sidebar label: Email"},
		],
	},
	{
		"id": "theme_setting",
		"title": "Theme setting",
		"keywords": ["theme", "light", "dark", "appearance"],
		"patterns": [
			r"\b(light|dark)\b.{0,20}\b(theme|mode|appearance)\b",
			r"\b(theme|appearance)\b.{0,20}\b(light|dark)\b",
		],
		"answer": (
			"MeetSum supports light and dark theme settings. "
			"Changing the theme updates the app settings and applies the new theme immediately."
		),
		"actions": [
			{"type": "set_theme_light", "label": "Set theme to Light"},
			{"type": "set_theme_dark", "label": "Set theme to Dark"},
		],
	},
	{
		"id": "language_settings",
		"title": "Language settings",
		"keywords": ["language", "spoken", "transcription", "app language", "spoken language"],
		"patterns": [
			r"\b(app\s+language|spoken\s+language|transcription\s+language|language)\b",
		],
		"answer": (
			"MeetSum stores both an app language and a spoken language setting. "
			"App language controls the interface language, while spoken language is used for transcription behavior and can be set to auto-detect."
		),
		"actions": [
			{"type": "open_settings", "label": "Open user settings"},
			{"type": "set_language_en", "label": "Set app language to English"},
			{"type": "set_spoken_language", "label": "Set spoken language to Auto-detect", "payload": {"spoken_language": "auto"}},
		],
	},
	{
		"id": "sidebar_label_mode",
		"title": "Sidebar label mode",
		"keywords": ["sidebar", "label", "username", "email", "auto"],
		"patterns": [
			r"\b(sidebar\s+label|label\s+mode|username|email)\b",
		],
		"answer": (
			"MeetSum can show your sidebar label in auto, username, or email mode. "
			"That setting is stored with the rest of your account preferences."
		),
		"actions": [
			{"type": "open_settings", "label": "Open user settings"},
			{"type": "set_sidebar_label_auto", "label": "Sidebar label: Auto"},
			{"type": "set_sidebar_label_username", "label": "Sidebar label: Username"},
			{"type": "set_sidebar_label_email", "label": "Sidebar label: Email"},
		],
	},
	{
		"id": "chat_general_mode",
		"title": "General chat mode",
		"keywords": ["general", "chat", "mode", "normal"],
		"patterns": [
			r"\b(general|normal)\s+chat\s+mode\b",
			r"\bswitch\b.{0,20}\bgeneral\s+chat\b",
		],
		"answer": (
			"Switching back to general chat mode keeps you in chat and clears the pending agent action cards."
		),
		"actions": [
			{"type": "chat_general_mode", "label": "Switch to general chat mode"},
		],
	},
]


def _normalize_text(text: str) -> str:
	return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tokenize(text: str) -> set[str]:
	return set(re.findall(r"[a-z0-9_]+", _normalize_text(text)))


def _entry_score(entry: KnowledgeEntry, normalized_text: str, tokens: set[str]) -> int:
	score = 0
	for pattern in entry.get("patterns", []):
		if re.search(pattern, normalized_text):
			score += 5

	for keyword in entry.get("keywords", []):
		keyword_normalized = _normalize_text(keyword)
		if not keyword_normalized:
			continue
		if " " in keyword_normalized:
			if keyword_normalized in normalized_text:
				score += 3
		elif keyword_normalized in tokens:
			score += 2

	return score


def lookup_app_knowledge(user_message: str) -> Optional[Dict[str, Any]]:
	normalized_text = _normalize_text(user_message)
	if not normalized_text:
		return None

	tokens = _tokenize(normalized_text)
	best_entry: Optional[KnowledgeEntry] = None
	best_score = 0
	for entry in _KNOWLEDGE_ENTRIES:
		score = _entry_score(entry, normalized_text, tokens)
		if score > best_score:
			best_score = score
			best_entry = entry

	if not best_entry or best_score < 5:
		return None

	return {
		"id": best_entry["id"],
		"title": best_entry["title"],
		"answer": best_entry["answer"],
		"actions": list(best_entry.get("actions", [])),
		"score": best_score,
	}