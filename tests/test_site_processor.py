"""Tests for SiteProcessor: article selection, link extraction, download retry.

Run: pytest tests/test_site_processor.py -v
"""
import pytest

pytestmark = pytest.mark.asyncio

from src.site_processor import SiteProcessor, SiteResult
from src.config import SiteConfig, Config, CrawlConfig, LLMConfig, ProviderConfig
from src.crawler import Page
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
        """Retries 3 times, returns None on total failure."""
        call_count = 0

        async def fake_download(url):
            nonlocal call_count
            call_count += 1
            raise ConnectionError("timeout")

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        result = await SiteProcessor._download_retry("http://x.com/f.yaml")
        assert result is None
        assert call_count == 3

    async def test_succeeds_on_first_try(self, monkeypatch):
        async def fake_download(url):
            return "content ok"

        monkeypatch.setattr("src.site_processor.download_file", fake_download)
        result = await SiteProcessor._download_retry("http://x.com/f.txt")
        assert result == "content ok"


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
        assert r.errors == []
