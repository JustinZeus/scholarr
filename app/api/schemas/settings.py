from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.api.schemas.common import ApiMeta
from app.api.schemas.runs import ScrapeSafetyStateData


class SettingsPolicyData(BaseModel):
    min_run_interval_minutes: int
    min_request_delay_seconds: int
    automation_allowed: bool
    manual_run_allowed: bool
    blocked_failure_threshold: int
    network_failure_threshold: int
    cooldown_blocked_seconds: int
    cooldown_network_seconds: int

    model_config = ConfigDict(extra="forbid")


class SettingsData(BaseModel):
    auto_run_enabled: bool
    run_interval_minutes: int
    request_delay_seconds: int
    nav_visible_pages: list[str]
    policy: SettingsPolicyData
    safety_state: ScrapeSafetyStateData

    openalex_api_key: str | None = None
    crossref_api_token: str | None = None
    crossref_api_mailto: str | None = None

    model_config = ConfigDict(extra="forbid")


class SettingsEnvelope(BaseModel):
    data: SettingsData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class SettingsUpdateRequest(BaseModel):
    auto_run_enabled: bool
    run_interval_minutes: int
    request_delay_seconds: int
    nav_visible_pages: list[str] | None = None

    openalex_api_key: str | None = None
    crossref_api_token: str | None = None
    crossref_api_mailto: str | None = None

    model_config = ConfigDict(extra="forbid")
