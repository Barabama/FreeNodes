"""Node dedup + base64 decode + output to nodes/ directory."""
import base64
import hashlib
import re
from pathlib import Path


def _is_base64_sub(raw: str) -> bool:
    """Detect if content is base64-encoded subscription data (not already plain text)."""
    stripped = raw.strip()
    if not stripped:
        return False
    if re.search(r'(vmess|vless|trojan|ss|ssr|socks|hysteria)://', stripped):
        return False
    return bool(re.fullmatch(r'[A-Za-z0-9+/=\s]+', stripped))


def process_txt(raw: str) -> str:
    """Decode base64 v2ray nodes if needed, dedup by line hash."""
    if _is_base64_sub(raw):
        try:
            decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
        except Exception:
            decoded = raw
    else:
        decoded = raw

    seen: set[str] = set()
    unique: list[str] = []
    for line in decoded.splitlines():
        line = line.strip()
        if not line:
            continue
        h = hashlib.md5(line.encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(line)
    return "\n".join(unique)


def save(site: str, ext: str, content: str, out_dir: str = "nodes"):
    """Write deduped content to nodes/{site}.{ext}."""
    path = Path(out_dir)
    path.mkdir(exist_ok=True)
    if ext == ".txt":
        content = process_txt(content)
    filepath = path / f"{site}{ext}"
    filepath.write_text(content, encoding="utf-8")
    lines = content.count("\n") + 1 if content else 0
    print(f"  Saved: {filepath} ({len(content)}B, {lines} lines)")
