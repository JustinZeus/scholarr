from app.services.openalex.types import OpenAlexWork


def test_parse_openalex_work_from_api_dict() -> None:
    raw_api_response = {
        "id": "https://openalex.org/W2741809807",
        "doi": "https://doi.org/10.1038/s41586-020-0315-z",
        "title": "Machine learning and the physical sciences",
        "publication_year": 2019,
        "cited_by_count": 1420,
        "ids": {
            "openalex": "https://openalex.org/W2741809807",
            "doi": "https://doi.org/10.1038/s41586-020-0315-z",
            "mag": "2741809807",
            "pmid": "https://pubmed.ncbi.nlm.nih.gov/32040050",
            "pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7325852",
        },
        "open_access": {"is_oa": True, "oa_url": "https://example.com/pdf"},
        "authorships": [
            {
                "author_position": "first",
                "author": {"id": "https://openalex.org/A1969205032", "display_name": "Giuseppe Carleo"},
            },
            {
                "author_position": "middle",
                "author": {"id": "https://openalex.org/A4356881717", "display_name": "Ignacio Cirac"},
            },
        ],
    }

    work = OpenAlexWork.from_api_dict(raw_api_response)

    assert work.openalex_id == "https://openalex.org/W2741809807"
    assert work.title == "Machine learning and the physical sciences"
    assert work.doi == "10.1038/s41586-020-0315-z"
    assert work.pmid == "32040050"
    assert work.pmcid == "PMC7325852"
    assert work.publication_year == 2019
    assert work.cited_by_count == 1420
    assert work.is_oa is True
    assert work.oa_url == "https://example.com/pdf"
    assert len(work.authors) == 2
    assert work.authors[0].display_name == "Giuseppe Carleo"
    assert work.authors[1].display_name == "Ignacio Cirac"


def test_parse_openalex_work_empty() -> None:
    work = OpenAlexWork.from_api_dict({"id": "W123"})
    assert work.openalex_id == "W123"
    assert work.doi is None
    assert work.pmid is None
    assert work.title is None
    assert work.publication_year is None
    assert work.cited_by_count == 0
    assert work.is_oa is False
    assert len(work.authors) == 0
