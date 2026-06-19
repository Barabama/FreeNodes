"""Inspect clashmeta blog page and article page structure."""
import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode

BLOG_URL = "https://clash-meta.github.io/free-nodes/"
ARTICLE_URL = "https://clash-meta.github.io/newly-discovered-nodes/index.html?date=2026-6-18"


async def main():
    async with AsyncWebCrawler() as crawler:
        # --- Blog page ---
        print("=" * 80)
        print("BLOG PAGE:", BLOG_URL)
        print("=" * 80)
        result = await crawler.arun(
            url=BLOG_URL,
            config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=30000),
        )
        if result.success:
            print(f"Title: {result.metadata.get('title') if result.metadata else 'N/A'}")
            print(f"\n--- RAW HTML (first 3000 chars) ---")
            print(result.html[:3000] if result.html else "NO HTML")
            print(f"\n--- MARKDOWN (first 3000 chars) ---")
            md = result.markdown.raw_markdown if result.markdown else ""
            print(md[:3000])
            print(f"\n--- ALL LINKS ---")
            links = result.links if result.links else {}
            internal = links.get("internal", [])
            external = links.get("external", [])
            print(f"Internal links ({len(internal)}):")
            for l in internal[:15]:
                print(f"  href={l.get('href')} text={l.get('text','')[:80]}")
            print(f"External links ({len(external)}):")
            for l in external[:15]:
                print(f"  href={l.get('href')} text={l.get('text','')[:80]}")
        else:
            print(f"FAILED: {result.error_message}")

        # --- Article page ---
        print("\n" + "=" * 80)
        print("ARTICLE PAGE:", ARTICLE_URL)
        print("=" * 80)
        result2 = await crawler.arun(
            url=ARTICLE_URL,
            config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=30000),
        )
        if result2.success:
            print(f"Title: {result2.metadata.get('title') if result2.metadata else 'N/A'}")
            print(f"\n--- RAW HTML (first 3000 chars) ---")
            print(result2.html[:3000] if result2.html else "NO HTML")
            print(f"\n--- MARKDOWN (first 3000 chars) ---")
            md2 = result2.markdown.raw_markdown if result2.markdown else ""
            print(md2[:3000])
            print(f"\n--- FULL HTML (for link pattern search) ---")
            html = result2.html or ""
            # Search for key patterns
            import re
            for pat in [r'\.txt', r'\.yaml', r'vmess', r'vless', r'trojan', r'shadowsocks', r'clash', r'sub']:
                matches = [m.group()[:100] for m in re.finditer(rf'.{{0,80}}{pat}.{{0,80}}', html, re.I)]
                if matches:
                    print(f"  '{pat}' matches ({len(matches)}):")
                    for m in matches[:5]:
                        print(f"    ...{m}...")
            print(f"\n--- ALL LINKS on article page ---")
            links2 = result2.links if result2.links else {}
            for scope, lst in links2.items():
                if lst:
                    print(f"  {scope}:")
                    for l in lst[:10]:
                        print(f"    href={l.get('href')} text={l.get('text','')[:80]}")
        else:
            print(f"FAILED: {result2.error_message}")


if __name__ == "__main__":
    asyncio.run(main())
