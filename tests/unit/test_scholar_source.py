import pytest

from app.services.domains.scholar import rate_limit as scholar_rate_limit
from app.services.domains.scholar.source import FetchResult, LiveScholarSource, _build_profile_url


def test_build_profile_url_includes_pagesize_for_initial_page() -> None:
    url = _build_profile_url(
        scholar_id="abcDEF123456",
        cstart=0,
        pagesize=100,
    )

    assert "user=abcDEF123456" in url
    assert "pagesize=100" in url
    assert "cstart=" not in url


@pytest.mark.asyncio
async def test_live_scholar_source_applies_global_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_interval: list[float] = []

    async def _fake_wait_for_scholar_slot(*, min_interval_seconds: float) -> None:
        captured_interval.append(min_interval_seconds)

    monkeypatch.setattr(
        scholar_rate_limit,
        "wait_for_scholar_slot",
        _fake_wait_for_scholar_slot,
    )

    expected_result = FetchResult(
        requested_url="https://example.test/scholar",
        status_code=200,
        final_url="https://example.test/scholar",
        body="ok",
        error=None,
    )

    source = LiveScholarSource(min_interval_seconds=7.0)
    monkeypatch.setattr(source, "_fetch_sync", lambda _url: expected_result)

    result = await source.fetch_profile_page_html(
        "abcDEF123456",
        cstart=0,
        pagesize=100,
    )

    assert result == expected_result
    assert captured_interval == [7.0]
