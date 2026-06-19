"""Tests for Scheduler: site resolution, parallel dispatch, error handling.

Run: pytest tests/test_scheduler.py -v
"""
import asyncio
import pytest

pytestmark = pytest.mark.asyncio

from src.scheduler import Scheduler
from src.site_processor import SiteResult
from src.config import Config, SiteConfig, CrawlConfig, LLMConfig


@pytest.fixture
def three_site_config():
    return Config(
        sites=[
            SiteConfig(name="site-a", start_url="http://a.test/"),
            SiteConfig(name="site-b", start_url="http://b.test/"),
            SiteConfig(name="site-c", start_url="http://c.test/"),
        ],
        crawl=CrawlConfig(max_articles=2, timeout=5, concurrency=2),
        output={"dir": "nodes"},
        llm=LLMConfig(),
    )


@pytest.fixture
def scheduler(three_site_config):
    return Scheduler(three_site_config)


# ═══════════════════════════════════════════════════════════════
# _resolve_sites
# ═══════════════════════════════════════════════════════════════

class TestResolveSites:

    def test_returns_all_sites_when_no_target(self, scheduler):
        sites = scheduler._resolve_sites(None)
        assert len(sites) == 3

    def test_returns_single_site_when_target_matches(self, scheduler):
        sites = scheduler._resolve_sites("site-b")
        assert len(sites) == 1
        assert sites[0].name == "site-b"

    def test_returns_empty_when_target_unknown(self, scheduler):
        sites = scheduler._resolve_sites("nonexistent")
        assert sites == []

    def test_target_is_case_sensitive(self, scheduler):
        sites = scheduler._resolve_sites("SITE-A")
        assert sites == []


# ═══════════════════════════════════════════════════════════════
# _print_summary
# ═══════════════════════════════════════════════════════════════

class TestPrintSummary:

    def test_empty_results(self, scheduler, capsys):
        scheduler._print_summary([])
        captured = capsys.readouterr()
        assert "SUMMARY" in captured.out
        assert "TOTAL" in captured.out

    def test_single_result(self, scheduler, capsys):
        r = SiteResult(site_name="test", articles_processed=2,
                        txt_count=3, yaml_count=1, total_bytes=5000)
        scheduler._print_summary([r])
        captured = capsys.readouterr()
        assert "test" in captured.out
        assert "3" in captured.out  # txt_count
        assert "5000B" in captured.out

    def test_shows_errors(self, scheduler, capsys):
        r = SiteResult(site_name="err-site", errors=["fetch failed"])
        scheduler._print_summary([r])
        captured = capsys.readouterr()
        assert "err-site" in captured.out
        assert "fetch failed" in captured.out


# ═══════════════════════════════════════════════════════════════
# run (with mocked SiteProcessor)
# ═══════════════════════════════════════════════════════════════

class TestRun:

    async def test_run_all_sites(self, three_site_config, monkeypatch):
        """All 3 sites processed, results collected."""
        processed: list[str] = []

        async def fake_run(self):
            processed.append(self.site.name)
            return SiteResult(site_name=self.site.name, articles_processed=1)

        monkeypatch.setattr("src.scheduler.SiteProcessor.run", fake_run)

        scheduler = Scheduler(three_site_config)
        results = await scheduler.run()
        assert len(results) == 3
        assert len(processed) == 3
        assert set(processed) == {"site-a", "site-b", "site-c"}

    async def test_run_single_target(self, three_site_config, monkeypatch):
        """Only the targeted site runs."""
        processed: list[str] = []

        async def fake_run(self):
            processed.append(self.site.name)
            return SiteResult(site_name=self.site.name)

        monkeypatch.setattr("src.scheduler.SiteProcessor.run", fake_run)

        scheduler = Scheduler(three_site_config)
        results = await scheduler.run(target="site-b")
        assert len(results) == 1
        assert processed == ["site-b"]

    async def test_handles_site_crash(self, three_site_config, monkeypatch):
        """One site crashing doesn't stop others."""
        call_count = 0

        async def fake_run(self):
            nonlocal call_count
            call_count += 1
            if self.site.name == "site-b":
                raise RuntimeError("crash!")
            return SiteResult(site_name=self.site.name, articles_processed=1)

        monkeypatch.setattr("src.scheduler.SiteProcessor.run", fake_run)

        scheduler = Scheduler(three_site_config)
        results = await scheduler.run()
        assert len(results) == 3
        # site-b should produce an error result
        err_sites = [r for r in results if r.errors]
        assert len(err_sites) == 1
        assert "crash" in err_sites[0].errors[0]

    async def test_respects_concurrency_limit(self, three_site_config, monkeypatch):
        """Semaphore cap = 2, max 2 concurrent."""
        running = 0
        max_concurrent = 0

        async def fake_run(self):
            nonlocal running, max_concurrent
            running += 1
            max_concurrent = max(max_concurrent, running)
            await asyncio.sleep(0.05)
            running -= 1
            return SiteResult(site_name=self.site.name)

        monkeypatch.setattr("src.scheduler.SiteProcessor.run", fake_run)

        scheduler = Scheduler(three_site_config)
        await scheduler.run()
        assert max_concurrent <= 2, f"concurrency exceeded limit: {max_concurrent}"
