"""Tests for honest run reporting: skips must not inflate the error summary.

Run: pytest tests/test_observability.py -v
"""
from src.scheduler import Scheduler
from src.site_processor import SiteResult


class TestSummaryCounting:

    def test_skips_do_not_count_as_errored_sites(self, capsys):
        """A site with only skips is not listed under 'had errors'."""
        skipped = SiteResult(site_name="skip-only", txt_count=1, skipped=3)
        failed = SiteResult(site_name="real-error", errors=["blog fetch failed"])

        Scheduler._print_summary([skipped, failed])

        out = capsys.readouterr().out
        assert "⚠ 1 site(s) had errors" in out
        assert "blog fetch failed" in out

    def test_only_skips_prints_no_error_section(self, capsys):
        """All-skipped results produce no error section at all."""
        skipped = SiteResult(site_name="skip-only", skipped=4)

        Scheduler._print_summary([skipped])

        out = capsys.readouterr().out
        assert "had errors" not in out
        assert "skip-only" in out
