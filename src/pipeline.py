"""Node dedup + subscription normalization + output to nodes/ directory."""
import hashlib
from pathlib import Path

from src.node_validator import normalize_yaml_text, valid_txt_lines, decode_subscription_text


def process_txt(raw: str) -> str:
    """Decode, validate, and deduplicate proxy URI lines."""
    decoded = decode_subscription_text(raw)
    valid, _issues = valid_txt_lines(decoded)
    seen: set[str] = set()
    unique: list[str] = []
    for line in valid:
        h = hashlib.md5(line.encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(line)
    return "\n".join(unique)


def save(site: str, ext: str, content: str, out_dir: str = "nodes"):
    """Write validated content to nodes/{site}.{ext}."""
    path = Path(out_dir)
    path.mkdir(exist_ok=True)
    if ext == ".txt":
        content = process_txt(content)
    elif ext in {".yaml", ".yml"}:
        content = normalize_yaml_text(content)
    filepath = path / f"{site}{ext}"
    filepath.write_text(content, encoding="utf-8")
    lines = content.count("\n") + 1 if content else 0
    print(f"  Saved: {filepath} ({len(content)}B, {lines} lines)")
