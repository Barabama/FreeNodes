"""去重 + base64 decode + 输出到 nodes/."""
import base64
import hashlib
from pathlib import Path


def process_txt(raw: str) -> str:
    """Decode base64 v2ray 节点，按行 hash 去重."""
    try:
        decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
    except Exception:
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
    """输出到 nodes/{site}.{ext}."""
    path = Path(out_dir)
    path.mkdir(exist_ok=True)
    if ext == ".txt":
        content = process_txt(content)
    filepath = path / f"{site}{ext}"
    filepath.write_text(content, encoding="utf-8")
    lines = content.count("\n") + 1 if content else 0
    print(f"  Saved: {filepath} ({len(content)}B, {lines} lines)")
