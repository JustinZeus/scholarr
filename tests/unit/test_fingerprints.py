from __future__ import annotations

from app.services.ingestion.fingerprints import (
    _dedupe_publication_candidates,
    canonical_title_for_dedup,
    fuzzy_titles_match,
    normalize_title,
)
from app.services.scholar.parser import PublicationCandidate


def _candidate(
    title: str,
    *,
    cluster_id: str | None = None,
    year: int | None = 2024,
    authors_text: str | None = "Smith, J",
    venue_text: str | None = "ICML",
) -> PublicationCandidate:
    return PublicationCandidate(
        title=title,
        title_url=None,
        cluster_id=cluster_id,
        year=year,
        citation_count=None,
        authors_text=authors_text,
        venue_text=venue_text,
        pdf_url=None,
    )


class TestFuzzyTitlesMatch:
    def test_identical_titles(self) -> None:
        assert fuzzy_titles_match("Deep Learning for NLP", "deep learning for nlp") is True

    def test_minor_word_difference(self) -> None:
        assert (
            fuzzy_titles_match(
                "A Survey on Deep Learning Methods for NLP",
                "Survey on Deep Learning Methods for NLP",
            )
            is True
        )

    def test_punctuation_difference(self) -> None:
        assert (
            fuzzy_titles_match(
                "Attention Is All You Need",
                "Attention Is All You Need.",
            )
            is True
        )

    def test_colon_vs_dash_subtitle(self) -> None:
        assert (
            fuzzy_titles_match(
                "Deep Learning: A Comprehensive Survey",
                "Deep Learning - A Comprehensive Survey",
            )
            is True
        )

    def test_completely_different_titles(self) -> None:
        assert (
            fuzzy_titles_match(
                "Deep Learning for NLP",
                "Climate Change Impact on Agriculture",
            )
            is False
        )

    def test_short_title_no_false_positive(self) -> None:
        assert fuzzy_titles_match("On Trees", "On Forests") is False

    def test_empty_title(self) -> None:
        assert fuzzy_titles_match("", "Deep Learning") is False

    def test_custom_threshold(self) -> None:
        # Lower threshold catches more distant matches
        assert (
            fuzzy_titles_match(
                "A Survey on Deep Learning",
                "Survey on Machine Learning Approaches",
                threshold=0.3,
            )
            is True
        )
        # Default threshold rejects them
        assert (
            fuzzy_titles_match(
                "A Survey on Deep Learning",
                "Survey on Machine Learning Approaches",
            )
            is False
        )


class TestDedupePublicationCandidates:
    def test_exact_duplicates_by_cluster_id(self) -> None:
        pubs = [
            _candidate("Title A", cluster_id="c1"),
            _candidate("Title A Copy", cluster_id="c1"),
        ]
        result = _dedupe_publication_candidates(pubs)
        assert len(result) == 1
        assert result[0].title == "Title A"

    def test_fuzzy_duplicates_without_cluster_id(self) -> None:
        pubs = [
            _candidate("Attention Is All You Need"),
            _candidate("Attention Is All You Need."),
        ]
        result = _dedupe_publication_candidates(pubs)
        assert len(result) == 1

    def test_distinct_titles_preserved(self) -> None:
        pubs = [
            _candidate("Deep Learning for NLP"),
            _candidate("Reinforcement Learning for Robotics"),
        ]
        result = _dedupe_publication_candidates(pubs)
        assert len(result) == 2

    def test_fallback_aligned_with_db_fingerprint(self) -> None:
        """Same title/year/first_author/first_venue should deduplicate even with
        different full authors_text or venue_text."""
        pubs = [
            _candidate(
                "My Paper",
                authors_text="Smith, J; Jones, A",
                venue_text="International Conference on ML",
            ),
            _candidate(
                "My Paper",
                authors_text="Smith, J; Baker, B",
                venue_text="International Conference for ML",
            ),
        ]
        result = _dedupe_publication_candidates(pubs)
        # Both share first_author_last_name="smith" and first_venue_word="international"
        assert len(result) == 1

    def test_mixed_cluster_and_fuzzy(self) -> None:
        pubs = [
            _candidate("A Comprehensive Survey on Deep Learning Methods", cluster_id="c1"),
            _candidate("Comprehensive Survey on Deep Learning Methods"),  # fuzzy match (subtitle stripped)
            _candidate("Completely Different Study"),
        ]
        result = _dedupe_publication_candidates(pubs)
        assert len(result) == 2
        titles = [p.title for p in result]
        assert "A Comprehensive Survey on Deep Learning Methods" in titles
        assert "Completely Different Study" in titles

    def test_scholar_noise_variants_collapse_to_one(self) -> None:
        """The motivating case: three Scholar display variants of the Adam paper."""
        pubs = [
            _candidate(
                "Adam: A method for stochastic optimization, preprint (2014)",
                year=2014,
                venue_text="",
            ),
            _candidate(
                "Adam: A Method for Stochastic Optimization. arXiv, Jan 29, 2017. doi: 10.48550/arxiv.1412.6980",
                year=2017,
                venue_text="arXiv",
            ),
            _candidate(
                "Adam a method for stochastic optimization. Comput. Sci",
                year=2015,
                venue_text="Comput. Sci",
            ),
        ]
        result = _dedupe_publication_candidates(pubs)
        assert len(result) == 1
        assert result[0].title == pubs[0].title

    def test_distinct_papers_not_merged(self) -> None:
        """Papers with different core titles must not be collapsed."""
        pubs = [
            _candidate("Adam: A Method for Stochastic Optimization"),
            _candidate("SGD: Stochastic Gradient Descent Revisited"),
            _candidate("Attention Is All You Need"),
        ]
        result = _dedupe_publication_candidates(pubs)
        assert len(result) == 3

    def test_cross_page_dedup_via_seen_canonical(self) -> None:
        """seen_canonical threads state across two separate calls (simulating two pages)."""
        seen: set[str] = set()
        page1 = [_candidate("Adam: A Method for Stochastic Optimization")]
        page2 = [
            _candidate(
                "Adam: A method for stochastic optimization, preprint (2014)",
                year=2014,
            ),
            _candidate("An Entirely Different Paper"),
        ]

        result1 = _dedupe_publication_candidates(page1, seen_canonical=seen)
        result2 = _dedupe_publication_candidates(page2, seen_canonical=seen)

        assert len(result1) == 1
        # Noisy Adam variant from page 2 is suppressed; distinct paper survives
        assert len(result2) == 1
        assert result2[0].title == "An Entirely Different Paper"

    def test_first_seen_wins_in_noise_collapse(self) -> None:
        """First occurrence in page order is the kept candidate."""
        pubs = [
            _candidate("Adam: A Method for Stochastic Optimization", year=2015),
            _candidate("Adam: A method for stochastic optimization, preprint (2014)", year=2014),
        ]
        result = _dedupe_publication_candidates(pubs)
        assert len(result) == 1
        assert result[0].year == 2015  # first wins


class TestCanonicalTitleForDedup:
    def test_strips_doi_suffix(self) -> None:
        title = "Adam: A Method for Stochastic Optimization. doi: 10.48550/arxiv.1412.6980"
        assert canonical_title_for_dedup(title) == normalize_title("Adam: A Method for Stochastic Optimization")

    def test_strips_arxiv_metadata_suffix(self) -> None:
        title = "Adam: A Method for Stochastic Optimization. arXiv, Jan 29, 2017"
        assert canonical_title_for_dedup(title) == normalize_title("Adam: A Method for Stochastic Optimization")

    def test_strips_preprint_parenthetical(self) -> None:
        title = "Adam: A method for stochastic optimization, preprint (2014)"
        assert canonical_title_for_dedup(title) == normalize_title("Adam: A method for stochastic optimization")

    def test_strips_venue_sentence_suffix(self) -> None:
        title = "Adam a method for stochastic optimization. Comput. Sci"
        assert canonical_title_for_dedup(title) == normalize_title("Adam a method for stochastic optimization")

    def test_strips_trailing_year_in_parens(self) -> None:
        assert canonical_title_for_dedup("Deep Learning (2018)") == normalize_title("Deep Learning")

    def test_preserves_clean_title(self) -> None:
        title = "Attention Is All You Need"
        assert canonical_title_for_dedup(title) == normalize_title(title)

    def test_adam_variants_produce_identical_canonical(self) -> None:
        variants = [
            "Adam: A method for stochastic optimization, preprint (2014)",
            "Adam: A Method for Stochastic Optimization. arXiv, Jan 29, 2017. doi: 10.48550/arxiv.1412.6980",
            "Adam a method for stochastic optimization. Comput. Sci",
        ]
        canonicals = [canonical_title_for_dedup(v) for v in variants]
        assert len(set(canonicals)) == 1, f"Expected one canonical, got: {canonicals}"

    def test_strips_mojibake_conference_suffix(self) -> None:
        noisy = "â€ œAdam: A method for stochastic optimization, â€ 3rd Int. Conf. Learn. Represent. ICLR 2015-Conf"
        clean = "Adam: A method for stochastic optimization"
        assert canonical_title_for_dedup(noisy) == normalize_title(clean)

    def test_preserves_clean_subtitle_not_venue_metadata(self) -> None:
        title = "Vision-Language Models - A Survey"
        assert canonical_title_for_dedup(title) == normalize_title(title)

    def test_strips_leading_author_fragment_before_core_title(self) -> None:
        noisy = "and Ba.J.:Adam: a method for stochastic optimization"
        clean = "Adam: a method for stochastic optimization"
        assert canonical_title_for_dedup(noisy) == normalize_title(clean)

    def test_strips_leading_date_prefix(self) -> None:
        noisy = "January 7-9). Adam: A method for stochastic optimization"
        clean = "Adam: A method for stochastic optimization"
        assert canonical_title_for_dedup(noisy) == normalize_title(clean)

    def test_strips_trailing_publication_type(self) -> None:
        noisy = "Adam: A method for stochastic optimization. conference paper"
        clean = "Adam: A method for stochastic optimization"
        assert canonical_title_for_dedup(noisy) == normalize_title(clean)

    def test_strips_trailing_month_year_parenthetical(self) -> None:
        noisy = "Adam: A method for stochastic optimization (Jan 2017)"
        clean = "Adam: A method for stochastic optimization"
        assert canonical_title_for_dedup(noisy) == normalize_title(clean)
