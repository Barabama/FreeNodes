"""SiteProcessor — full lifecycle for a single crawl target.

Extracted from the original mvp_clashmeta.py monolith.
"""
import asyncio
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urljoin, urlparse

from src.config import SiteConfig, Config
from src.crawler import Page, fetch_page, download_file
from src.llm_router import LLMRouter
from src.pipeline import save


@dataclass
class SiteResult:
    """Result summary for one site after processing."""
    site_name: str
    articles_processed: int = 0
    txt_count: int = 0
    yaml_count: int = 0
    total_bytes: int = 0
    pattern_saved: bool = False
    link_pattern: str | None = None
    errors: list[str] = field(default_factory=list)


class SiteProcessor:
    """Process a single site end-to-end: blog → articles → links → download → save."""

    def __init__(self, site: SiteConfig, config: Config, llm: LLMRouter):
        self.site = site
        self.max_articles = config.crawl.max_articles
        self.output_dir = config.output.get("dir", "nodes")
        self.llm = llm
        self._base = self._derive_base(site.start_url)

    # ── Public ──

    async def run(self) -> SiteResult:
        """Run the full site processing pipeline."""
        result = SiteResult(site_name=self.site.name)
        print(f"\n{'='*60}")
        print(f"SITE: {self.site.name} ({self.site.start_url})")
        print(f"Cfg:  pattern={self.site.link_pattern or 'null (LLM)'}")
        print(f"{'='*60}")

        # 1. Fetch blog
        print(f"\n[1/4] Fetching blog page...")
        blog = await fetch_page(self.site.start_url)
        if not blog.success:
            result.errors.append(f"blog fetch failed: {blog.error[:100]}")
            return result
        print(f"       got {len(blog.links)} links, {len(blog.markdown)} chars")

        # 2. Pick newest articles
        print(f"\n[2/4] Picking newest {self.max_articles} articles...")
        articles = self._pick_articles(blog)
        for a in articles:
            print(f"       [{a['date']}] {a['url']}")
        if not articles:
            result.errors.append("no articles found")
            return result

        # 3. Process each article
        print(f"\n[3/4] Processing {len(articles)} articles...")
        all_txt: set[str] = set()
        all_yaml: set[str] = set()
        pattern_saved = False

        for i, article in enumerate(articles):
            print(f"  [{i+1}/{len(articles)}] {article['url']}")
            article_page = await fetch_page(article["url"], timeout_ms=60000)
            if not article_page.success:
                err = f"  article fetch failed: {article_page.error[:80]}"
                print(err)
                result.errors.append(err)
                continue

            links, saved = await self._extract_links(article_page)
            if saved:
                pattern_saved = True

            for url in links:
                if url.endswith(".txt"):
                    all_txt.add(url)
                elif url.endswith(".yaml"):
                    all_yaml.add(url)

        result.articles_processed = len(articles)
        result.pattern_saved = pattern_saved
        result.link_pattern = self.site.link_pattern

        total_links = len(all_txt) + len(all_yaml)
        print(f"\n       total: {len(all_txt)} txt + {len(all_yaml)} yaml = {total_links} unique links")
        if not total_links:
            result.errors.append("no subscription links found")
            return result

        # 4. Download files
        print(f"\n[4/4] Downloading {total_links} files (up to 3 retries)...")
        txt_contents: list[str] = []
        yaml_contents: list[str] = []

        for url in sorted(all_txt):
            body = await self._download_retry(url)
            if body:
                txt_contents.append(body)
                result.txt_count += 1
                result.total_bytes += len(body)
                print(f"  OK  txt: {url} ({len(body)}B)")
            else:
                result.errors.append(f"txt download failed: {url}")
                print(f"  FAIL txt: {url}")

        for url in sorted(all_yaml):
            body = await self._download_retry(url)
            if body:
                yaml_contents.append(body)
                result.yaml_count += 1
                result.total_bytes += len(body)
                print(f"  OK  yaml: {url} ({len(body)}B)")
            else:
                result.errors.append(f"yaml download failed: {url}")
                print(f"  FAIL yaml: {url}")

        if txt_contents:
            save(self.site.name, ".txt", "\n".join(txt_contents), self.output_dir)
        if yaml_contents:
            save(self.site.name, ".yaml", "\n---\n".join(yaml_contents), self.output_dir)

        # Update crawl metadata
        self.site.up_date = date.today().isoformat()
        self.site.node_count = result.txt_count + result.yaml_count

        print(f"\n{'='*60}")
        print(f"DONE: {self.site.name} — {result.txt_count} txt + {result.yaml_count} yaml ({result.total_bytes}B)")
        if pattern_saved:
            print(f"  pattern self-healed: {self.site.link_pattern}")
        print(f"{'='*60}")

        return result

    # ── Article selection ──

    def _pick_articles(self, blog: Page) -> list[dict]:
        """Select the *max_articles* newest articles from a blog listing page.

        Rule-only: tries several date formats found across different blog sites.
        """
        articles: list[dict] = []
        for link in blog.links:
            text = link.get("text", "")
            href = link.get("href", "")
            d = self._parse_article_date(text, href)
            if d is None:
                continue

            # Exclude non-article links: exact matches + configurable substring patterns
            if href in ("/free-nodes/", "/", ""):
                continue
            exclusions = self.site.exclude_patterns or ["category", "page-"]
            if any(pat in href for pat in exclusions if isinstance(pat, str)):
                continue

            full = urljoin(self._base, href)
            articles.append({"url": full, "date": d, "text": text[:80]})

        seen: set[str] = set()
        unique: list[dict] = []
        for a in sorted(articles, key=lambda x: x["date"], reverse=True):
            if a["url"] not in seen:
                seen.add(a["url"])
                unique.append(a)
        return unique[:self.max_articles]

    # ── Link extraction: rule-first + LLM fallback + self-heal ──

    async def _extract_links(self, page: Page) -> tuple[list[str], bool]:
        """Extract subscription links from an article page.

        Returns (links, pattern_saved).
        """
        html = page.html

        # Step 1: rule-first
        if self.site.link_pattern:
            # If pattern failed too many times, reset it so LLM gets retried
            if self.site.failed_count >= 5:
                print(f"    pattern failed {self.site.failed_count}x, resetting to null")
                self.site.link_pattern = None
            else:
                result = self._extract_by_pattern(html, self.site.link_pattern)
                if result:
                    print(f"    regex hit: {len(result)} links (0 LLM)")
                    self.site.failed_count = 0
                    return result, False

                self.site.failed_count += 1
                print(f"    regex miss (failed_count={self.site.failed_count}), falling back to LLM")

        # Step 2: LLM fallback
        llm_result = await self.llm.extract_links(page.markdown)
        all_links = (
            llm_result.get("txt", [])
            + llm_result.get("yaml", [])
            + llm_result.get("other", [])
        )
        inline_links = llm_result.get("inline", [])
        if inline_links:
            print(f"    inline nodes found: {len(inline_links)} (protocol links)")

        # If no downloadable links, try saving inline protocol links as pseudo-txt
        if not all_links and inline_links:
            combined = "\n".join(inline_links)
            print(f"    no files, saving {len(inline_links)} inline protocol links")
            return [combined], False

        if not all_links:
            print("    LLM also found nothing, giving up")
            return [], False

        print(f"    LLM found {len(all_links)} links")
        for link in all_links[:3]:
            print(f"       {link}")

        # Step 3: generate pattern
        new_pattern = await self.llm.generate_pattern(all_links, html)
        if not new_pattern:
            print("    LLM could not generate pattern, skipping self-heal")
            return all_links, False

        print(f"    generated pattern: {new_pattern[:80]}...")

        # Step 4: three-layer verification
        if LLMRouter.verify_pattern(new_pattern, all_links, html):
            print("    pattern verified! writing to config")
            self.site.link_pattern = new_pattern
            self.site.failed_count = 0
            return all_links, True
        else:
            print("    pattern rejected by verification, keeping null")
            return all_links, False

    # ── Helpers ──

    @staticmethod
    def _parse_article_date(text: str, href: str) -> str | None:
        """Extract date from article title text or URL href.

        Tries these patterns in order:
          1. ``X月X日`` in title text                    → 2026-06-18
          2. ``YYYY年MM月DD日`` in title text              → 2026-06-18
          3. ``YYYY/MM/DD`` in title text                 → 2026-06-18
          4. ``YYYY-MM-DD`` in href URL                   → 2026-06-18
          5. ``YYYYMMDD`` (8-digit) in href URL            → 2026-06-18
        """
        m = re.search(r"(\d{1,2})月(\d{1,2})日", text)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            today = date.today()
            parsed = date(today.year, month, day)
            # Cross-year boundary: if parsed date is > 1 month in the future,
            # it's likely from last year (e.g. "12月30日" seen on Jan 1st)
            diff_days = (parsed - today).days
            if diff_days > 30:
                parsed = parsed.replace(year=today.year - 1)
            return parsed.isoformat()
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", text)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", href)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r"/(\d{8})[/-]", href)
        if m:
            raw = m.group(1)
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
        return None

    @staticmethod
    def _extract_by_pattern(html: str, pattern: str) -> list[str]:
        """Extract subscription URLs matching *pattern*."""
        compiled = re.compile(pattern, re.IGNORECASE)
        matches = compiled.findall(html)
        if matches and isinstance(matches[0], tuple):
            matches = [m[0] for m in matches]
        cleaned: list[str] = []
        for m in matches:
            if isinstance(m, str) and m.startswith("http"):
                m = re.sub(r'[),;.\'"]+$', "", m)
                cleaned.append(m)
        return cleaned

    @staticmethod
    async def _download_retry(url: str, retries: int = 3) -> str | None:
        """Download a file with retry."""
        for attempt in range(retries):
            try:
                return await download_file(url)
            except Exception as e:
                msg = str(e) or "timeout"
                if attempt < retries - 1:
                    print(f"    retry {attempt+1}/{retries} {url} ({msg})")
                    await asyncio.sleep(1.5)
        return None

    @staticmethod
    def _derive_base(start_url: str) -> str:
        """Extract scheme + host from a URL for resolving relative links."""
        parsed = urlparse(start_url)
        return f"{parsed.scheme}://{parsed.netloc}"
