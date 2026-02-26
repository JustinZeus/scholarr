from __future__ import annotations

from datetime import datetime, timezone

from app.services.domains.arxiv.guards import arxiv_skip_reason_for_item
from app.services.domains.publication_identifiers.types import DisplayIdentifier
from app.services.domains.publications.types import PublicationListItem


def _item(
    *,
    title: str,
    pub_url: str | None = None,
    pdf_url: str | None = None,
    display_identifier: DisplayIdentifier | None = None,
) -> PublicationListItem:
    return PublicationListItem(
        publication_id=1,
        scholar_profile_id=1,
        scholar_label="Ada Lovelace",
        title=title,
        year=2024,
        citation_count=0,
        venue_text=None,
        pub_url=pub_url,
        pdf_url=pdf_url,
        is_read=False,
        first_seen_at=datetime.now(timezone.utc),
        is_new_in_latest_run=True,
        display_identifier=display_identifier,
    )


def test_arxiv_skip_reason_for_strong_doi_evidence() -> None:
    item = _item(
        title="A Robust and Reproducible Deep Learning Benchmark",
        display_identifier=DisplayIdentifier(
            kind="doi",
            value="10.1000/example",
            label="DOI: 10.1000/example",
            url="https://doi.org/10.1000/example",
            confidence_score=1.0,
        ),
    )
    assert arxiv_skip_reason_for_item(item=item) == "strong_doi_present"


def test_arxiv_skip_reason_for_existing_arxiv_link() -> None:
    item = _item(
        title="A Robust and Reproducible Deep Learning Benchmark",
        pub_url="https://arxiv.org/abs/2501.00001",
    )
    assert arxiv_skip_reason_for_item(item=item) == "arxiv_identifier_present"


def test_arxiv_skip_reason_for_low_quality_title() -> None:
    item = _item(title="AI 2024")
    assert arxiv_skip_reason_for_item(item=item) == "title_quality_below_threshold"


def test_arxiv_skip_reason_none_for_eligible_item() -> None:
    item = _item(title="Reliable Graph Neural Network Benchmarking Across Multiple Datasets")
    assert arxiv_skip_reason_for_item(item=item) is None
