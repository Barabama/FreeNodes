"""Inspect article pages for sites where LLM extraction failed."""
import asyncio, re
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode


async def inspect(name: str, url: str):
    print(f"\n{'='*60}")
    print(f"SITE: {name}")
    print(f"URL:  {url}")
    print(f"{'='*60}")
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS, page_timeout=30000))
        if not result.success:
            print(f"  FAILED: {result.error_message[:100]}")
            return

        md = result.markdown.raw_markdown if result.markdown else ""
        html = result.html or ""

        # Search for subscription patterns in HTML
        patterns = {
            '.txt': r'https?://[^"\'<\s]+\.txt',
            '.yaml': r'https?://[^"\'<\s]+\.yaml',
            'vmess': r'vmess://[a-zA-Z0-9+/=]+',
            'vless': r'vless://[a-zA-Z0-9+/=]+',
            'trojan': r'trojan://[^"\'<\s]+',
            'ss://': r'ss://[a-zA-Z0-9+/=@:.#]+',
            'ssr://': r'ssr://[a-zA-Z0-9+/=]+',
            'base64': r'[A-Za-z0-9+/]{50,}={0,2}',
        }
        print(f"\n  Markdown: {len(md)} chars")
        print(f"  HTML: {len(html)} chars")
        print(f"\n  --- Pattern search in HTML ---")
        for label, pat in patterns.items():
            matches = re.findall(pat, html)
            if matches:
                print(f"  {label}: {len(matches)} matches")
                for m in matches[:3]:
                    print(f"    {m[:120]}")

        print(f"\n  --- Markdown preview (first 3000 chars) ---")
        print(md[:3000])


async def main():
    sites = [
        ("cfmem article", "https://www.cfmem.com/2026/06/20260619-21-vless-x12-trojan-x5-vmess-x4.html"),
        ("jichangx article", "https://jichangx.com/free-nodes-2026-06-19/"),
        ("clashstair article", "https://clashstair.com/freenode/2026-06-19/"),
    ]
    for name, url in sites:
        await inspect(name, url)

if __name__ == "__main__":
    asyncio.run(main())
