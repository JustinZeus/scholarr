from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.domains.publications import pdf_resolution_pipeline as pipeline
from app.services.domains.publication_identifiers.types import DisplayIdentifier
from app.services.domains.unpaywall.application import OaResolutionOutcome


def _row(*, display_identifier: DisplayIdentifier | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        publication_id=1,
        scholar_profile_id=1,
        scholar_label="Ada Lovelace",
        title="A paper",
        year=2024,
        citation_count=0,
        venue_text=None,
        pub_url="https://scholar.google.com/citations?view_op=view_citation&citation_for_view=abc:xyz",
        display_identifier=display_identifier,
        pdf_url=None,
        is_read=False,
        is_favorite=False,
        first_seen_at=datetime(2026, 2, 22, 12, 0, tzinfo=timezone.utc),
        is_new_in_latest_run=True,
    )


def _api_outcome(*, pdf_url: str | None, source: str = "unpaywall") -> OaResolutionOutcome | None:
    if not pdf_url:
        return None
    return OaResolutionOutcome(
        publication_id=1,
        doi="10.1000/example",
        pdf_url=pdf_url,
        failure_reason=None if pdf_url else "no_pdf_found",
        source=source,
        used_crossref=False,
    )


def _oa_fallback_outcome(*, pdf_url: str | None, source: str = "unpaywall") -> OaResolutionOutcome:
    return OaResolutionOutcome(
        publication_id=1,
        doi="10.1000/example",
        pdf_url=pdf_url,
        failure_reason=None if pdf_url else "no_pdf_found",
        source=source,
        used_crossref=False,
    )


@pytest.mark.asyncio
async def test_pipeline_prefers_openalex_before_arxiv(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_openalex(row, request_email: str | None = None, openalex_api_key: str | None = None):
        return _api_outcome(pdf_url="https://oa.example.org/found.pdf", source="openalex")

    async def _fail_arxiv(row):
        raise AssertionError(f"arXiv should not run when OpenAlex candidate exists.")

    monkeypatch.setattr(pipeline, "_openalex_outcome", _fake_openalex)
    monkeypatch.setattr(pipeline, "_arxiv_outcome", _fail_arxiv)

    result = await pipeline.resolve_publication_pdf_outcome_for_row(row=_row(), request_email="user@example.com")

    assert result.outcome is not None
    assert result.outcome.pdf_url == "https://oa.example.org/found.pdf"
    assert result.outcome.source == "openalex"


@pytest.mark.asyncio
async def test_pipeline_uses_arxiv_after_openalex_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_openalex(row, request_email: str | None = None, openalex_api_key: str | None = None):
        return None

    async def _fake_arxiv(row, request_email: str | None = None):
        return _api_outcome(pdf_url="https://arxiv.org/pdf/1234.5678.pdf", source="arxiv")

    async def _fail_oa(*, row, request_email):
        raise AssertionError("Unpaywall should not run when arXiv returns PDF.")

    monkeypatch.setattr(pipeline, "_openalex_outcome", _fake_openalex)
    monkeypatch.setattr(pipeline, "_arxiv_outcome", _fake_arxiv)
    monkeypatch.setattr(pipeline, "_oa_outcome", _fail_oa)

    result = await pipeline.resolve_publication_pdf_outcome_for_row(row=_row(), request_email="user@example.com")

    assert result.outcome is not None
    assert result.outcome.pdf_url == "https://arxiv.org/pdf/1234.5678.pdf"
    assert result.outcome.source == "arxiv"


@pytest.mark.asyncio
async def test_pipeline_uses_unpaywall_after_arxiv_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_openalex(row, request_email: str | None = None, openalex_api_key: str | None = None):
        return None

    async def _fake_arxiv(row, request_email: str | None = None):
        return None

    async def _fake_oa(*, row, request_email):
        assert request_email == "user@example.com"
        return _oa_fallback_outcome(pdf_url="https://example.org/fallback.pdf", source="unpaywall")

    monkeypatch.setattr(pipeline, "_openalex_outcome", _fake_openalex)
    monkeypatch.setattr(pipeline, "_arxiv_outcome", _fake_arxiv)
    monkeypatch.setattr(pipeline, "_oa_outcome", _fake_oa)

    result = await pipeline.resolve_publication_pdf_outcome_for_row(row=_row(), request_email="user@example.com")

    assert result.outcome is not None
    assert result.outcome.pdf_url == "https://example.org/fallback.pdf"
    assert result.outcome.source == "unpaywall"
