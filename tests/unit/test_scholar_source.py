import pytest

from app.services.scholar import rate_limit as scholar_rate_limit
from app.services.scholar.source import FetchResult, LiveScholarSource, _build_profile_url
from app.settings import settings


def _request_header(request, name: str) -> str | None:
    headers = {key.lower(): value for key, value in request.header_items()}
    return headers.get(name.lower())


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


def test_http_error_reason_prefers_sorry_challenge_marker() -> None:
    reason = LiveScholarSource._http_error_reason(
        status_code=429,
        final_url="https://www.google.com/sorry/index?continue=example",
        body="",
    )
    assert reason == "blocked_google_sorry_challenge"


def test_http_error_reason_falls_back_to_http_429_rate_limit() -> None:
    reason = LiveScholarSource._http_error_reason(
        status_code=429,
        final_url="https://scholar.google.com/citations?hl=en&user=abc",
        body="Too Many Requests",
    )
    assert reason == "blocked_http_429_rate_limited"


def test_build_request_uses_stable_user_agent_by_default() -> None:
    previous_user_agent = settings.scholar_http_user_agent
    previous_rotate = settings.scholar_http_rotate_user_agent
    previous_cookie = settings.scholar_http_cookie
    previous_accept_language = settings.scholar_http_accept_language
    object.__setattr__(settings, "scholar_http_user_agent", "")
    object.__setattr__(settings, "scholar_http_rotate_user_agent", False)
    object.__setattr__(settings, "scholar_http_cookie", "")
    object.__setattr__(settings, "scholar_http_accept_language", "en-US,en;q=0.9")
    try:
        source = LiveScholarSource(user_agents=["UA-A", "UA-B"])
        request_one = source._build_request("https://example.test/one")
        request_two = source._build_request("https://example.test/two")
        assert _request_header(request_one, "User-Agent") == _request_header(request_two, "User-Agent")
        assert _request_header(request_one, "Connection") is None
    finally:
        object.__setattr__(settings, "scholar_http_user_agent", previous_user_agent)
        object.__setattr__(settings, "scholar_http_rotate_user_agent", previous_rotate)
        object.__setattr__(settings, "scholar_http_cookie", previous_cookie)
        object.__setattr__(settings, "scholar_http_accept_language", previous_accept_language)


def test_build_request_rotates_user_agent_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    previous_user_agent = settings.scholar_http_user_agent
    previous_rotate = settings.scholar_http_rotate_user_agent
    object.__setattr__(settings, "scholar_http_user_agent", "")
    object.__setattr__(settings, "scholar_http_rotate_user_agent", True)
    choices = iter(["UA-STABLE", "UA-1", "UA-2"])
    monkeypatch.setattr("app.services.scholar.source.random.choice", lambda _values: next(choices))
    try:
        source = LiveScholarSource(user_agents=["UA-A", "UA-B"])
        request_one = source._build_request("https://example.test/one")
        request_two = source._build_request("https://example.test/two")
        assert _request_header(request_one, "User-Agent") == "UA-1"
        assert _request_header(request_two, "User-Agent") == "UA-2"
    finally:
        object.__setattr__(settings, "scholar_http_user_agent", previous_user_agent)
        object.__setattr__(settings, "scholar_http_rotate_user_agent", previous_rotate)


def test_build_request_includes_cookie_when_configured() -> None:
    previous_cookie = settings.scholar_http_cookie
    object.__setattr__(settings, "scholar_http_cookie", "SID=abc123")
    try:
        source = LiveScholarSource(user_agents=["UA-A"])
        request = source._build_request("https://example.test/one")
        assert _request_header(request, "Cookie") == "SID=abc123"
    finally:
        object.__setattr__(settings, "scholar_http_cookie", previous_cookie)
