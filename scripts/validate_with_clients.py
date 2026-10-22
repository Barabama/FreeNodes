"""Validate published node artifacts with real client binaries.

This is a local/CI integration check, not part of the unit-test suite.

Usage:
    python scripts/validate_with_clients.py --mihomo path/to/mihomo --v2ray path/to/v2ray
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

import yaml


@dataclass
class UriIssue:
    line: int
    scheme: str
    reason: str


def decode_base64(value: str) -> str | None:
    compact = re.sub(r"\s+", "", value)
    compact += "=" * (-len(compact) % 4)
    try:
        return base64.urlsafe_b64decode(compact).decode("utf-8")
    except Exception:
        return None


def validate_vmess(uri: str) -> str | None:
    payload = uri.split("://", 1)[1].split("#", 1)[0]
    text = payload if payload.lstrip().startswith("{") else decode_base64(payload)
    if not text:
        return "invalid base64 payload"
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return "invalid JSON payload"
    if not obj.get("add"):
        return "missing add"
    if not obj.get("id"):
        return "missing id"
    try:
        port = int(obj.get("port"))
    except (TypeError, ValueError):
        return "invalid port"
    if not 1 <= port <= 65535:
        return "invalid port"
    return None


def validate_vless(uri: str) -> str | None:
    try:
        parsed = urlsplit(uri)
        port = parsed.port
    except ValueError:
        return "invalid URL"
    if not parsed.hostname:
        return "missing host"
    if not parsed.username:
        return "missing user id"
    if port is None or not 1 <= port <= 65535:
        return "invalid port"
    query = parse_qs(parsed.query)
    if query.get("security", [""])[0] == "reality" and not query.get("pbk", [""])[0]:
        return "reality missing pbk"
    return None


def validate_trojan(uri: str) -> str | None:
    try:
        parsed = urlsplit(uri)
        port = parsed.port
    except ValueError:
        return "invalid URL"
    if not parsed.hostname or not parsed.username:
        return "missing host or password"
    if port is None or not 1 <= port <= 65535:
        return "invalid port"
    return None


def validate_ss(uri: str) -> str | None:
    payload = uri.split("://", 1)[1].split("#", 1)[0].split("?", 1)[0]
    if "@" in payload:
        userinfo, hostport = payload.rsplit("@", 1)
        if ":" not in userinfo:
            decoded = decode_base64(userinfo)
            if not decoded or ":" not in decoded:
                return "invalid userinfo"
        try:
            host, port = hostport.rsplit(":", 1)
            if not host or not 1 <= int(port) <= 65535:
                return "invalid host or port"
        except ValueError:
            return "invalid host or port"
        return None
    decoded = decode_base64(payload)
    if not decoded or ":" not in decoded or "@" not in decoded:
        return "invalid legacy payload"
    return None


def validate_uri(uri: str) -> str | None:
    scheme = uri.split("://", 1)[0].lower()
    validators = {
        "vmess": validate_vmess,
        "vless": validate_vless,
        "trojan": validate_trojan,
        "ss": validate_ss,
    }
    validator = validators.get(scheme)
    if validator is None:
        return None
    return validator(uri)


def check_mihomo(binary: Path, config: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [str(binary), "-t", "-f", str(config)],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", default="nodes")
    parser.add_argument("--mihomo", required=True)
    parser.add_argument("--v2ray")
    args = parser.parse_args()

    nodes = Path(args.nodes)
    mihomo = Path(args.mihomo)
    failures = 0

    for name in ("merged.yaml", "provider.yaml"):
        ok, output = check_mihomo(mihomo, (nodes / name).resolve())
        print(f"{'PASS' if ok else 'FAIL'} mihomo {name}")
        if not ok:
            failures += 1
            print(output[-2000:])

    txt = nodes / "merged.txt"
    lines = [line.strip() for line in txt.read_text(encoding="utf-8").splitlines() if line.strip()]
    schemes = Counter(line.split("://", 1)[0].lower() for line in lines if "://" in line)
    issues: list[UriIssue] = []
    for number, line in enumerate(lines, 1):
        scheme = line.split("://", 1)[0].lower() if "://" in line else "<none>"
        reason = validate_uri(line)
        if reason:
            issues.append(UriIssue(number, scheme, reason))

    print(f"TXT lines={len(lines)} schemes={dict(schemes)} errors={len(issues)}")
    for issue in issues[:20]:
        print(f"  line {issue.line} {issue.scheme}: {issue.reason}")
    if issues:
        failures += 1

    if args.v2ray:
        v2ray = Path(args.v2ray)
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "v2ray.json"
            config = {
                "log": {"loglevel": "warning"},
                "inbounds": [],
                "outbounds": [{"protocol": "freedom", "tag": "direct"}],
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")
            proc = subprocess.run(
                [str(v2ray), "test", "-config", str(config_path)],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
            )
            ok = proc.returncode == 0
            print(f"{'PASS' if ok else 'FAIL'} v2ray baseline config")
            if not ok:
                failures += 1
                print((proc.stdout + proc.stderr)[-2000:])

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
