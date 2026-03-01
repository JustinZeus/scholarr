from app.services.openalex.matching import find_best_match
from app.services.openalex.types import OpenAlexWork


def test_find_best_match_exact_title():
    cand1 = OpenAlexWork.from_api_dict({"id": "W1", "title": "Exact Title of the Paper"})
    cand2 = OpenAlexWork.from_api_dict({"id": "W2", "title": "Totally Different Paper"})

    match = find_best_match("Exact Title of the Paper", 2020, "Author A", [cand1, cand2])
    assert match is not None
    assert match.openalex_id == "W1"


def test_find_best_match_fuzzy_title():
    # Only differences are punctuation or minor phrasing (e.g., matching a preprint title vs published)
    cand1 = OpenAlexWork.from_api_dict({"id": "W1", "title": "Fuzzier Title: A Study on OpenAlex"})
    cand2 = OpenAlexWork.from_api_dict({"id": "W2", "title": "Some completely unrelated work"})

    match = find_best_match("Fuzzier Title A Study on OpenAlex", 2021, "Author B", [cand1, cand2])
    assert match is not None
    assert match.openalex_id == "W1"


def test_find_best_match_rejects_low_score():
    cand1 = OpenAlexWork.from_api_dict({"id": "W1", "title": "Cats in hats"})

    match = find_best_match("Dogs with logs", 2020, "Author A", [cand1])
    assert match is None


def test_find_best_match_year_tiebreaker():
    # Both titles are very similar, one has exact year.
    cand1 = OpenAlexWork.from_api_dict({"id": "W1", "title": "The exact same title", "publication_year": 2018})
    cand2 = OpenAlexWork.from_api_dict({"id": "W2", "title": "The exact same title", "publication_year": 2020})

    match = find_best_match("The exact same title", 2020, "Author A", [cand1, cand2])
    assert match is not None
    assert match.openalex_id == "W2"


def test_find_best_match_author_tiebreaker():
    # Titles and years match exactly. Author overlap decides it.
    cand1 = OpenAlexWork.from_api_dict(
        {
            "id": "W1",
            "title": "A popular title",
            "publication_year": 2020,
            "authorships": [{"author": {"display_name": "Smith, J"}}],
        }
    )
    cand2 = OpenAlexWork.from_api_dict(
        {
            "id": "W2",
            "title": "A popular title",
            "publication_year": 2020,
            "authorships": [{"author": {"display_name": "Doe, J"}}],
        }
    )

    # Target authors contains "Doe"
    match = find_best_match("A popular title", 2020, "A Einstein, J Doe", [cand1, cand2])
    assert match is not None
    assert match.openalex_id == "W2"
