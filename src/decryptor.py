"""Page decryption via Playwright — password input and form submission.

Handles password-protected blog posts (yudou66 type) using Crawl4AI's js_code
for form filling and submission. Falls back to brute-force for 4-digit passwords.
"""
import logging
import re
from dataclasses import dataclass

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode

from src.crawler import Page
from src.utils import has_subscription_content

logger = logging.getLogger(__name__)


@dataclass
class DecryptResult:
    """Result of a decryption attempt."""
    success: bool
    password: str | None = None
    content: str = ""         # decrypted page text
    error: str = ""


def generate_password_candidates(hint: str = "AABB") -> list[str]:
    """Generate 4-digit password candidates sorted by pattern priority.

    hint controls which patterns to try first:
      - "AABB": 0011, 0022, ..., 1122, 1133, ... (90 candidates)
      - "ABAB": 0101, 0202, ..., 1212, 1313, ... (90 candidates)
      - "all":  exhaustive 0000-9999 (10000 candidates, last resort)
    """
    candidates: list[str] = []

    # AABB pattern: 0011, 0022, ..., 9988
    for a in range(10):
        for b in range(10):
            if a != b:
                candidates.append(f"{a}{a}{b}{b}")

    # ABAB pattern: 0101, 0202, ..., 9898
    if hint in ("ABAB", "all"):
        for a in range(10):
            for b in range(10):
                if a != b:
                    pwd = f"{a}{b}{a}{b}"
                    if pwd not in candidates:
                        candidates.append(pwd)

    # Exhaustive (last resort)
    if hint == "all":
        for i in range(10000):
            pwd = str(i).zfill(4)
            if pwd not in candidates:
                candidates.append(pwd)

    return candidates


def detect_protection(html: str) -> bool:
    """Detect if a page requires password input (structural indicators only).

    Only checks for actual input fields and decrypt buttons, not text content.
    """
    indicators = [
        'class="cl-input"',
        'placeholder="在此输入密码"',
        'class="cl-btn"',
        'type="password"',
        'input[type="text"][class*="cl-input"]',
    ]
    html_lower = html.lower()
    return any(ind.lower() in html_lower for ind in indicators)


async def try_decrypt(
    url: str,
    password: str,
    input_selector: str = ".cl-input",
    button_selector: str = ".cl-btn",
    timeout_ms: int = 30000,
) -> DecryptResult:
    """Try to decrypt a password-protected page.

    Uses Crawl4AI's js_code to fill the password input and click submit.
    """
    js_code = f"""
    (async () => {{
        // Find password input
        const input = document.querySelector('{input_selector}');
        if (!input) return 'no_input';

        // Fill password
        input.value = '{password}';
        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
        input.dispatchEvent(new Event('change', {{ bubbles: true }}));

        // Find and click decrypt button
        const btn = document.querySelector('{button_selector}');
        if (!btn) return 'no_button';
        btn.click();

        // Wait for content to appear
        await new Promise(r => setTimeout(r, 3000));
        return document.body.innerText;
    }})()
    """

    try:
        async with AsyncWebCrawler() as crawler:
            config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                page_timeout=timeout_ms,
                js_code=js_code,
            )
            result = await crawler.arun(url=url, config=config)

        if not result.success:
            return DecryptResult(success=False, error=result.error_message)

        content = result.markdown.raw_markdown if result.markdown and hasattr(result.markdown, "raw_markdown") else ""
        html = result.html or ""

        # Check if decryption was successful (content should have subscription links)
        if has_subscription_content(content, html):
            return DecryptResult(success=True, password=password, content=content)
        else:
            return DecryptResult(success=False, password=password,
                                 error="Decryption did not reveal subscription content")

    except Exception as e:
        return DecryptResult(success=False, error=str(e)[:200])


async def brute_force_4digit(
    url: str,
    hint: str = "AABB",
    input_selector: str = ".cl-input",
    button_selector: str = ".cl-btn",
    max_attempts: int = 100,
    timeout_ms: int = 30000,
) -> DecryptResult:
    """Brute-force 4-digit password with pattern priority.

    hint: "AABB" (fast, 90 attempts), "ABAB" (180), "all" (10000, slow)

    Note: Each attempt creates a new Crawl4AI instance (slow for brute-force).
    This is a last-resort fallback when YouTube subtitle extraction fails.
    """
    candidates = generate_password_candidates(hint)[:max_attempts]
    logger.info("Brute-forcing %s pattern: %d candidates", hint, len(candidates))

    # Reuse a single Crawl4AI instance for all attempts
    async with AsyncWebCrawler() as crawler:
        for i, pwd in enumerate(candidates):
            result = await _try_password_with_crawler(
                crawler, url, pwd, input_selector, button_selector, timeout_ms,
            )
            if result.success:
                logger.info("Password found: %s (attempt %d/%d)", pwd, i + 1, len(candidates))
                return result

            if (i + 1) % 20 == 0:
                logger.info("Brute-force progress: %d/%d", i + 1, len(candidates))

    return DecryptResult(success=False, error=f"Exhausted {len(candidates)} candidates")


async def _try_password_with_crawler(
    crawler: AsyncWebCrawler,
    url: str,
    password: str,
    input_selector: str,
    button_selector: str,
    timeout_ms: int,
) -> DecryptResult:
    """Try a single password with a reused crawler instance."""
    js_code = f"""
    (async () => {{
        const input = document.querySelector('{input_selector}');
        if (!input) return 'no_input';
        input.value = '{password}';
        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
        const btn = document.querySelector('{button_selector}');
        if (!btn) return 'no_button';
        btn.click();
        await new Promise(r => setTimeout(r, 3000));
        return document.body.innerText;
    }})()
    """
    try:
        result = await crawler.arun(
            url=url,
            config=CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                page_timeout=timeout_ms,
                js_code=js_code,
            ),
        )
        if not result.success:
            return DecryptResult(success=False, password=password, error=result.error_message)

        content = result.markdown.raw_markdown if result.markdown and hasattr(result.markdown, "raw_markdown") else ""
        html = result.html or ""

        if has_subscription_content(content, html):
            return DecryptResult(success=True, password=password, content=content)
        return DecryptResult(success=False, password=password)
    except Exception as e:
        return DecryptResult(success=False, password=password, error=str(e)[:100])


# Legacy alias for test compatibility
_has_subscription_content = has_subscription_content
