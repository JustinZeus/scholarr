from __future__ import annotations

import pytest

from app.services.ingestion.run_completion import apply_outcome_to_progress
from app.services.ingestion.types import RunProgress, ScholarProcessingOutcome


def _outcome(*, scholar_profile_id: int, outcome_label: str) -> ScholarProcessingOutcome:
    counters = {
        "success": (1, 0, 0),
        "partial": (1, 0, 1),
        "failed": (0, 1, 0),
    }
    succeeded, failed, partial = counters[outcome_label]
    return ScholarProcessingOutcome(
        result_entry={
            "scholar_profile_id": scholar_profile_id,
            "outcome": outcome_label,
            "state": "ok",
            "state_reason": "publications_extracted",
            "publication_count": 1,
        },
        succeeded_count_delta=succeeded,
        failed_count_delta=failed,
        partial_count_delta=partial,
        discovered_publication_count=1,
    )


def test_apply_outcome_to_progress_replaces_previous_scholar_outcome() -> None:
    progress = RunProgress()

    apply_outcome_to_progress(
        progress=progress,
        outcome=_outcome(scholar_profile_id=42, outcome_label="partial"),
    )
    apply_outcome_to_progress(
        progress=progress,
        outcome=_outcome(scholar_profile_id=42, outcome_label="success"),
    )

    assert len(progress.scholar_results) == 1
    assert progress.scholar_results[0]["outcome"] == "success"
    assert progress.succeeded_count == 1
    assert progress.failed_count == 0
    assert progress.partial_count == 0


def test_apply_outcome_to_progress_rejects_invalid_scholar_id() -> None:
    progress = RunProgress()
    invalid = ScholarProcessingOutcome(
        result_entry={"scholar_profile_id": 0, "outcome": "success"},
        succeeded_count_delta=1,
        failed_count_delta=0,
        partial_count_delta=0,
        discovered_publication_count=0,
    )

    with pytest.raises(RuntimeError, match="missing valid scholar_profile_id"):
        apply_outcome_to_progress(progress=progress, outcome=invalid)
