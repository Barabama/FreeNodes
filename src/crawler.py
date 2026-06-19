"""双引擎爬取：Crawl4AI 取页面结构 + httpx 下载文件."""
import httpx
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from dataclasses import dataclass


@dataclass
class Page:
    url: str
    markdown: str
    html: str
    links: list[dict]  # [{"href": "...", "text": "..."}]
    success: bool = True
    error: str = ""


async def fetch_page(url: str, timeout_ms: int = 60000) -> Page:
    """Crawl4AI 爬取页面，返回结构化内容."""
    try:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(
                url=url,
                config=CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    page_timeout=timeout_ms,
                ),
            )
        if not result.success:
            return Page(url=url, success=False, error=result.error_message, markdown="", html="", links=[])

        md_obj = result.markdown
        markdown_text = ""
        if md_obj and hasattr(md_obj, "raw_markdown"):
            markdown_text = md_obj.raw_markdown or ""

        links: list[dict] = []
        for scope in ("internal", "external"):
            for link in (result.links or {}).get(scope, []):
                href = link.get("href", "")
                if href and not href.startswith("javascript:"):
                    links.append({"href": href, "text": link.get("text", "")[:200]})

        return Page(url=url, markdown=markdown_text, html=result.html or "", links=links)

    except Exception as e:
        return Page(url=url, success=False, error=str(e), markdown="", html="", links=[])


async def download_file(url: str) -> str:
    """httpx 下载文件，加大 read timeout 避免大 yaml 超时."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=15.0, read=60.0),
        follow_redirects=True,
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    ) as c:
        resp = await c.get(url)
        resp.raise_for_status()
        return resp.text
