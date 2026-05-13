from typing import Any

from pydantic import BaseModel, Field


class AdminPermissionsUpdateRequest(BaseModel):
    permissions: dict[str, Any] = Field(default_factory=dict)


class AdminSettingsSectionUpdateRequest(BaseModel):
    value: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)


class AdminGroupUpsertRequest(BaseModel):
    name: str
    description: str | None = None
    sharing_scope: str = "group_admins"
    permissions: dict[str, Any] = Field(default_factory=dict)


class AdminGroupMembershipRequest(BaseModel):
    user_id: str
    role: str = "member"