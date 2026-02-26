from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CrawlRun, Publication, RunStatus, RunTriggerType, ScholarProfile, ScholarPublication
from app.services.domains.ingestion.application import ScholarIngestionService
from app.services.domains.openalex.types import OpenAlexWork
from tests.integration.helpers import insert_user


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deferred_enrichment_sweeps_previous_runs(db_session: AsyncSession) -> None:
    # 1. Setup: Create user and scholar
    user_id = await insert_user(db_session, email="test@example.com", password="password123")

    scholar = ScholarProfile(
        user_id=user_id,
        scholar_id="SaiiI5MAAAAJ",
        display_name="Test Scholar",
        is_enabled=True,
    )
    db_session.add(scholar)
    await db_session.flush()

    # 2. Simulate a previous FAILED run that left an un-enriched publication
    failed_run = CrawlRun(
        user_id=user_id,
        status=RunStatus.FAILED,
        trigger_type=RunTriggerType.MANUAL,
        start_dt=datetime.now(UTC),
    )
    db_session.add(failed_run)
    await db_session.flush()

    pub = Publication(
        title_raw="A fast quantum mechanical algorithm for database search",
        title_normalized="a fast quantum mechanical algorithm for database search",
        fingerprint_sha256="dummy_fingerprint_for_test",
        author_text="LK Grover",
        openalex_enriched=False,
    )
    db_session.add(pub)
    await db_session.flush()

    link = ScholarPublication(
        scholar_profile_id=scholar.id,
        publication_id=pub.id,
        first_seen_run_id=failed_run.id,
    )
    db_session.add(link)
    await db_session.commit()

    # 3. Create a NEW run
    new_run = CrawlRun(
        user_id=user_id,
        status=RunStatus.RUNNING,
        trigger_type=RunTriggerType.MANUAL,
        start_dt=datetime.now(UTC),
    )
    db_session.add(new_run)
    await db_session.commit()

    # 4. Mock OpenAlex client to return enrichment data
    mock_work = OpenAlexWork(
        openalex_id="W1234567",
        doi="10.1145/237814.237866",
        pmid=None,
        pmcid=None,
        title="A fast quantum mechanical algorithm for database search",
        publication_year=1996,
        cited_by_count=1000,
        is_oa=True,
        oa_url="http://example.com/grover.pdf",
    )

    mock_source = MagicMock()
    service = ScholarIngestionService(source=mock_source)

    # We patch the client at its source, and also mock arXiv to avoid real HTTP calls
    with (
        patch("app.services.domains.openalex.client.OpenAlexClient") as MockClient,
        patch(
            "app.services.domains.arxiv.application.discover_arxiv_id_for_publication", new=AsyncMock(return_value=None)
        ),
    ):
        mock_instance = MockClient.return_value
        mock_instance.get_works_by_filter = AsyncMock(return_value=[mock_work])

        # 5. Execute the enrichment pass for the NEW run
        await service._enrich_pending_publications(db_session, run_id=new_run.id)
        await db_session.commit()

    # 6. Verification: The publication from the FAILED run should now be enriched
    await db_session.refresh(pub)
    assert pub.openalex_enriched is True
    assert pub.citation_count == 1000
    assert pub.pdf_url == "http://example.com/grover.pdf"

    # Double check it was indeed processed
    stmt = select(Publication).where(Publication.id == pub.id)
    result = await db_session.execute(stmt)
    enriched_pub = result.scalar_one()
    assert enriched_pub.openalex_enriched is True
