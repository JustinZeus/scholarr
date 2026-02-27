from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import ApiMeta


class DisplayIdentifierData(BaseModel):
    kind: str
    value: str
    label: str
    url: str | None
    confidence_score: float = Field(ge=0.0, le=1.0)

    model_config = ConfigDict(extra="forbid")


class PublicationItemData(BaseModel):
    publication_id: int
    scholar_profile_id: int
    scholar_label: str
    title: str
    year: int | None
    citation_count: int
    venue_text: str | None
    pub_url: str | None
    display_identifier: DisplayIdentifierData | None = None
    pdf_url: str | None
    pdf_status: str = "untracked"
    pdf_attempt_count: int = 0
    pdf_failure_reason: str | None = None
    pdf_failure_detail: str | None = None
    is_read: bool
    is_favorite: bool = False
    first_seen_at: datetime
    is_new_in_latest_run: bool

    model_config = ConfigDict(extra="forbid")


class PublicationsListData(BaseModel):
    mode: str
    favorite_only: bool = False
    selected_scholar_profile_id: int | None
    unread_count: int
    favorites_count: int
    latest_count: int
    new_count: int
    total_count: int
    page: int
    page_size: int
    snapshot: str
    has_next: bool = False
    has_prev: bool = False
    publications: list[PublicationItemData]

    model_config = ConfigDict(extra="forbid")


class PublicationsListEnvelope(BaseModel):
    data: PublicationsListData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class MarkAllReadData(BaseModel):
    message: str
    updated_count: int

    model_config = ConfigDict(extra="forbid")


class MarkAllReadEnvelope(BaseModel):
    data: MarkAllReadData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class PublicationSelectionItem(BaseModel):
    scholar_profile_id: int
    publication_id: int

    model_config = ConfigDict(extra="forbid")


class MarkSelectedReadRequest(BaseModel):
    selections: list[PublicationSelectionItem] = Field(min_length=1, max_length=500)

    model_config = ConfigDict(extra="forbid")


class MarkSelectedReadData(BaseModel):
    message: str
    requested_count: int
    updated_count: int

    model_config = ConfigDict(extra="forbid")


class MarkSelectedReadEnvelope(BaseModel):
    data: MarkSelectedReadData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class RetryPublicationPdfRequest(BaseModel):
    scholar_profile_id: int = Field(ge=1)

    model_config = ConfigDict(extra="forbid")


class RetryPublicationPdfData(BaseModel):
    message: str
    queued: bool
    resolved_pdf: bool
    publication: PublicationItemData

    model_config = ConfigDict(extra="forbid")


class RetryPublicationPdfEnvelope(BaseModel):
    data: RetryPublicationPdfData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class TogglePublicationFavoriteRequest(BaseModel):
    scholar_profile_id: int = Field(ge=1)
    is_favorite: bool

    model_config = ConfigDict(extra="forbid")


class TogglePublicationFavoriteData(BaseModel):
    message: str
    publication: PublicationItemData

    model_config = ConfigDict(extra="forbid")


class TogglePublicationFavoriteEnvelope(BaseModel):
    data: TogglePublicationFavoriteData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")
