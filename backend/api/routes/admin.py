import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
import requests
from sqlalchemy import text

from api.deps.auth import get_current_user
from db.session import get_db_session, is_db_enabled
from schemas import (
    AdminGroupMembershipRequest,
    AdminGroupUpsertRequest,
    AdminPermissionsUpdateRequest,
    AdminSettingsSectionUpdateRequest,
)

router = APIRouter(prefix="/admin", tags=["admin"])

DEFAULT_USER_PERMISSIONS = {
    "can_create_meetings": True,
    "can_create_chats": True,
    "can_share_workspace_content": False,
    "can_create_groups": False,
    "can_use_external_connections": False,
}

DEFAULT_GROUP_PERMISSIONS = {
    "members_can_invite": False,
    "members_can_share": True,
    "members_can_export": False,
    "visibility": "private",
}

DEFAULT_ADMIN_SETTINGS = {
    "general": {
        "workspace_name": "Open MeetSum",
        "allow_self_signup": True,
        "default_user_role": "member",
        "audit_retention_days": 90,
    },
    "connections": [
        {
            "id": "ollama-local",
            "name": "Local Ollama",
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "api_key": "",
            "enabled": True,
        },
        {
            "id": "custom-api",
            "name": "Custom API",
            "provider": "openai-compatible",
            "connection_type": "azure",
            "auth_type": "bearer",
            "base_url": "",
            "api_key": "",
            "api_version": "",
            "enabled": False,
        },
    ],
    "models": [
        {
            "id": "default-assistant",
            "name": "Default Assistant",
            "provider": "ollama",
            "runtime": "llama3.2:latest",
            "system_prompt": "You are Open MeetSum assistant.",
            "knowledge_scope": "workspace",
            "capabilities": ["chat", "summarization"],
        }
    ],
    "model_routing": {
        "summary_model_id": "",
        "assistant_model_id": "default-assistant",
    },
    "audio": {
        "transcription_backend": "local_whisper",
        "api_provider": "openai-compatible",
        "local_model": "large-v3",
        "default_language": "auto",
    },
    "database": {
        "exports": ["users", "chats", "meetings", "summaries", "groups"],
    },
}


def _require_admin(current_user=Depends(get_current_user)):
    if not current_user.get("is_superuser", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    if not is_db_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured")
    return current_user


def _read_setting(db, key: str, default):
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
        return deepcopy(default)
    return row.value


def _write_setting(db, key: str, value) -> None:
    db.execute(
        text(
            """
            INSERT INTO public.admin_setting (key, value, updated_at)
            VALUES (:key, CAST(:value AS jsonb), NOW())
            ON CONFLICT (key)
            DO UPDATE SET
              value = CAST(:value AS jsonb),
              updated_at = NOW()
            """
        ),
        {"key": key, "value": json.dumps(value)},
    )


def _get_totals(db):
    row = db.execute(
        text(
            """
            SELECT
              (SELECT COUNT(*) FROM public.app_user) AS user_count,
              (SELECT COUNT(*) FROM public.chat_thread) AS chat_count,
              (SELECT COUNT(*) FROM public.meeting) AS meeting_count,
              (SELECT COUNT(*) FROM public.meeting_summary) AS summary_count,
              (SELECT COUNT(*) FROM public.group_workspace) AS group_count
            """
        )
    ).fetchone()
    return dict(row._mapping) if row else {
        "user_count": 0,
        "chat_count": 0,
        "meeting_count": 0,
        "summary_count": 0,
        "group_count": 0,
    }


def _get_users(db):
    rows = db.execute(
        text(
            """
            SELECT
              u.id,
              CASE WHEN u.is_superuser THEN 'admin' ELSE 'member' END AS role,
              COALESCE(NULLIF(TRIM(COALESCE(u.display_name, '')), ''), NULLIF(TRIM(COALESCE(u.username, '')), ''), u.email) AS name,
              u.email,
              u.username,
              u.display_name,
              u.is_active,
              u.is_superuser,
              u.created_at,
              GREATEST(
                COALESCE(u.updated_at, u.created_at),
                COALESCE((SELECT MAX(cm.created_at) FROM public.chat_message cm WHERE cm.created_by = u.id), TIMESTAMPTZ 'epoch'),
                COALESCE((SELECT MAX(m.updated_at) FROM public.meeting m WHERE m.owner_user_id = u.id), TIMESTAMPTZ 'epoch'),
                COALESCE((SELECT MAX(us.updated_at) FROM public.user_settings us WHERE us.user_id = u.id), TIMESTAMPTZ 'epoch')
              ) AS last_active
            FROM public.app_user u
            ORDER BY u.created_at DESC
            """
        )
    ).fetchall()
    return [dict(row._mapping) for row in rows]


def _get_groups(db):
    group_rows = db.execute(
        text(
            """
            SELECT
              g.id,
              g.name,
              g.description,
              g.sharing_scope,
              g.permissions,
              g.created_at,
              g.updated_at,
              COUNT(gm.user_id)::int AS user_count
            FROM public.group_workspace g
            LEFT JOIN public.group_membership gm ON gm.group_id = g.id
            GROUP BY g.id
            ORDER BY LOWER(g.name), g.created_at ASC
            """
        )
    ).fetchall()

    membership_rows = db.execute(
        text(
            """
            SELECT
              gm.group_id,
              gm.user_id,
              gm.role,
              u.email,
              u.username,
              u.display_name,
              u.is_active,
              u.is_superuser,
              u.created_at,
              gm.created_at AS joined_at
            FROM public.group_membership gm
            JOIN public.app_user u ON u.id = gm.user_id
            ORDER BY gm.group_id, LOWER(COALESCE(u.display_name, u.username, u.email))
            """
        )
    ).fetchall()

    members_by_group: dict[str, list[dict]] = {}
    for row in membership_rows:
        payload = dict(row._mapping)
        members_by_group.setdefault(payload["group_id"], []).append(
            {
                "user_id": payload["user_id"],
                "role": payload["role"],
                "email": payload["email"],
                "username": payload.get("username"),
                "display_name": payload.get("display_name"),
                "is_active": payload.get("is_active", True),
                "is_superuser": payload.get("is_superuser", False),
                "created_at": payload.get("created_at"),
                "joined_at": payload.get("joined_at"),
            }
        )

    groups = []
    for row in group_rows:
        payload = dict(row._mapping)
        payload["permissions"] = payload.get("permissions") or {}
        payload["members"] = members_by_group.get(payload["id"], [])
        groups.append(payload)
    return groups


def _get_settings_payload(db):
    return {
        section: _read_setting(db, f"settings:{section}", default_value)
        for section, default_value in DEFAULT_ADMIN_SETTINGS.items()
    }


def _validate_connections_payload(value):
    if not isinstance(value, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Connections settings must be a list")

    enabled_providers = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        if not item.get("enabled"):
            continue

        provider = str(item.get("provider") or "").strip().lower()
        if provider == "ollama":
            enabled_providers.add("ollama")
        elif provider in {"openai-compatible", "openai", "azure-openai"}:
            enabled_providers.add("openai-compatible")

    if len(enabled_providers) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only one connection provider can be enabled at a time",
        )


def _normalize_provider(provider: str | None) -> str:
    value = str(provider or "").strip().lower()
    if value == "ollama":
        return "ollama"
    if value in {"openai-compatible", "openai", "azure-openai"}:
        return "openai-compatible"
    return value


def _slugify_runtime(runtime: str) -> str:
    return (
        runtime.strip().lower().replace(":", "-").replace("/", "-").replace(" ", "-").replace("_", "-")
    )


def _get_ollama_default_base_url() -> str:
    # Mirror runtime behavior in WSL where localhost may not reach Windows-hosted Ollama.
    try:
        if os.path.exists("/proc/version"):
            with open("/proc/version", "r", encoding="utf-8") as version_file:
                if "microsoft" in version_file.read().lower() and os.path.exists("/etc/resolv.conf"):
                    with open("/etc/resolv.conf", "r", encoding="utf-8") as resolv_file:
                        for line in resolv_file:
                            if line.startswith("nameserver"):
                                windows_ip = line.split()[1].strip()
                                if windows_ip:
                                    return f"http://{windows_ip}:11434"
    except Exception:
        pass
    return "http://localhost:11434"


def _get_ollama_base_candidates(configured_base_url: str | None) -> list[str]:
    configured = str(configured_base_url or "").strip().rstrip("/")
    default_base = _get_ollama_default_base_url().rstrip("/")
    if not configured:
        return [default_base]

    candidates = [configured]
    parsed = urlparse(configured)
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"} and configured != default_base:
        candidates.append(default_base)
    return candidates


def _discover_ollama_models(connection: dict) -> tuple[list[dict], str | None]:
    base_candidates = _get_ollama_base_candidates(connection.get("base_url"))
    last_error = "Ollama discovery failed"
    for base_url in base_candidates:
        url = f"{base_url.rstrip('/')}/api/tags"
        try:
            response = requests.get(url, timeout=8)
            response.raise_for_status()
            payload = response.json()
            models = payload.get("models") or []
            discovered = []
            for item in models:
                if not isinstance(item, dict):
                    continue
                runtime = str(item.get("name") or "").strip()
                if not runtime:
                    continue
                discovered.append(
                    {
                        "id": f"model-ollama-{_slugify_runtime(runtime)}",
                        "name": runtime,
                        "provider": "ollama",
                        "runtime": runtime,
                        "connection_id": str(connection.get("id") or "ollama-local"),
                        "knowledge_scope": "workspace",
                        "capabilities": ["chat", "summary", "hitl"],
                        "system_prompt": "You are Open MeetSum assistant.",
                        "enabled": True,
                    }
                )
            return discovered, None
        except Exception as exc:
            last_error = f"Ollama discovery failed via {base_url}: {type(exc).__name__}: {exc}"
            continue
    return [], last_error


def _build_openai_models_url(base_url: str, api_version: str) -> str:
    candidate = base_url.strip()
    if not candidate:
        return ""
    if candidate.endswith("/chat/completions"):
        candidate = candidate[: -len("/chat/completions")]
    if not candidate.endswith("/models"):
        candidate = f"{candidate.rstrip('/')}/models"
    if api_version and "api-version=" not in candidate:
        separator = "&" if "?" in candidate else "?"
        candidate = f"{candidate}{separator}api-version={api_version}"
    return candidate


def _extract_deployment_name_from_url(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    for idx, part in enumerate(parts):
        if part == "deployments" and idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def _build_openai_discovery_headers(connection: dict) -> dict:
    api_key = str(connection.get("api_key") or "").strip()
    auth_type = str(connection.get("auth_type") or "").strip().lower()
    connection_type = str(connection.get("connection_type") or "").strip().lower()
    headers = {"Content-Type": "application/json"}
    if not api_key:
        return headers
    if auth_type == "api-key" or (not auth_type and connection_type == "azure"):
        headers["api-key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _discover_openai_models_from_config(connection: dict) -> list[str]:
    runtimes: list[str] = []
    model_ids = connection.get("model_ids")
    if isinstance(model_ids, list):
        runtimes.extend(str(item).strip() for item in model_ids if str(item).strip())
    deployment = _extract_deployment_name_from_url(str(connection.get("base_url") or ""))
    if deployment:
        runtimes.append(deployment)
    seen = set()
    deduped = []
    for runtime in runtimes:
        if runtime in seen:
            continue
        seen.add(runtime)
        deduped.append(runtime)
    return deduped


def _discover_openai_models(connection: dict) -> tuple[list[dict], str | None]:
    base_url = str(connection.get("base_url") or "").strip()
    if not base_url:
        return [], "OpenAI-compatible base URL is missing"
    api_version = str(connection.get("api_version") or "").strip()
    url = _build_openai_models_url(base_url, api_version)
    if not url:
        return [], "OpenAI-compatible models URL is missing"

    headers = _build_openai_discovery_headers(connection)

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        payload = response.json()
        items = payload.get("data") or payload.get("models") or []
        discovered = []
        for item in items:
            if isinstance(item, dict):
                runtime = str(item.get("id") or item.get("name") or "").strip()
            else:
                runtime = str(item or "").strip()
            if not runtime:
                continue
            discovered.append(
                {
                    "id": f"model-openai-{_slugify_runtime(runtime)}",
                    "name": runtime,
                    "provider": "openai-compatible",
                    "runtime": runtime,
                    "connection_id": str(connection.get("id") or "custom-api"),
                    "knowledge_scope": "workspace",
                    "capabilities": ["chat", "summary", "hitl"],
                    "system_prompt": "You are Open MeetSum assistant.",
                    "enabled": True,
                }
            )
        return discovered, None
    except Exception as exc:
        from_config = _discover_openai_models_from_config(connection)
        if from_config:
            discovered = []
            for runtime in from_config:
                discovered.append(
                    {
                        "id": f"model-openai-{_slugify_runtime(runtime)}",
                        "name": runtime,
                        "provider": "openai-compatible",
                        "runtime": runtime,
                        "connection_id": str(connection.get("id") or "custom-api"),
                        "knowledge_scope": "workspace",
                        "capabilities": ["chat", "summary", "hitl"],
                        "system_prompt": "You are Open MeetSum assistant.",
                        "enabled": True,
                    }
                )
            return discovered, None
        return [], f"OpenAI-compatible discovery failed: {type(exc).__name__}: {exc}"


def _merge_discovered_models(existing_models: list, discovered_models: list[dict]) -> list[dict]:
    existing_by_id = {}
    for item in existing_models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if model_id:
            existing_by_id[model_id] = item

    merged = []
    for discovered in discovered_models:
        model_id = str(discovered.get("id") or "").strip()
        prior = existing_by_id.get(model_id, {})
        merged.append(
            {
                **discovered,
                "name": str(prior.get("name") or discovered.get("name") or "").strip(),
                "system_prompt": str(prior.get("system_prompt") or discovered.get("system_prompt") or "").strip(),
                "knowledge_scope": str(prior.get("knowledge_scope") or discovered.get("knowledge_scope") or "workspace").strip(),
                "capabilities": prior.get("capabilities") if isinstance(prior.get("capabilities"), list) else discovered.get("capabilities", ["chat"]),
            }
        )
    return merged


@router.get("/panel")
def get_admin_panel(current_user=Depends(_require_admin)):
    with get_db_session() as db:
        users = _get_users(db)
        groups = _get_groups(db)
        totals = _get_totals(db)
        user_defaults = _read_setting(db, "defaults:user_permissions", DEFAULT_USER_PERMISSIONS)
        group_defaults = _read_setting(db, "defaults:group_permissions", DEFAULT_GROUP_PERMISSIONS)
        settings = _get_settings_payload(db)

    return {
        "users": users,
        "groups": groups,
        "totals": totals,
        "user_defaults": user_defaults,
        "group_defaults": group_defaults,
        "settings": settings,
    }


@router.patch("/defaults/users")
def update_default_user_permissions(
    payload: AdminPermissionsUpdateRequest,
    current_user=Depends(_require_admin),
):
    with get_db_session() as db:
        _write_setting(db, "defaults:user_permissions", payload.permissions)
        db.commit()
    return {"permissions": payload.permissions}


@router.patch("/defaults/groups")
def update_default_group_permissions(
    payload: AdminPermissionsUpdateRequest,
    current_user=Depends(_require_admin),
):
    with get_db_session() as db:
        _write_setting(db, "defaults:group_permissions", payload.permissions)
        db.commit()
    return {"permissions": payload.permissions}


@router.patch("/settings/{section}")
def update_admin_settings_section(
    section: str,
    payload: AdminSettingsSectionUpdateRequest,
    current_user=Depends(_require_admin),
):
    if section not in DEFAULT_ADMIN_SETTINGS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Settings section not found")

    if section == "connections":
        _validate_connections_payload(payload.value)

    with get_db_session() as db:
        _write_setting(db, f"settings:{section}", payload.value)
        db.commit()
    return {"section": section, "value": payload.value}


@router.post("/connections/discover-models")
def discover_models_from_connections(current_user=Depends(_require_admin)):
    with get_db_session() as db:
        connections = _read_setting(db, "settings:connections", DEFAULT_ADMIN_SETTINGS["connections"])
        models = _read_setting(db, "settings:models", DEFAULT_ADMIN_SETTINGS["models"])

    if not isinstance(connections, list):
        connections = []
    if not isinstance(models, list):
        models = []

    discovered: list[dict] = []
    statuses: list[dict] = []
    for connection in connections:
        if not isinstance(connection, dict):
            continue
        if not bool(connection.get("enabled")):
            continue
        provider = _normalize_provider(connection.get("provider"))
        connection_id = str(connection.get("id") or provider or "connection")
        if provider == "ollama":
            items, error = _discover_ollama_models(connection)
        elif provider == "openai-compatible":
            items, error = _discover_openai_models(connection)
        else:
            continue

        if items:
            discovered.extend(items)
            statuses.append({
                "connection_id": connection_id,
                "provider": provider,
                "ok": True,
                "attempted": True,
                "count": len(items),
                "base_url": str(connection.get("base_url") or ""),
            })
        else:
            statuses.append({
                "connection_id": connection_id,
                "provider": provider,
                "ok": False,
                "attempted": True,
                "count": 0,
                "base_url": str(connection.get("base_url") or ""),
                "error": error or "No models returned",
            })

    merged = _merge_discovered_models(models, discovered) if discovered else [item for item in models if isinstance(item, dict)]

    attempted = statuses
    successful = [item for item in attempted if item.get("ok") is True]
    failed = [item for item in attempted if item.get("ok") is False]

    with get_db_session() as db:
        _write_setting(db, "settings:models", merged)
        db.commit()

    return {
        "models": merged,
        "connections": statuses,
        "attempted_connections": len(attempted),
        "successful_connections": len(successful),
        "failed_connections": len(failed),
    }


@router.post("/groups")
def create_group(payload: AdminGroupUpsertRequest, current_user=Depends(_require_admin)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Group name cannot be empty")

    with get_db_session() as db:
        row = db.execute(
            text(
                """
                INSERT INTO public.group_workspace (name, description, sharing_scope, permissions)
                VALUES (:name, :description, :sharing_scope, CAST(:permissions AS jsonb))
                RETURNING id
                """
            ),
            {
                "name": name,
                "description": (payload.description or "").strip() or None,
                "sharing_scope": payload.sharing_scope,
                "permissions": json.dumps(payload.permissions or {}),
            },
        ).fetchone()
        db.commit()
    return {"id": row.id}


@router.patch("/groups/{group_id}")
def update_group(group_id: str, payload: AdminGroupUpsertRequest, current_user=Depends(_require_admin)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Group name cannot be empty")

    with get_db_session() as db:
        row = db.execute(
            text(
                """
                UPDATE public.group_workspace
                SET name = :name,
                    description = :description,
                    sharing_scope = :sharing_scope,
                    permissions = CAST(:permissions AS jsonb),
                    updated_at = NOW()
                WHERE id = :group_id
                RETURNING id
                """
            ),
            {
                "group_id": group_id,
                "name": name,
                "description": (payload.description or "").strip() or None,
                "sharing_scope": payload.sharing_scope,
                "permissions": json.dumps(payload.permissions or {}),
            },
        ).fetchone()
        if not row:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
        db.commit()
    return {"id": group_id}


@router.post("/groups/{group_id}/members")
def add_group_member(
    group_id: str,
    payload: AdminGroupMembershipRequest,
    current_user=Depends(_require_admin),
):
    with get_db_session() as db:
        group_exists = db.execute(
            text("SELECT id FROM public.group_workspace WHERE id = :group_id LIMIT 1"),
            {"group_id": group_id},
        ).fetchone()
        if not group_exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

        user_exists = db.execute(
            text("SELECT id FROM public.app_user WHERE id = :user_id LIMIT 1"),
            {"user_id": payload.user_id},
        ).fetchone()
        if not user_exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        db.execute(
            text(
                """
                INSERT INTO public.group_membership (group_id, user_id, role)
                VALUES (:group_id, :user_id, :role)
                ON CONFLICT (group_id, user_id)
                DO UPDATE SET role = EXCLUDED.role
                """
            ),
            {"group_id": group_id, "user_id": payload.user_id, "role": payload.role},
        )
        db.commit()
    return {"group_id": group_id, "user_id": payload.user_id, "role": payload.role}


@router.delete("/groups/{group_id}/members/{user_id}")
def remove_group_member(group_id: str, user_id: str, current_user=Depends(_require_admin)):
    with get_db_session() as db:
        row = db.execute(
            text(
                """
                DELETE FROM public.group_membership
                WHERE group_id = :group_id AND user_id = :user_id
                RETURNING user_id
                """
            ),
            {"group_id": group_id, "user_id": user_id},
        ).fetchone()
        if not row:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found")
        db.commit()
    return {"deleted": True, "group_id": group_id, "user_id": user_id}


@router.get("/export/{resource}")
def export_admin_resource(resource: str, current_user=Depends(_require_admin)):
    resource_queries = {
        "users": "SELECT id, email, username, display_name, is_active, is_superuser, created_at, updated_at FROM public.app_user ORDER BY created_at DESC",
        "chats": "SELECT id, title, owner_user_id, created_at, updated_at FROM public.chat_thread ORDER BY created_at DESC",
        "meetings": "SELECT id, title, source, owner_user_id, meeting_date, status, created_at, updated_at FROM public.meeting ORDER BY created_at DESC",
        "summaries": "SELECT id, meeting_id, version, model_runtime_name, created_at FROM public.meeting_summary ORDER BY created_at DESC",
        "groups": "SELECT id, name, description, sharing_scope, permissions, created_at, updated_at FROM public.group_workspace ORDER BY created_at DESC",
    }
    query = resource_queries.get(resource)
    if query is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export resource not found")

    with get_db_session() as db:
        rows = db.execute(text(query)).fetchall()

    return {
        "resource": resource,
        "exported_at": datetime.now(timezone.utc),
        "items": [dict(row._mapping) for row in rows],
    }