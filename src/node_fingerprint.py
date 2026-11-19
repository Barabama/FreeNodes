"""Node identity fingerprints for deduplicating merged artifacts.

A fingerprint describes the *connection configuration* of a node. Display-only
fields (remarks, proxy names) are excluded, because the same upstream node is
often republished under a different label by every blog. Everything that can
change whether a client connects — credentials, transport, TLS and plugin
options — is deliberately kept, so two nodes are never merged just because
they share a host and port.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

# Fields that only affect how a node is displayed in a client.
DISPLAY_FIELDS = frozenset({"name", "ps", "remarks", "remark"})

_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.+)$", re.DOTALL)


# ── Value canonicalisation ──

def canonical_value(value: object) -> str:
    """Render a field value so semantically equal values compare equal.

    ``443`` and ``"443"`` must produce the same fingerprint, and mapping key
    order must not matter.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return "{" + ",".join(
            f"{key}={canonical_value(value[key])}" for key in sorted(value)
        ) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_value(item) for item in value) + "]"
    return str(value)


def proxy_fingerprint(proxy: dict) -> tuple[str, ...]:
    """Return the connection-configuration fingerprint of a Clash proxy."""
    return tuple(
        f"{key}={canonical_value(proxy[key])}"
        for key in sorted(proxy)
        if key not in DISPLAY_FIELDS and proxy[key] is not None
    )


# ── TXT URI fingerprints ──

def uri_scheme(line: str) -> str | None:
    """Return the lowercase URI scheme, or ``None`` when *line* is not a URI."""
    match = _SCHEME_RE.match(line.strip().lstrip("﻿"))
    return match.group(1).lower() if match else None


def _decode_base64(value: str) -> str | None:
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return None
    compact += "=" * (-len(compact) % 4)
    try:
        return base64.urlsafe_b64decode(compact.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeError, binascii.Error):
        return None


def _vmess_payload(body: str) -> dict | None:
    """Decode a vmess payload into its JSON object without the remark field."""
    payload = body.split("#", 1)[0]
    text = payload
    if not payload.lstrip().startswith("{"):
        decoded = _decode_base64(payload)
        if decoded is None:
            return None
        text = decoded
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def txt_fingerprint(line: str) -> tuple[str, ...]:
    """Return the connection fingerprint of one subscription URI.

    Only the display-name fragment (and vmess ``ps``) is ignored; every other
    part of the URI is kept verbatim so parameters that affect connectivity are
    never collapsed.
    """
    clean = line.strip().lstrip("﻿")
    match = _SCHEME_RE.match(clean)
    if not match:
        return ("raw", clean)
    scheme = match.group(1).lower()
    body = match.group(2)
    if scheme == "vmess":
        obj = _vmess_payload(body)
        if obj is None:
            return ("vmess-raw", body.split("#", 1)[0])
        return ("vmess", *proxy_fingerprint(obj))
    return (scheme, body.split("#", 1)[0])


def txt_endpoint(line: str) -> tuple[str, int] | None:
    """Return ``(host, port)`` for a subscription URI, or ``None``.

    Used by TCP probing, which needs an address rather than a URI.
    """
    clean = line.strip().lstrip("﻿")
    match = _SCHEME_RE.match(clean)
    if not match:
        return None
    scheme = match.group(1).lower()
    body = match.group(2)

    if scheme == "vmess":
        obj = _vmess_payload(body)
        if obj is None:
            return None
        host, port = obj.get("add"), obj.get("port")
        return _host_port(host, port)

    # SIP002 lets Shadowsocks carry the whole method:password@host:port payload
    # either plain or base64-encoded, so urlsplit cannot be used directly.
    if scheme == "ss":
        payload = body.split("#", 1)[0].split("?", 1)[0]
        if "@" in payload:
            _userinfo, hostport = payload.rsplit("@", 1)
        else:
            decoded = _decode_base64(payload)
            if decoded is None or "@" not in decoded:
                return None
            _userinfo, hostport = decoded.rsplit("@", 1)
        host, _, port_text = hostport.rpartition(":")
        return _host_port(host, port_text)

    try:
        parsed = urlsplit(clean.split("#", 1)[0])
        port = parsed.port
    except ValueError:
        return None
    if port is None and scheme in {"hysteria2", "hy2"}:
        # Hysteria2 permits an omitted port and defaults to 443.
        port = 443
    return _host_port(parsed.hostname, port)


def _host_port(host: object, port: object) -> tuple[str, int] | None:
    if not isinstance(host, str) or not host.strip():
        return None
    if port is None or isinstance(port, bool):
        return None
    try:
        port_number = int(port)
    except (TypeError, ValueError):
        return None
    if not 1 <= port_number <= 65535:
        return None
    return host.strip().lower(), port_number


# ── Deduplication ──

def unique_by(items: Iterable, key: Callable) -> list:
    """Keep the first item of each fingerprint, preserving input order."""
    seen: set = set()
    unique: list = []
    for item in items:
        fingerprint = key(item)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(item)
    return unique
