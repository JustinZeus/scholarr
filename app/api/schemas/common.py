from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ApiMeta(BaseModel):
    request_id: str | None = None

    model_config = ConfigDict(extra="forbid")


class ApiErrorData(BaseModel):
    code: str
    message: str
    details: Any | None = None

    model_config = ConfigDict(extra="forbid")


class ApiErrorEnvelope(BaseModel):
    error: ApiErrorData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class MessageData(BaseModel):
    message: str

    model_config = ConfigDict(extra="forbid")


class MessageEnvelope(BaseModel):
    data: MessageData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")
