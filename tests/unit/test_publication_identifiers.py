from __future__ import annotations

from app.services.domains.publication_identifiers import application as identifier_service


def test_derive_display_identifier_prefers_doi_over_arxiv() -> None:
    display = identifier_service.derive_display_identifier_from_values(
        doi="10.1000/example",
        pub_url="https://arxiv.org/abs/1504.08025",
        pdf_url=None,
    )
    assert display is not None
    assert display.kind == "doi"
    assert display.value == "10.1000/example"
    assert display.url == "https://doi.org/10.1000/example"


def test_derive_display_identifier_uses_arxiv_when_doi_missing() -> None:
    display = identifier_service.derive_display_identifier_from_values(
        doi=None,
        pub_url="https://arxiv.org/pdf/1504.08025v2",
        pdf_url=None,
    )
    assert display is not None
    assert display.kind == "arxiv"
    assert display.value == "1504.08025v2"
    assert display.label == "arXiv: 1504.08025v2"


def test_derive_display_identifier_uses_pmcid_when_present() -> None:
    display = identifier_service.derive_display_identifier_from_values(
        doi=None,
        pub_url=None,
        pdf_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC2175868/pdf/file.pdf",
    )
    assert display is not None
    assert display.kind == "pmcid"
    assert display.value == "PMC2175868"


def test_normalize_arxiv_id_handles_urls() -> None:
    from app.services.domains.publication_identifiers.normalize import normalize_arxiv_id
    
    assert normalize_arxiv_id("https://arxiv.org/abs/1504.08025") == "1504.08025"
    assert normalize_arxiv_id("http://arxiv.org/pdf/1504.08025v2.pdf") == "1504.08025v2"
    assert normalize_arxiv_id("https://arxiv.org/html/1504.08025v2") == "1504.08025v2"
    # Modern arxiv format
    assert normalize_arxiv_id("https://arxiv.org/abs/2012.00001") == "2012.00001"
    # Old arxiv format
    assert normalize_arxiv_id("https://arxiv.org/abs/math/9901123") == "math/9901123"


def test_normalize_arxiv_id_handles_raw_text() -> None:
    from app.services.domains.publication_identifiers.normalize import normalize_arxiv_id
    
    assert normalize_arxiv_id("arXiv:1504.08025") == "1504.08025"
    assert normalize_arxiv_id("arxiv: 1504.08025v1") == "1504.08025v1"
    assert normalize_arxiv_id("Preprint at arXiv:math/9901123v2") == "math/9901123v2"
    assert normalize_arxiv_id("Not an arxiv: 123") is None


def test_normalize_pmcid_handles_urls_and_text() -> None:
    from app.services.domains.publication_identifiers.normalize import normalize_pmcid
    
    assert normalize_pmcid("https://pmc.ncbi.nlm.nih.gov/articles/PMC2175868/") == "PMC2175868"
    assert normalize_pmcid("http://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567") == "PMC1234567"
    assert normalize_pmcid("PMCID: PMC1234567") == "PMC1234567"
    assert normalize_pmcid("pmc1234567") == "PMC1234567"
    assert normalize_pmcid("Not a PMCID 1234567") is None


def test_normalize_pmid_handles_urls() -> None:
    from app.services.domains.publication_identifiers.normalize import normalize_pmid
    
    assert normalize_pmid("https://pubmed.ncbi.nlm.nih.gov/12345678/") == "12345678"
    assert normalize_pmid("http://pubmed.ncbi.nlm.nih.gov/12345678") == "12345678"
    assert normalize_pmid("https://pubmed.ncbi.nlm.nih.gov/not-a-pmid/") is None


import pytest
from app.services.domains.arxiv import application as arxiv_service
from app.services.domains.publications.types import UnreadPublicationItem

@pytest.mark.asyncio
async def test_discover_arxiv_id_returns_none_if_no_title() -> None:
    item = UnreadPublicationItem(
        publication_id=1,
        scholar_profile_id=1,
        scholar_label="First Last",
        title="",
        year=2023,
        citation_count=0,
        venue_text=None,
        pub_url=None,
        pdf_url=None,
    )
    result = await arxiv_service.discover_arxiv_id_for_publication(item=item)
    assert result is None


@pytest.mark.asyncio
async def test_build_arxiv_query() -> None:
    query = arxiv_service._build_arxiv_query("Super AI Model", "Smith")
    assert query == 'ti:"Super AI Model" AND au:"Smith"'

    query2 = arxiv_service._build_arxiv_query("Only Title Here", None)
    assert query2 == 'ti:"Only Title Here"'
