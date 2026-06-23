"""Paste.to / PrivateBin client-side encrypted paste decryption.

These services encrypt content in the browser using AES-256 with the
decryption key stored in the URL fragment (#key). When accessed through
YouTube redirects, the fragment is lost — we need to extract the full
URL (with fragment) from the video description first.
"""
import logging
import re
from urllib.parse import unquote

from src.crawler import Page
from src.utils import has_subscription_content

logger = logging.getLogger(__name__)


def extract_paste_url(text: str) -> str | None:
    """Extract paste.to / PrivateBin URL with fragment key from text.

    Handles YouTube redirect URLs that embed the real URL in ?q= parameter.
    Preserves URL fragment (#key) which is critical for client-side decryption.
    """
    paste_patterns = [
        r'(https?://paste\.to/\?[a-zA-Z0-9_=-]+#[a-zA-Z0-9_-]+)',
        r'(https?://(?:dpaste|hastebin|privatebin)\.[a-zA-Z.]+/[^\s<>"\')\]]+#[a-zA-Z0-9_-]+)',
    ]
    for pat in paste_patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)

    # YouTube redirect URLs — extract real URL from ?q= parameter
    yt_redirect = re.search(
        r'https?://(?:www\.)?youtube\.com/redirect\?[^"\'>\s]*',
        text,
    )
    if yt_redirect:
        redirect_url = yt_redirect.group(0)
        m = re.search(r'[&?]q=([^&]+)', redirect_url)
        if m:
            real_url = unquote(m.group(1))
            if 'paste' in real_url or '#' in real_url:
                return real_url

    return None


async def decrypt_paste(
    url: str,
    password: str,
    password_selector: str = "#passworddecrypt",
    button_text: str = "解密",
    timeout_ms: int = 30000,
) -> Page | None:
    """Open a paste.to URL and decrypt with password.

    paste.to uses client-side AES-256 decryption. The key is in the URL fragment.
    The password input is for additional access control (separate from the AES key).

    Returns Page with decrypted content, or None on failure.
    """
    js_code = f"""
    (async () => {{
        await new Promise(r => setTimeout(r, 3000));

        const pwdInput = document.querySelector('{password_selector}');
        if (pwdInput) {{
            pwdInput.value = '{password}';
            pwdInput.dispatchEvent(new Event('input', {{ bubbles: true }}));

            const btns = document.querySelectorAll('button');
            for (const btn of btns) {{
                if (btn.textContent.trim().includes('{button_text}')) {{
                    btn.click();
                    break;
                }}
            }}
            await new Promise(r => setTimeout(r, 5000));
        }}

        const textEl = document.querySelector('#cleartext, .highlight, pre, code, article');
        return textEl ? textEl.textContent : document.body.innerText;
    }})()
    """

    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
        async with AsyncWebCrawler() as crawler:
            config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                page_timeout=timeout_ms,
                js_code=js_code,
            )
            result = await crawler.arun(url=url, config=config)

        if not result.success:
            logger.warning("Paste decrypt failed: %s", result.error_message[:100])
            return None

        content = result.markdown.raw_markdown if result.markdown and hasattr(result.markdown, "raw_markdown") else ""
        html = result.html or ""

        if has_subscription_content(content, html):
            return Page(
                url=url,
                markdown=content,
                html=html,
                links=_extract_links_from_paste(content),
                success=True,
            )
        else:
            logger.info("Paste decrypted but no subscription content found")
            return None

    except Exception as e:
        logger.warning("Paste decrypt error: %s", str(e)[:100])
        return None


def _extract_links_from_paste(text: str) -> list[dict]:
    """Extract subscription links from decrypted paste content."""
    links: list[dict] = []
    url_pattern = r'https?://[^\s<>"\'\[\]()]+'
    for m in re.finditer(url_pattern, text):
        href = m.group(0).rstrip('.,;)')
        if href.endswith(('.txt', '.yaml', '.yml', '.json', '.conf')):
            links.append({"href": href, "text": href})
        # Capture .jpg "fake" subscription links (OneDrive trick)
        elif href.endswith('.jpg') and ('dlink' in href or '1drv' in href or 'onedrive' in href):
            links.append({"href": href, "text": href})
    return links
