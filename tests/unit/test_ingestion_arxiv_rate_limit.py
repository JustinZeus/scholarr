from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.domains.arxiv.errors import ArxivRateLimitError
from app.services.domains.ingestion.application import ScholarIngestionService
from app.services.domains.publication_identifiers import application as identifier_service


@pytest.mark.asyncio
async def test_discover_identifiers_for_enrichment_disables_arxiv_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ScholarIngestionService(source=object())
    publication = SimpleNamespace(id=11, author_text="Ada Lovelace")
    calls = {"sync": 0}

    async def _raise_rate_limit(db_session, *, publication, scholar_label):
        _ = (db_session, publication, scholar_label)
        raise ArxivRateLimitError("arXiv rate limit hit (429) — stopping batch")

    async def _sync_fields(db_session, *, publication):
        _ = (db_session, publication)
        calls["sync"] += 1

    monkeypatch.setattr(
        identifier_service,
        "discover_and_sync_identifiers_for_publication",
        _raise_rate_limit,
    )
    monkeypatch.setattr(identifier_service, "sync_identifiers_for_publication_fields", _sync_fields)

    async def _publish_noop(*args, **kwargs) -> None:
        _ = (args, kwargs)

    monkeypatch.setattr(service, "_publish_identifier_update_event", _publish_noop)

    result = await service._discover_identifiers_for_enrichment(
        object(),
        publication=publication,
        run_id=321,
        allow_arxiv_lookup=True,
    )

    assert result is False
    assert calls["sync"] == 1
