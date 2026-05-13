import os
from typing import List
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from sqlalchemy import text

from db.session import get_db_session, is_db_enabled


def _get_ollama_url() -> str:
	if os.path.exists("/proc/version"):
		with open("/proc/version", "r") as f:
			if "microsoft" in f.read().lower():
				try:
					with open("/etc/resolv.conf", "r") as resolv:
						for line in resolv:
							if line.startswith("nameserver"):
								windows_ip = line.split()[1].strip()
								return f"http://{windows_ip}:11434/api/generate"
				except Exception:
					pass
	return "http://localhost:11434/api/generate"


OLLAMA_URL = _get_ollama_url()
OLLAMA_MODEL = "llama3.2:latest"

DEFAULT_MODEL_ROUTING = {
	"summary_model_id": "",
	"assistant_model_id": "",
}


def _read_admin_setting(key: str, default_value):
	if not is_db_enabled():
		return default_value

	try:
		with get_db_session() as db:
			if db is None:
				return default_value
			row = db.execute(
				text(
					"""
					SELECT value
					FROM public.admin_setting
					WHERE key = :key
					LIMIT 1
					"""
				),
				{"key": key},
			).fetchone()
			if not row or row.value is None:
				return default_value
			return row.value
	except Exception:
		return default_value


def _normalize_provider(provider: str | None) -> str:
	value = (provider or "").strip().lower()
	if value == "ollama":
		return "ollama"
	if value in {"openai-compatible", "openai", "azure-openai"}:
		return "openai-compatible"
	return value


def get_active_provider() -> dict:
	default_connections = [
		{
			"provider": "ollama",
			"base_url": OLLAMA_URL.replace("/api/generate", ""),
			"enabled": True,
		}
	]
	connections = _read_admin_setting("settings:connections", default_connections) or default_connections

	enabled = []
	for item in connections:
		if not isinstance(item, dict):
			continue
		provider = _normalize_provider(item.get("provider"))
		if provider not in {"ollama", "openai-compatible"}:
			continue
		if item.get("enabled"):
			enabled.append({**item, "provider": provider})

	if len(enabled) > 1:
		raise ValueError("Invalid settings: more than one connection is enabled")

	if len(enabled) == 1:
		return enabled[0]

	for item in connections:
		if not isinstance(item, dict):
			continue
		provider = _normalize_provider(item.get("provider"))
		if provider in {"ollama", "openai-compatible"}:
			return {**item, "provider": provider}

	return default_connections[0]


def get_runtime_for_provider(provider: str) -> str:
	return get_runtime_for_provider_task(provider=provider, task=None)


def _normalize_model_provider(provider: str | None) -> str:
	return _normalize_provider(provider)


def _get_models() -> list[dict]:
	default_models = [
		{
			"id": "default-assistant",
			"provider": "ollama",
			"runtime": OLLAMA_MODEL,
			"system_prompt": "You are Open MeetSum assistant.",
			"capabilities": ["chat", "summary", "hitl"],
			"enabled": True,
		}
	]
	models = _read_admin_setting("settings:models", default_models) or default_models
	return [item for item in models if isinstance(item, dict)]


def _get_model_routing() -> dict:
	routing = _read_admin_setting("settings:model_routing", DEFAULT_MODEL_ROUTING) or DEFAULT_MODEL_ROUTING
	if not isinstance(routing, dict):
		return DEFAULT_MODEL_ROUTING.copy()
	merged = DEFAULT_MODEL_ROUTING.copy()
	merged.update(routing)
	# Backward compatibility with older keys.
	if not str(merged.get("assistant_model_id") or "").strip():
		legacy_chat = str(merged.get("chat_model_id") or "").strip()
		if legacy_chat:
			merged["assistant_model_id"] = legacy_chat
	if "summary_model_id" not in merged:
		merged["summary_model_id"] = ""
	if not str(merged.get("summary_model_id") or "").strip():
		legacy_strategy = str(merged.get("summary_strategy") or "").strip().lower()
		if legacy_strategy in {"provider_primary", "provider_only"}:
			legacy_model_id = str(merged.get("summary_model_id") or "").strip()
			if not legacy_model_id:
				# Keep empty if no explicit model id exists; provider selection will fall back by capability/provider.
				merged["summary_model_id"] = ""
	legacy_mode = str(merged.get("summary_model") or "").strip().lower()
	if legacy_mode == "default" and not str(merged.get("summary_model_id") or "").strip():
		merged["summary_model_id"] = ""
	return merged


def get_summary_strategy() -> str:
	summary_model_id = str(_get_model_routing().get("summary_model_id") or "").strip()
	if summary_model_id:
		return "provider_only"
	return "flan_first"


def get_model_info_for_task(task: str | None) -> dict:
	provider = get_active_provider()
	provider_name = str((provider or {}).get("provider") or "").strip()
	selected = _get_model_for_provider_task(provider=provider_name, task=task) if provider_name else None
	runtime = get_runtime_for_provider_task(provider_name, task) if provider_name else ""
	return {
		"task": task or "",
		"provider": provider_name,
		"model_id": str((selected or {}).get("id") or "").strip(),
		"model_name": str((selected or {}).get("name") or "").strip(),
		"runtime": runtime,
	}


def _get_task_model_id(task: str | None) -> str:
	if not task:
		return ""
	routing = _get_model_routing()
	if task in {"chat", "hitl"}:
		return str(routing.get("assistant_model_id") or "").strip()
	if task == "summary":
		return str(routing.get("summary_model_id") or "").strip()
	return ""


def _get_model_for_provider_task(provider: str, task: str | None) -> dict | None:
	models = _get_models()
	normalized_provider = _normalize_model_provider(provider)
	task_model_id = _get_task_model_id(task)

	if task_model_id:
		for item in models:
			if str(item.get("id") or "").strip() != task_model_id:
				continue
			if _normalize_model_provider(item.get("provider")) != normalized_provider:
				continue
			if item.get("enabled", True) is False:
				continue
			return item

	if task:
		for item in models:
			if _normalize_model_provider(item.get("provider")) != normalized_provider:
				continue
			if item.get("enabled", True) is False:
				continue
			caps = item.get("capabilities") or []
			if isinstance(caps, list) and task in [str(cap).strip().lower() for cap in caps]:
				return item

	for item in models:
		if _normalize_model_provider(item.get("provider")) != normalized_provider:
			continue
		if item.get("enabled", True) is False:
			continue
		return item

	return None


def get_runtime_for_provider_task(provider: str, task: str | None) -> str:
	default_models = [
		{
			"provider": "ollama",
			"runtime": OLLAMA_MODEL,
			"enabled": True,
		}
	]
	selected = _get_model_for_provider_task(provider=provider, task=task)
	if selected:
		runtime = str(selected.get("runtime") or selected.get("name") or "").strip()
		if runtime:
			return runtime

	models = _read_admin_setting("settings:models", default_models) or default_models

	for item in models:
		if not isinstance(item, dict):
			continue
		if _normalize_provider(item.get("provider")) != provider:
			continue
		runtime = str(item.get("runtime") or item.get("name") or "").strip()
		if runtime:
			return runtime

	return OLLAMA_MODEL if provider == "ollama" else "gpt-4o-mini"


def get_system_prompt_for_provider_task(provider: str, task: str | None) -> str:
	if task == "summary":
		return ""
	selected = _get_model_for_provider_task(provider=provider, task=task)
	if not selected:
		return ""
	return str(selected.get("system_prompt") or "").strip()


def _get_ollama_base_candidates(configured_base_url: str | None) -> List[str]:
	configured = str(configured_base_url or "").strip()
	default_base = OLLAMA_URL.replace("/api/generate", "")

	if not configured:
		return [default_base]

	candidates = [configured]
	parsed = urlparse(configured)
	if parsed.hostname in {"localhost", "127.0.0.1", "::1"} and configured.rstrip("/") != default_base.rstrip("/"):
		candidates.append(default_base)

	return candidates


def _ollama_provider_generate(prompt: str, provider_config: dict | None, task: str | None = None) -> str | None:
	runtime = str((provider_config or {}).get("runtime") or get_runtime_for_provider_task("ollama", task)).strip() or OLLAMA_MODEL
	system_prompt = get_system_prompt_for_provider_task("ollama", task)
	prompt_text = prompt
	if system_prompt:
		prompt_text = f"System:\n{system_prompt}\n\nUser:\n{prompt}"

	payload = {
		"model": runtime,
		"prompt": prompt_text,
		"stream": False,
		"options": {
			"temperature": 0.2,
		},
	}

	base_candidates = _get_ollama_base_candidates((provider_config or {}).get("base_url"))

	for index, base_url in enumerate(base_candidates):
		if base_url.endswith("/api/generate"):
			url = base_url
		else:
			url = f"{base_url.rstrip('/')}/api/generate"

		try:
			print(f"[LLM/Ollama] Sending request to {url} with model {runtime}...")
			response = requests.post(url, json=payload, timeout=60)
			response.raise_for_status()
			data = response.json()
			result = str(data.get("response", "")).strip()
			print(f"[LLM/Ollama] Generated {len(result)} chars")
			if len(result) < 100:
				print(f"[LLM/Ollama] Response: {result}")
			return result
		except requests.exceptions.ConnectionError as e:
			if index < len(base_candidates) - 1:
				print(f"[LLM/Ollama] Connection error for {base_url}, trying fallback: {e}")
				continue
			print(f"[LLM/Ollama] Connection error: {e}")
			return None
		except requests.exceptions.Timeout as e:
			print(f"[LLM/Ollama] Timeout error: {e}")
			return None
		except Exception as e:
			print(f"[LLM/Ollama] Unexpected error: {type(e).__name__}: {e}")
			return None

	return None


def _openai_compatible_generate(prompt: str, provider_config: dict, task: str | None = None) -> str | None:
	base_url = str(provider_config.get("base_url") or "").strip()
	if not base_url:
		print("[LLM/OpenAI] Missing base_url in active connection")
		return None

	runtime = get_runtime_for_provider_task("openai-compatible", task)
	model_ids = provider_config.get("model_ids") or []
	if isinstance(model_ids, list) and model_ids:
		runtime = str(model_ids[0]).strip() or runtime
	if not runtime and "/deployments/" in base_url:
		runtime = _extract_deployment_name(base_url)

	connection_type = str(provider_config.get("connection_type") or "").strip().lower()
	api_version = str(provider_config.get("api_version") or "").strip()
	url_candidates = _build_openai_chat_url_candidates(base_url, api_version, runtime, connection_type)

	api_key = (
		str(provider_config.get("api_key") or "").strip()
		or os.getenv("OPENAI_API_KEY", "").strip()
		or os.getenv("AZURE_OPENAI_API_KEY", "").strip()
	)
	auth_type = str(provider_config.get("auth_type") or "").strip().lower()

	system_prompt = get_system_prompt_for_provider_task("openai-compatible", task)

	headers = {"Content-Type": "application/json"}
	if api_key:
		if auth_type == "api-key" or (not auth_type and connection_type == "azure"):
			headers["api-key"] = api_key
		else:
			headers["Authorization"] = f"Bearer {api_key}"

	messages = []
	if system_prompt:
		messages.append({"role": "system", "content": system_prompt})
	messages.append({"role": "user", "content": prompt})

	payload = {
		"messages": messages,
		"temperature": 0.2,
	}

	for index, url in enumerate(url_candidates):
		is_deployment_url = "/deployments/" in url
		request_payload = dict(payload)
		if runtime and not is_deployment_url:
			request_payload["model"] = runtime

		try:
			print(f"[LLM/OpenAI] Sending request to {url} with model {runtime}...")
			response = requests.post(url, headers=headers, json=request_payload, timeout=60)
			response.raise_for_status()
			data = response.json()
			choices = data.get("choices") or []
			if not choices:
				return None
			message = choices[0].get("message") or {}
			content = message.get("content")
			if isinstance(content, list):
				text_parts = []
				for item in content:
					if isinstance(item, dict) and item.get("type") == "text":
						text_parts.append(str(item.get("text") or ""))
				result = "\n".join(part for part in text_parts if part).strip()
			else:
				result = str(content or "").strip()
			print(f"[LLM/OpenAI] Generated {len(result)} chars")
			if len(result) < 100:
				print(f"[LLM/OpenAI] Response: {result}")
			return result or None
		except requests.exceptions.HTTPError as e:
			status_code = e.response.status_code if e.response is not None else 0
			response_text = ""
			if e.response is not None:
				try:
					response_text = str(e.response.text or "").strip()
				except Exception:
					response_text = ""
			if status_code in {400, 404} and index < len(url_candidates) - 1:
				if response_text:
					print(f"[LLM/OpenAI] HTTP {status_code} for {url}: {response_text[:240]}")
				print(f"[LLM/OpenAI] HTTP {status_code} for {url}, trying fallback endpoint...")
				continue
			if response_text:
				print(f"[LLM/OpenAI] HTTP error {status_code} for {url}: {response_text[:240]}")
			else:
				print(f"[LLM/OpenAI] HTTP error {status_code} for {url}: {e}")
			return None
		except requests.exceptions.ConnectionError as e:
			print(f"[LLM/OpenAI] Connection error: {e}")
			return None
		except requests.exceptions.Timeout as e:
			print(f"[LLM/OpenAI] Timeout error: {e}")
			return None
		except Exception as e:
			print(f"[LLM/OpenAI] Unexpected error: {type(e).__name__}: {e}")
			return None

	return None


def _append_api_version(url: str, api_version: str) -> str:
	if not api_version:
		return url
	parsed_url = urlparse(url)
	query_items = parse_qsl(parsed_url.query, keep_blank_values=True)
	if not any(key == "api-version" for key, _ in query_items):
		query_items.append(("api-version", api_version))
	return urlunparse(
		(
			parsed_url.scheme,
			parsed_url.netloc,
			parsed_url.path,
			parsed_url.params,
			urlencode(query_items),
			parsed_url.fragment,
		)
	)


def _build_openai_chat_url_candidates(base_url: str, api_version: str, runtime: str, connection_type: str = "") -> list[str]:
	candidate = base_url.strip()
	if not candidate:
		return []

	parsed = urlparse(candidate)
	path = parsed.path.rstrip("/")
	host = str(parsed.netloc or "").lower()
	base_prefix = urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")

	candidates: list[tuple[str, bool]] = []

	def _path_with(suffix: str) -> str:
		if path:
			return f"{path}/{suffix}"
		return f"/{suffix}"

	prefer_v1 = (
		connection_type in {"aifoundry", "azure"}
		or host.endswith(".cognitiveservices.azure.com")
	)

	# In Foundry/Azure mode, use a single deterministic endpoint only.
	if prefer_v1:
		if path.endswith("/chat/completions") or path.endswith("/responses"):
			return [_append_api_version(candidate, api_version)]
		v1_url = urlunparse((parsed.scheme, parsed.netloc, _path_with("openai/v1/chat/completions"), parsed.params, parsed.query, parsed.fragment))
		# Foundry v1 endpoints generally do not require api-version and can reject it.
		return [v1_url]

	# Respect exact endpoint URLs pasted from Foundry/Open WebUI.
	if path.endswith("/chat/completions") or path.endswith("/responses"):
		candidates.append((candidate, True))
	else:
		candidates.append((urlunparse((parsed.scheme, parsed.netloc, _path_with("chat/completions"), parsed.params, parsed.query, parsed.fragment)), True))
		if not path.endswith("/openai/v1"):
			v1_url = urlunparse((parsed.scheme, parsed.netloc, _path_with("openai/v1/chat/completions"), parsed.params, parsed.query, parsed.fragment))
			# Foundry/OpenAI v1 style often doesn't require api-version.
			candidates.append((v1_url, False))
			candidates.append((v1_url, True))
		if runtime:
			deployment_url = urlunparse((parsed.scheme, parsed.netloc, _path_with(f"openai/deployments/{runtime}/chat/completions"), parsed.params, parsed.query, parsed.fragment))
			candidates.append((deployment_url, True))

	final_urls: list[str] = []
	seen = set()
	for url, with_api_version in candidates:
		clean = _append_api_version(url, api_version) if with_api_version else url
		if clean in seen:
			continue
		seen.add(clean)
		final_urls.append(clean)

	# Defensive fallback for bare resource URLs.
	if not final_urls and runtime:
		fallback = _append_api_version(f"{base_prefix}/openai/deployments/{runtime}/chat/completions", api_version)
		final_urls.append(fallback)

	return final_urls


def _extract_deployment_name(url: str) -> str:
	parts = [part for part in urlparse(url).path.split("/") if part]
	for idx, part in enumerate(parts):
		if part == "deployments" and idx + 1 < len(parts):
			return parts[idx + 1]
	return ""


def generate_with_active_provider(prompt: str, task: str | None = None) -> str | None:
	try:
		provider = get_active_provider()
	except Exception as e:
		print(f"[LLM] Provider selection error: {type(e).__name__}: {e}")
		return None

	if provider and provider.get("provider") == "openai-compatible":
		return _openai_compatible_generate(prompt, provider, task=task)

	return _ollama_provider_generate(prompt, provider, task=task)
