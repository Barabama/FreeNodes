"""Shared utilities for content detection across modules."""
import re


def has_subscription_content(text: str, html: str) -> bool:
    """Check if page content contains subscription URLs or protocol URIs.

    Only matches actual subscription URLs and protocol links, not generic
    keywords like "clash" or "v2ray" which appear in ads and navigation.
    """
    combined = text + html
    patterns = [
        r'https?://[^"\'<\s]+\.(txt|yaml)',
        r'(vmess|vless|trojan|ss|ssr)://[a-zA-Z0-9+/=:@.#-]+',
    ]
    return any(re.search(p, combined, re.IGNORECASE) for p in patterns)
