import logging
import re

from rapidfuzz import fuzz

from app.services.domains.openalex.types import OpenAlexWork

logger = logging.getLogger(__name__)

# A minimum similarity score out of 100 for a title to be considered a match candidate.
TITLE_MATCH_THRESHOLD = 90.0
# The margin within the top score where a secondary tiebreaker (author/year) is necessary.
TIEBREAKER_MARGIN = 5.0


def _clean_string(s: str | None) -> str:
    if not s:
        return ""
    # Strip non-alphanumeric (keep spaces), lowercase, and collapse whitespace
    cleaned = re.sub(r"[^a-z0-9\s]", " ", s.lower())
    return " ".join(cleaned.split())


def _author_overlap_score(target_authors: str | None, candidate_authors: list[str]) -> bool:
    if not target_authors or not candidate_authors:
        return False

    target_clean = _clean_string(target_authors)
    if not target_clean:
        return False

    for candidate in candidate_authors:
        cand_clean = _clean_string(candidate)
        if cand_clean and (cand_clean in target_clean or target_clean in cand_clean):
            return True
        # Alternatively check rapidfuzz token_set_ratio
        if cand_clean and fuzz.token_set_ratio(target_clean, cand_clean) > 80:
            return True

    return False


def find_best_match(
    target_title: str,
    target_year: int | None,
    target_authors: str | None,
    candidates: list[OpenAlexWork],
) -> OpenAlexWork | None:
    """
    Finds the best matching OpenAlexWork from a list of candidates, prioritizing title similarity (>90%)
    with year and author overlap as tiebreakers for close candidates.
    """
    if not target_title or not candidates:
        return None

    clean_target = _clean_string(target_title)
    if not clean_target:
        return None

    scored_candidates: list[tuple[float, OpenAlexWork]] = []

    for cand in candidates:
        if not cand.title:
            continue

        clean_cand = _clean_string(cand.title)

        # Primary sort: string similarity ratio
        score = fuzz.ratio(clean_target, clean_cand)

        if score >= TITLE_MATCH_THRESHOLD:
            scored_candidates.append((score, cand))

    if not scored_candidates:
        return None

    # Sort descending by score
    scored_candidates.sort(key=lambda x: x[0], reverse=True)

    best_score = scored_candidates[0][0]

    # Extract all candidates within the tiebreaker margin
    top_scored_candidates = [
        (score, cand) for score, cand in scored_candidates if best_score - score <= TIEBREAKER_MARGIN
    ]

    if len(top_scored_candidates) == 1:
        return top_scored_candidates[0][1]

    # We have a tie or near-tie. Use year and author overlap to break the tie.
    # Score candidates: +1 for year match (within 1 year), +1 for author overlap
    tiebreaker_scores: list[tuple[int, float, OpenAlexWork]] = []

    for original_score, cand in top_scored_candidates:
        tb_score = 0
        if target_year is not None and cand.publication_year is not None and abs(target_year - cand.publication_year) <= 1:
                tb_score += 1

        candidate_author_names = [a.display_name for a in cand.authors if a.display_name]
        if _author_overlap_score(target_authors, candidate_author_names):
            tb_score += 1

        tiebreaker_scores.append((tb_score, original_score, cand))

    tiebreaker_scores.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return tiebreaker_scores[0][2]
