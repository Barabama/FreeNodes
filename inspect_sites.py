"""Inspect a blog site's page structure for FreeNodeSpider integration."""
import asyncio, re
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode


async def inspect(name: str, url: str):
    print(f"\n{'='*70}")
    print(f"SITE: {name}")
    print(f"URL:  {url}")
    print(f"{'='*70}")
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS, page_timeout=30000))
        if not result.success:
            print(f"  FAILED: {result.error_message[:100]}")
            return
        md = result.markdown.raw_markdown if result.markdown else ""
        html = result.html or ""
        print(f"  Title: {result.metadata.get('title','N/A') if result.metadata else 'N/A'}")
        print(f"  Markdown: {len(md)} chars")
        print(f"  HTML: {len(html)} chars")
        links = result.links or {}
        internal = links.get("internal", [])
        external = links.get("external", [])
        all_links = internal + external
        print(f"  Links: {len(internal)} internal + {len(external)} external")

        # Show article-like links
        print(f"\n  --- Article-like links ---")
        for l in all_links[:20]:
            href = l.get("href", "")
            text = l.get("text", "")[:60]
            # Check for date patterns
            has_date_cn = bool(re.search(r'\d{1,2}月\d{1,2}日', text))
            has_date_url = bool(re.search(r'20\d{2}[-\/]\d{1,2}[-\/]\d{1,2}', href))
            if has_date_cn or has_date_url or ".txt" in href or ".yaml" in href:
                print(f"    📄 {href:55s} {text}")

        # Show subscription links
        print(f"\n  --- Subscription links (.txt / .yaml) ---")
        for l in all_links:
            href = l.get("href", "")
            if ".txt" in href or ".yaml" in href:
                print(f"    🔗 {href}")

        # Show LLM-friendly markdown preview
        print(f"\n  --- Markdown preview (first 2000 chars) ---")
        print(md[:2000])


async def main():
    sites = [
        ("nodefree",       "https://nodefree.me/"),
        ("nodev2ray",      "https://nodev2ray.com/free-node/"),
        ("freeclashnode",  "https://www.freeclashnode.com/free-node/"),
        ("clashnode",      "https://clashnode.cc/free-node/"),
        ("oneclash",       "https://oneclash.cc/freenode/"),
        ("yoyapai",        "https://yoyapai.com/category/mianfeijiedian/"),
        ("85la",           "https://www.85la.com/internet-access/free-network-nodes/"),
        ("cfmem",          "https://www.cfmem.com/"),
        ("jichangx",       "https://jichangx.com/free-subscription/"),
        ("clashstair",     "https://clashstair.com/category/freenode/"),
        ("datiya",         "https://free.datiya.com/"),
    ]
    for name, url in sites:
        await inspect(name, url)

if __name__ == "__main__":
    asyncio.run(main())
