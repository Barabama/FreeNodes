"""Tests for the httpx download path: status handling and empty bodies.

All HTTP is mocked; no network access.

Run: pytest tests/test_crawler.py -v
"""
import pytest

pytestmark = pytest.mark.asyncio

from src.crawler import DownloadError, download_file


class FakeResponse:
    def __init__(self, status_code: int, text: str = "",
                 headers: dict | None = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class FakeClient:
    """Minimal async context manager standing in for httpx.AsyncClient."""

    def __init__(self, response: FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url: str):
        return self._response


def patch_client(monkeypatch, response: FakeResponse) -> None:
    monkeypatch.setattr(
        "src.crawler.httpx.AsyncClient",
        lambda *args, **kwargs: FakeClient(response),
    )


# ═══════════════════════════════════════════════════════════════
# download_file
# ═══════════════════════════════════════════════════════════════

class TestDownloadFile:

    async def test_200_with_body_returns_text(self, monkeypatch):
        patch_client(monkeypatch, FakeResponse(200, "vless://node"))
        assert await download_file("http://x.com/a.txt") == "vless://node"

    async def test_200_with_empty_body_returns_empty_string(self, monkeypatch):
        """A 200 with a 0-byte payload is a success, not an exception."""
        patch_client(monkeypatch, FakeResponse(200, ""))
        assert await download_file("http://x.com/empty.txt") == ""

    async def test_204_is_success(self, monkeypatch):
        patch_client(monkeypatch, FakeResponse(204, ""))
        assert await download_file("http://x.com/a.txt") == ""

    async def test_404_raises_with_status(self, monkeypatch):
        patch_client(monkeypatch, FakeResponse(404))
        with pytest.raises(DownloadError) as exc_info:
            await download_file("http://x.com/missing.txt")
        assert exc_info.value.status_code == 404
        assert str(exc_info.value) == "HTTP 404"
        assert exc_info.value.retry_after is None

    async def test_429_exposes_retry_after(self, monkeypatch):
        patch_client(monkeypatch, FakeResponse(429, headers={"Retry-After": "17"}))
        with pytest.raises(DownloadError) as exc_info:
            await download_file("http://x.com/a.txt")
        assert exc_info.value.status_code == 429
        assert exc_info.value.retry_after == "17"

    async def test_503_exposes_http_date_retry_after(self, monkeypatch):
        header = "Wed, 21 Oct 2015 07:28:00 GMT"
        patch_client(monkeypatch, FakeResponse(503, headers={"Retry-After": header}))
        with pytest.raises(DownloadError) as exc_info:
            await download_file("http://x.com/a.txt")
        assert exc_info.value.status_code == 503
        assert exc_info.value.retry_after == header

    async def test_4xx_without_retry_after(self, monkeypatch):
        patch_client(monkeypatch, FakeResponse(403))
        with pytest.raises(DownloadError) as exc_info:
            await download_file("http://x.com/a.txt")
        assert exc_info.value.status_code == 403
        assert exc_info.value.retry_after is None

    async def test_5xx_is_an_error(self, monkeypatch):
        patch_client(monkeypatch, FakeResponse(500))
        with pytest.raises(DownloadError) as exc_info:
            await download_file("http://x.com/a.txt")
        assert exc_info.value.status_code == 500
