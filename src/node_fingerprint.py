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


def _normalize(value: object) -> object:
    """Return a hashable form that is equal for semantically equal values.

    Only scalars whose representations are interchangeable are folded
    together: integers and digit-only strings, which appear both in Clash
    files and in URIs. Booleans stay distinct from "1". Mappings and
    sequences are converted recursively and compared structurally, so no
    nested value can collide with a neighbour through a separator.
    """
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, float):
        return ("float", value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdecimal():
            return ("int", int(stripped))
        return ("str", stripped)
    if isinstance(value, dict):
        items = frozenset(
            (str(key), _normalize(item)) for key, item in value.items()
        )
        return ("map", items)
    if isinstance(value, (list, tuple)):
        return ("seq", tuple(_normalize(item) for item in value))
    return ("other", repr(value))


def canonical_value(value: object) -> object:
    """Return the comparison key for one field value."""
    return _normalize(value)


def proxy_fingerprint(proxy: dict) -> tuple:
    """Return the connection-configuration fingerprint of a Clash proxy.

    A tuple of ``(field, normalized_value)`` pairs: structured, so no field
    value can ever run into the next one.
    """
    return tuple(
        (key, canonical_value(proxy[key]))
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
