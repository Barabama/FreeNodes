"""Tests for SiteProcessor: article selection, link extraction, download retry.

Run: pytest tests/test_site_processor.py -v
"""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

pytestmark = pytest.mark.asyncio

from src.site_processor import SiteProcessor, SiteResult
from src.config import SiteConfig, Config, CrawlConfig, LLMConfig, ProviderConfig
from src.crawler import Page, DownloadError
from src.llm_router import LLMRouter


# ── Fixtures ──

@pytest.fixture
def site_cfg():
    return SiteConfig(
        name="test-site",
        start_url="https://example.com/blog/",
        description="a test blog",
        link_pattern=None,
    )


@pytest.fixture
def config_with_llm():
    return Config(
        sites=[SiteConfig(name="test", start_url="http://x")],
        crawl=CrawlConfig(max_articles=3, timeout=30, concurrency=3),
        output={"dir": "nodes"},
        llm=LLMConfig(
            providers=[
                ProviderConfig(
                    name="mock", base_url="http://m/v1",
                    api_key_env="K", models=["m"], default_weight=100,
                ),
            ],
            task_routing={"default": {"mock": 100}},
        ),
    )


def make_page(url: str = "http://x", links: list | None = None,
              markdown: str = "", html: str = "", success: bool = True) -> Page:
    return Page(url=url, markdown=markdown, html=html,
                links=links or [], success=success)


# ═══════════════════════════════════════════════════════════════
# _derive_base
# ═══════════════════════════════════════════════════════════════

class TestDeriveBase:

    def test_simple_url(self):
        assert SiteProcessor._derive_base("https://example.com/page") == "https://example.com"

    def test_with_path(self):
        assert SiteProcessor._derive_base("https://blog.example.com/free-nodes/") == "https://blog.example.com"

    def test_http(self):
        assert SiteProcessor._derive_base("http://x.com") == "http://x.com"


# ═══════════════════════════════════════════════════════════════
# _extract_by_pattern
# ═══════════════════════════════════════════════════════════════

class TestExtractByPattern:

    def test_basic_extraction(self):
        html = '<a href="https://x.com/a.yaml">link</a><a href="https://x.com/b.txt">link</a>'
        result = SiteProcessor._extract_by_pattern(html, r'https://x\.com/[^"\'<\s]+')
        assert len(result) == 2
        assert "a.yaml" in result[0]
        assert "b.txt" in result[1]

    def test_skips_non_http(self):
        html = '<a href="javascript:void">x</a><p>https://x.com/n.yaml</p>'
        result = SiteProcessor._extract_by_pattern(html, r'https?://[^"\'<\s]+')
        assert len(result) == 1
        assert "n.yaml" in result[0]

    def test_cleans_trailing_punctuation(self):
        html = '<p>https://x.com/a.yaml).</p>'
        result = SiteProcessor._extract_by_pattern(html, r'https?://[^"\'<\s]+')
        assert result[0] == "https://x.com/a.yaml"

    def test_empty_html(self):
        assert SiteProcessor._extract_by_pattern("", r"https?://.+") == []

    def test_no_match(self):
        assert SiteProcessor._extract_by_pattern("<p>no links</p>", r"https?://.+") == []


# ═══════════════════════════════════════════════════════════════
# _parse_article_date
# ═══════════════════════════════════════════════════════════════

class TestParseArticleDate:

    def test_chinese_month_day(self):
        assert SiteProcessor._parse_article_date("6月18日更新", "") == "2026-06-18"

    def test_chinese_full_date(self):
        assert SiteProcessor._parse_article_date("2026年06月19日 更新", "") == "2026-06-19"

    def test_slash_date_in_text(self):
        assert SiteProcessor._parse_article_date("2026/6/19", "") == "2026-06-19"

    def test_hyphen_date_in_url(self):
        assert SiteProcessor._parse_article_date("", "/free-nodes/2026-6-18-post.htm") == "2026-06-18"

    def test_compact_date_in_url(self):
        assert SiteProcessor._parse_article_date("", "/post/20260619/") == "2026-06-19"

    def test_compact_date_in_url_with_filename(self):
        assert SiteProcessor._parse_article_date("", "/2026/06/20260619-title.html") == "2026-06-19"

    def test_no_date_returns_none(self):
        assert SiteProcessor._parse_article_date("Home page", "/") is None

    def test_prefers_title_over_url(self):
        assert SiteProcessor._parse_article_date("6月18日文章", "/post/20260619/") == "2026-06-18"
# ═══════════════════════════════════════════════════════════════

class TestPickArticles:

    def test_picks_by_date_from_title(self, site_cfg, config_with_llm):
        """Chinese date "6月18日" in title → sorted correctly."""
        processor = SiteProcessor(site_cfg, config_with_llm, None)
        blog = make_page(links=[
            {"href": "/post-1.htm", "text": "6月17日 | Some title"},
            {"href": "/post-2.htm", "text": "6月18日 | Another post"},
            {"href": "/post-3.htm", "text": "6月16日 | Older post"},
        ])
        articles = processor._pick_articles(blog)
        assert len(articles) == 3
        assert articles[0]["date"] == "2026-06-18"  # newest first
        assert articles[1]["date"] == "2026-06-17"
        assert articles[2]["date"] == "2026-06-16"

    def test_picks_by_date_from_url(self, site_cfg, config_with_llm):
        """URL path fallback when title has no date."""
        processor = SiteProcessor(site_cfg, config_with_llm, None)
        blog = make_page(links=[
            {"href": "/free-nodes/2026-6-15-post.htm", "text": "Some article"},
            {"href": "/free-nodes/2026-6-18-post.htm", "text": "Another article"},
        ])
        articles = processor._pick_articles(blog)
        assert len(articles) == 2
        assert articles[0]["date"] == "2026-06-18"

    def test_skips_non_article_links(self, site_cfg, config_with_llm):
        """Category, pagination, and root links are excluded."""
        processor = SiteProcessor(site_cfg, config_with_llm, None)
        blog = make_page(links=[
            {"href": "/free-nodes/", "text": "6月18日 | Home"},
            {"href": "/category/news/", "text": "6月18日 | Category"},
            {"href": "/page-2.htm", "text": "6月18日 | Page"},
            {"href": "/free-nodes/2026-6-18-post.htm", "text": "6月18日 | Real post"},
        ])
        articles = processor._pick_articles(blog)
        assert len(articles) == 1
        assert "2026-6-18-post" in articles[0]["url"]

    def test_resolves_relative_href(self, site_cfg, config_with_llm):
        """Relative href gets joined to base URL."""
        processor = SiteProcessor(site_cfg, config_with_llm, None)
        blog = make_page(links=[
            {"href": "/path/to/article.htm", "text": "6月18日 | Post"},
        ])
        articles = processor._pick_articles(blog)
        assert "https://example.com/path/to/article.htm" in articles[0]["url"]

    def test_respects_max_articles(self, site_cfg, config_with_llm):
        """Config.crawl.max_articles = 3 limits the result."""
        processor = SiteProcessor(site_cfg, config_with_llm, None)
        links = [{"href": f"/post-{i}.htm", "text": f"6月{18-i:02d}日 | Post"} for i in range(10)]
        blog = make_page(links=links)
        articles = processor._pick_articles(blog)
        assert len(articles) == 3

    def test_empty_blog_links(self, site_cfg, config_with_llm):
        processor = SiteProcessor(site_cfg, config_with_llm, None)
        blog = make_page(links=[])
        assert processor._pick_articles(blog) == []


# ═══════════════════════════════════════════════════════════════
# _extract_links (with mocked LLM)
# ═══════════════════════════════════════════════════════════════

class TestExtractLinks:

    async def test_rule_hit_returns_early(self, site_cfg, config_with_llm):
        """link_pattern matches → returns links, no LLM."""
        site_cfg.link_pattern = r"https://node\.example\.com/[^\s<>\"']+"
        html = '<p>https://node.example.com/0.yaml</p>'
        page = make_page(html=html, markdown="ignored")

        processor = SiteProcessor(site_cfg, config_with_llm, None)
        links, saved = await processor._extract_links(page)
        assert len(links) == 1
        assert saved is False

    async def test_rule_miss_then_llm_fallback(self, site_cfg, config_with_llm):
        """No pattern → LLM extracts links."""
        from src.llm_router import LLMRouter

        site_cfg.link_pattern = None
        html = '<p>https://x.com/a.yaml https://x.com/b.txt</p>'
        page = make_page(html=html, markdown="some markdown with a.yaml and b.txt")

        router = LLMRouter(config_with_llm, timeout_s=5)

        async def fake_ask(prompt, task_type="default", max_tokens=1024):
            return '{"txt": ["https://x.com/b.txt"], "yaml": ["https://x.com/a.yaml"]}'

        router.ask = fake_ask
        processor = SiteProcessor(site_cfg, config_with_llm, router)
        links, saved = await processor._extract_links(page)
        assert len(links) == 2
        assert "a.yaml" in links[0] or "a.yaml" in links[1]

    async def test_pattern_resets_after_5_failures(self, site_cfg, config_with_llm):
        """When pattern fails >=5 times, link_pattern gets reset to None."""
        site_cfg.link_pattern = r"https://nonexistent\.com/[^\s]+"
        site_cfg.failed_count = 5
        html = '<p>https://x.com/a.yaml</p>'
        page = make_page(html=html, markdown="test")

        from src.llm_router import LLMRouter
        router = LLMRouter(config_with_llm, timeout_s=5)
        async def fake_ask(p, task_type="default", max_tokens=1024):
            return '{"yaml":["https://x.com/a.yaml"]}'
        async def fake_gen(links, html):
            return None  # no pattern → don't overwrite link_pattern
        router.ask = fake_ask
        router.generate_pattern = fake_gen

        processor = SiteProcessor(site_cfg, config_with_llm, router)
        links, saved = await processor._extract_links(page)
        assert site_cfg.link_pattern is None, "pattern should reset after 5 failures"
        assert len(links) > 0

    async def test_pattern_self_heal(self, site_cfg, config_with_llm, monkeypatch):
        """LLM generates valid pattern → saved to config."""
        site_cfg.link_pattern = None
        html = '<p>https://x.com/a.yaml https://x.com/b.txt</p>'
        page = make_page(html=html, markdown="a.yaml b.txt")

        # verify_pattern is called as static — monkeypatch class
        monkeypatch.setattr(
            "src.site_processor.LLMRouter.verify_pattern",
            lambda p, l, h: True,
        )

        router = LLMRouter(config_with_llm, timeout_s=5)

        async def fake_ask(prompt, task_type="default", max_tokens=1024):
            return '{"txt":["https://x.com/b.txt"],"yaml":["https://x.com/a.yaml"]}'

        async def fake_gen(links, html):
            return r"https://x\.com/[a-z]+\."

        router.ask = fake_ask
        router.generate_pattern = fake_gen

        processor = SiteProcessor(site_cfg, config_with_llm, router)
        links, saved = await processor._extract_links(page)
        assert saved is True
        assert site_cfg.link_pattern is not None


# ═══════════════════════════════════════════════════════════════
# _download_retry
# ═══════════════════════════════════════════════════════════════

class TestDownloadRetry:

    async def test_retries_on_failure(self, monkeypatch):
        """Retries 3 times, returns (None, error) on total failure."""
        call_count = 0
        delays: list[float] = []

        async def fake_download(url):
            nonlocal call_count
            call_count += 1
            raise ConnectionError("timeout")

        async def fake_sleep(seconds):
            delays.append(seconds)

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        monkeypatch.setattr("src.site_processor.asyncio.sleep", fake_sleep)
        body, error = await SiteProcessor._download_retry("http://x.com/f.yaml")
        assert body is None
        assert error == "timeout"
        assert call_count == 3
        assert delays == [1.5, 1.5]

    async def test_succeeds_on_first_try(self, monkeypatch):
        async def fake_download(url):
            return "content ok"

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        body, error = await SiteProcessor._download_retry("http://x.com/f.txt")
        assert body == "content ok"
        assert error is None

    async def test_empty_body_is_returned_not_retried(self, monkeypatch):
        """A 200 with a 0-byte payload is a success, not a failure."""
        call_count = 0

        async def fake_download(url):
            nonlocal call_count
            call_count += 1
            return ""

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        body, error = await SiteProcessor._download_retry("http://x.com/empty.txt")
        assert body == ""
        assert error is None
        assert call_count == 1

    async def test_http_status_surfaced_in_error(self, monkeypatch):
        async def fake_download(url):
            raise DownloadError("HTTP 404", status_code=404)

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        body, error = await SiteProcessor._download_retry("http://x.com/missing.txt", retries=1)
        assert body is None
        assert error == "HTTP 404"

    async def test_permanent_4xx_is_not_retried(self, monkeypatch):
        """A stale 404 link cannot recover within one run; retrying wastes time."""
        calls: list[str] = []

        async def fake_download(url):
            calls.append(url)
            raise DownloadError("HTTP 404", status_code=404)

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        body, error = await SiteProcessor._download_retry("http://x.com/missing.txt", retries=3)
        assert body is None
        assert error == "HTTP 404"
        assert len(calls) == 1

    async def test_403_is_not_retried(self, monkeypatch):
        calls: list[str] = []

        async def fake_download(url):
            calls.append(url)
            raise DownloadError("HTTP 403", status_code=403)

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        await SiteProcessor._download_retry("http://x.com/blocked.txt", retries=3)
        assert len(calls) == 1

    async def test_429_is_retried(self, monkeypatch):
        """Rate limiting is transient, so the retry budget still applies."""
        calls: list[str] = []

        async def fake_download(url):
            calls.append(url)
            raise DownloadError("HTTP 429", status_code=429, retry_after="0")

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        body, error = await SiteProcessor._download_retry("http://x.com/limited.txt", retries=3)
        assert body is None
        assert error == "HTTP 429"
        assert len(calls) == 3

    async def test_5xx_is_retried(self, monkeypatch):
        calls: list[str] = []

        async def fake_download(url):
            calls.append(url)
            raise DownloadError("HTTP 502", status_code=502, retry_after="0")

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        await SiteProcessor._download_retry("http://x.com/bad-gateway.txt", retries=2)
        assert len(calls) == 2

    async def test_network_error_is_retried(self, monkeypatch):
        """Exceptions without a status code stay retryable."""
        calls: list[str] = []

        async def fake_download(url):
            calls.append(url)
            raise OSError("connection reset")

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        await SiteProcessor._download_retry("http://x.com/x.txt", retries=2)
        assert len(calls) == 2

    async def test_retry_after_delta_seconds_honoured(self, monkeypatch):
        """Retry-After: 5 → sleep 5s instead of the fixed 1.5s."""
        delays: list[float] = []

        async def fake_download(url):
            raise DownloadError("HTTP 429", status_code=429, retry_after="5")

        async def fake_sleep(seconds):
            delays.append(seconds)

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        monkeypatch.setattr("src.site_processor.asyncio.sleep", fake_sleep)
        body, error = await SiteProcessor._download_retry("http://x.com/f.yaml")
        assert body is None
        assert error == "HTTP 429"
        assert delays == [5.0, 5.0]

    async def test_retry_after_http_date_honoured(self, monkeypatch):
        """Retry-After as an HTTP-date → sleep the remaining seconds."""
        delays: list[float] = []

        async def fake_download(url):
            when = datetime.now(timezone.utc) + timedelta(seconds=12)
            raise DownloadError(
                "HTTP 503", status_code=503,
                retry_after=format_datetime(when, usegmt=True),
            )

        async def fake_sleep(seconds):
            delays.append(seconds)

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        monkeypatch.setattr("src.site_processor.asyncio.sleep", fake_sleep)
        body, error = await SiteProcessor._download_retry("http://x.com/f.yaml", retries=2)
        assert body is None
        assert error == "HTTP 503"
        assert len(delays) == 1
        assert 10 <= delays[0] <= 12

    async def test_malformed_retry_after_falls_back(self, monkeypatch):
        """Garbage Retry-After → fixed 1.5s delay."""
        delays: list[float] = []

        async def fake_download(url):
            raise DownloadError("HTTP 429", status_code=429, retry_after="soon-ish")

        async def fake_sleep(seconds):
            delays.append(seconds)

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        monkeypatch.setattr("src.site_processor.asyncio.sleep", fake_sleep)
        body, _error = await SiteProcessor._download_retry("http://x.com/f.yaml", retries=2)
        assert body is None
        assert delays == [1.5]

    async def test_retry_after_capped_at_30s(self, monkeypatch):
        """A hostile Retry-After cannot stall the run for more than 30s."""
        delays: list[float] = []

        async def fake_download(url):
            raise DownloadError("HTTP 429", status_code=429, retry_after="86400")

        async def fake_sleep(seconds):
            delays.append(seconds)

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        monkeypatch.setattr("src.site_processor.asyncio.sleep", fake_sleep)
        await SiteProcessor._download_retry("http://x.com/f.yaml", retries=2)
        assert delays == [30.0]

    async def test_past_http_date_yields_zero_delay(self, monkeypatch):
        """A Retry-After date in the past means retry immediately."""
        delays: list[float] = []

        async def fake_download(url):
            raise DownloadError(
                "HTTP 503", status_code=503,
                retry_after="Wed, 21 Oct 2015 07:28:00 GMT",
            )

        async def fake_sleep(seconds):
            delays.append(seconds)

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        monkeypatch.setattr("src.site_processor.asyncio.sleep", fake_sleep)
        await SiteProcessor._download_retry("http://x.com/f.yaml", retries=2)
        assert delays == [0.0]


# ═══════════════════════════════════════════════════════════════
# _parse_retry_after
# ═══════════════════════════════════════════════════════════════

class TestParseRetryAfter:

    def test_none_or_empty_returns_none(self):
        assert SiteProcessor._parse_retry_after(None) is None
        assert SiteProcessor._parse_retry_after("") is None
        assert SiteProcessor._parse_retry_after("   ") is None

    def test_delta_seconds(self):
        assert SiteProcessor._parse_retry_after("120") == 30.0  # capped
        assert SiteProcessor._parse_retry_after("5") == 5.0
        assert SiteProcessor._parse_retry_after("0") == 0.0

    def test_http_date(self):
        when = datetime.now(timezone.utc) + timedelta(seconds=10)
        result = SiteProcessor._parse_retry_after(format_datetime(when, usegmt=True))
        assert result is not None
        assert 8 <= result <= 10

    def test_malformed_returns_none(self):
        assert SiteProcessor._parse_retry_after("not-a-date") is None
        assert SiteProcessor._parse_retry_after("12.5") is None
        assert SiteProcessor._parse_retry_after("Wed, 99 Xxx 9999") is None
        assert SiteProcessor._parse_retry_after("²") is None  # non-ASCII digit

    def test_negative_date_clamped_to_zero(self):
        assert SiteProcessor._parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


# ═══════════════════════════════════════════════════════════════
# _run_blog: skip vs error classification
# ═══════════════════════════════════════════════════════════════

VALID_TXT = "vless://418048af-a293-4b99-9b0c-98ca3580dd24@example.com:443"


def make_blog_config(tmp_path) -> Config:
    return Config(
        sites=[SiteConfig(name="skip-site", start_url="https://example.com/blog/")],
        crawl=CrawlConfig(max_articles=1, timeout=30, concurrency=1),
        output={"dir": str(tmp_path / "nodes")},
        llm=LLMConfig(),
    )


class TestRunBlogClassification:

    async def test_unsupported_and_empty_are_skipped(
        self, monkeypatch, tmp_path,
    ):
        """Unsupported + 0-byte downloads increment ``skipped``, not ``errors``."""
        config = make_blog_config(tmp_path)
        processor = SiteProcessor(config.sites[0], config, None)

        blog = make_page(links=[
            {"href": "/post-2026-06-18.htm", "text": "6月18日 | Post"},
        ])
        downloads = {
            "https://example.com/a.txt": VALID_TXT,
            "https://example.com/b.json": '{"outbounds": []}',
            "https://example.com/c.yaml": "",
        }

        async def fake_fetch(url, timeout_ms=60000):
            if url == "https://example.com/blog/":
                return blog
            return make_page(url=url, markdown="")

        async def fake_download(url):
            return downloads[url]

        async def fake_extract(page):
            return sorted(downloads), False

        monkeypatch.setattr("src.site_processor.fetch_page", fake_fetch)
        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        monkeypatch.setattr(SiteProcessor, "_extract_links", staticmethod(fake_extract))

        result = await processor.run()

        assert result.txt_count == 1
        assert result.skipped == 2
        assert result.errors == []

    async def test_real_download_error_is_an_error(
        self, monkeypatch, tmp_path,
    ):
        """A 404 stays an error and reports the HTTP status."""
        config = make_blog_config(tmp_path)
        processor = SiteProcessor(config.sites[0], config, None)

        blog = make_page(links=[
            {"href": "/post-2026-06-18.htm", "text": "6月18日 | Post"},
        ])

        async def fake_fetch(url, timeout_ms=60000):
            if url == "https://example.com/blog/":
                return blog
            return make_page(url=url, markdown="")

        async def fake_download(url):
            raise DownloadError("HTTP 404", status_code=404)

        async def fake_extract(page):
            return ["https://example.com/missing.txt"], False

        monkeypatch.setattr("src.site_processor.fetch_page", fake_fetch)
        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        monkeypatch.setattr(SiteProcessor, "_extract_links", staticmethod(fake_extract))

        result = await processor.run()

        assert result.skipped == 0
        assert len(result.errors) == 1
        assert "download failed: https://example.com/missing.txt" in result.errors[0]
        assert "(HTTP 404)" in result.errors[0]


# ═══════════════════════════════════════════════════════════════
# SiteResult
# ═══════════════════════════════════════════════════════════════

class TestSiteResult:

    def test_default_values(self):
        r = SiteResult(site_name="test")
        assert r.articles_processed == 0
        assert r.txt_count == 0
        assert r.yaml_count == 0
        assert r.total_bytes == 0
        assert r.pattern_saved is False
        assert r.skipped == 0
        assert r.errors == []
