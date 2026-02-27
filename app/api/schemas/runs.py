from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import ApiMeta


class RunListItemData(BaseModel):
    id: int
    trigger_type: str
    status: str
    start_dt: datetime
    end_dt: datetime | None
    scholar_count: int
    new_publication_count: int
    failed_count: int
    partial_count: int

    model_config = ConfigDict(extra="forbid")


class ScrapeSafetyCountersData(BaseModel):
    consecutive_blocked_runs: int = 0
    consecutive_network_runs: int = 0
    cooldown_entry_count: int = 0
    blocked_start_count: int = 0
    last_blocked_failure_count: int = 0
    last_network_failure_count: int = 0
    last_evaluated_run_id: int | None = None

    model_config = ConfigDict(extra="forbid")


class ScrapeSafetyStateData(BaseModel):
    cooldown_active: bool
    cooldown_reason: str | None = None
    cooldown_reason_label: str | None = None
    cooldown_until: datetime | None = None
    cooldown_remaining_seconds: int = 0
    recommended_action: str | None = None
    counters: ScrapeSafetyCountersData = Field(default_factory=ScrapeSafetyCountersData)

    model_config = ConfigDict(extra="forbid")


class RunsListData(BaseModel):
    runs: list[RunListItemData]
    safety_state: ScrapeSafetyStateData

    model_config = ConfigDict(extra="forbid")


class RunsListEnvelope(BaseModel):
    data: RunsListData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class RunSummaryData(BaseModel):
    succeeded_count: int
    failed_count: int
    partial_count: int
    failed_state_counts: dict[str, int] = Field(default_factory=dict)
    failed_reason_counts: dict[str, int] = Field(default_factory=dict)
    scrape_failure_counts: dict[str, int] = Field(default_factory=dict)
    retry_counts: dict[str, int] = Field(default_factory=dict)
    alert_thresholds: dict[str, int] = Field(default_factory=dict)
    alert_flags: dict[str, bool] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class RunAttemptLogData(BaseModel):
    attempt: int
    cstart: int
    state: str | None = None
    state_reason: str | None = None
    status_code: int | None = None
    fetch_error: str | None = None

    model_config = ConfigDict(extra="forbid")


class RunPageLogData(BaseModel):
    page: int
    cstart: int
    state: str
    state_reason: str | None = None
    status_code: int | None = None
    publication_count: int = 0
    attempt_count: int = 0
    has_show_more_button: bool = False
    articles_range: str | None = None
    warning_codes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class RunDebugData(BaseModel):
    status_code: int | None = None
    final_url: str | None = None
    fetch_error: str | None = None
    body_sha256: str | None = None
    body_length: int | None = None
    has_show_more_button: bool | None = None
    articles_range: str | None = None
    state_reason: str | None = None
    warning_codes: list[str] = Field(default_factory=list)
    marker_counts_nonzero: dict[str, int] = Field(default_factory=dict)
    page_logs: list[RunPageLogData] = Field(default_factory=list)
    attempt_log: list[RunAttemptLogData] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class RunScholarResultData(BaseModel):
    scholar_profile_id: int
    scholar_id: str
    state: str
    state_reason: str | None = None
    outcome: str
    attempt_count: int = 0
    publication_count: int = 0
    start_cstart: int = 0
    continuation_cstart: int | None = None
    continuation_enqueued: bool = False
    continuation_cleared: bool = False
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    debug: RunDebugData | None = None

    model_config = ConfigDict(extra="forbid")


class RunDetailData(BaseModel):
    run: RunListItemData
    summary: RunSummaryData
    scholar_results: list[RunScholarResultData]
    safety_state: ScrapeSafetyStateData

    model_config = ConfigDict(extra="forbid")


class RunDetailEnvelope(BaseModel):
    data: RunDetailData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class ManualRunData(BaseModel):
    run_id: int
    status: str
    scholar_count: int
    succeeded_count: int
    failed_count: int
    partial_count: int
    new_publication_count: int
    reused_existing_run: bool
    idempotency_key: str | None = None
    safety_state: ScrapeSafetyStateData

    model_config = ConfigDict(extra="forbid")


class ManualRunEnvelope(BaseModel):
    data: ManualRunData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class QueueItemData(BaseModel):
    id: int
    scholar_profile_id: int
    scholar_label: str
    status: str
    reason: str
    dropped_reason: str | None
    attempt_count: int
    resume_cstart: int
    next_attempt_dt: datetime | None
    updated_at: datetime
    last_error: str | None
    last_run_id: int | None

    model_config = ConfigDict(extra="forbid")


class QueueListData(BaseModel):
    queue_items: list[QueueItemData]

    model_config = ConfigDict(extra="forbid")


class QueueListEnvelope(BaseModel):
    data: QueueListData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class QueueItemEnvelope(BaseModel):
    data: QueueItemData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class QueueClearData(BaseModel):
    queue_item_id: int
    previous_status: str
    status: str
    message: str

    model_config = ConfigDict(extra="forbid")


class QueueClearEnvelope(BaseModel):
    data: QueueClearData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")
