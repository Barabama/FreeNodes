"""Scheduler — parallel site dispatching with shared resource management."""
import asyncio
import logging

from src.config import Config, SiteConfig
from src.llm_router import LLMRouter
from src.site_processor import SiteProcessor, SiteResult
from src.merger import Merger
from src.readme_updater import write_readme

logger = logging.getLogger(__name__)


class Scheduler:
    """Dispatch multiple sites concurrently with a shared LLMRouter.

    Usage:
        config = load_config()
        scheduler = Scheduler(config)
        results = await scheduler.run()          # all sites
        results = await scheduler.run("nodefree")  # single site
    """

    def __init__(self, config: Config):
        self.config = config
        self.llm = LLMRouter(config)

    async def run(self, target: str | None = None) -> list[SiteResult]:
        """Run all (or a single) sites, respecting concurrency limit.

        Args:
            target: Optional site name. When set, only that site runs.

        Returns:
            List of SiteResult, one per processed site.
        """
        sites = self._resolve_sites(target)
        if not sites:
            logger.error("No sites to process")
            return []

        semaphore = asyncio.Semaphore(self.config.crawl.concurrency)

        async def _run_one(site: SiteConfig) -> SiteResult:
            async with semaphore:
                processor = SiteProcessor(site, self.config, self.llm)
                return await processor.run()

        tasks = [_run_one(s) for s in sites]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final: list[SiteResult] = []
        for site, result in zip(sites, results):
            if isinstance(result, Exception):
                err = SiteResult(
                    site_name=site.name,
                    errors=[f"unhandled exception: {result}"],
                )
                final.append(err)
                logger.error(f"Site {site.name} crashed: {result}")
            else:
                final.append(result)

        self._print_summary(final)

        # Run merger + readme after all sites processed
        if not target:
            out_dir = self.config.output.get("dir", "nodes")
            merger = Merger(nodes_dir=out_dir)
            merge_result = merger.run()
            print(f"\n  merge: {merge_result.total_nodes} total nodes across "
                  f"{merge_result.txt_sources} txt + {merge_result.yaml_sources} yaml sources")
            print(f"  files: {merge_result.merged_txt or '(skip)'}, "
                  f"{merge_result.merged_yaml or '(skip)'}, "
                  f"{merge_result.provider_yaml or '(skip)'}")

            # Update README with latest dates
            write_readme(self.config)

        return final

    def _resolve_sites(self, target: str | None) -> list[SiteConfig]:
        """Resolve target string to a list of SiteConfig."""
        if target:
            matches = [s for s in self.config.sites if s.name == target]
            if not matches:
                logger.warning(f"Unknown target '{target}', ignoring")
            return matches
        return self.config.sites

    @staticmethod
    def _print_summary(results: list[SiteResult]):
        """Print a summary table of all site results."""
        print(f"\n{'='*70}")
        print(f"{'SUMMARY':^70}")
        print(f"{'='*70}")
        print(f"{'SITE':16s} {'ARTICLES':10s} {'TXT':6s} {'YAML':6s} {'BYTES':12s} {'PATTERN':12s}")
        print("-" * 70)
        total = SiteResult(site_name="TOTAL")
        for r in results:
            lp = r.link_pattern
            pattern = "✓ self-healed" if r.pattern_saved else (lp[:20] if lp else "—")
            print(f"{r.site_name:16s} {r.articles_processed:4d}        {r.txt_count:4d}   {r.yaml_count:4d}  {r.total_bytes:8d}B  {pattern:12s}")
            total.articles_processed += r.articles_processed
            total.txt_count += r.txt_count
            total.yaml_count += r.yaml_count
            total.total_bytes += r.total_bytes
        print("-" * 70)
        print(f"{total.site_name:16s} {total.articles_processed:4d}        {total.txt_count:4d}   {total.yaml_count:4d}  {total.total_bytes:8d}B")
        print(f"{'='*70}")

        errors = [r for r in results if r.errors]
        if errors:
            print(f"\n⚠ {len(errors)} site(s) had errors:")
            for r in errors:
                for e in r.errors:
                    print(f"  [{r.site_name}] {e}")
