"""Convert subscription URIs into Clash/Mihomo proxy mappings.

The Merger publishes both a TXT subscription and a YAML config for the same
upstream nodes. Probing that follows the real client load path needs the YAML
form, so TXT lines are converted here before they are handed to Mihomo.

Conversion is best-effort: a URI whose scheme or parameters are not covered
returns ``None`` and is kept unprobed, never silently dropped.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.+)$", re.DOTALL)


def _b64(value: str) -> str | None:
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return None
    compact += "=" * (-len(compact) % 4)
    try:
        return base64.urlsafe_b64decode(compact.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeError, binascii.Error):
        return None


def _first(query: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = query.get(name)
        if values and values[0]:
            return values[0]
    return None


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes"}


def _port(value: object) -> int | None:
    try:
        port = int(str(value))
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _remark(fragment: str, fallback: str) -> str:
    return unquote(fragment) if fragment else fallback


def _apply_transport(proxy: dict, network: str | None, query: dict[str, list[str]],
                     header_type: str | None = None) -> None:
    """Translate ``network``/``type`` parameters into Mihomo transport options."""
    network = (network or "tcp").lower()
    if network in {"ws", "httpupgrade"}:
        opts = {"path": _first(query, "path") or "/"}
        host = _first(query, "host")
        if host:
            opts["headers"] = {"Host": host}
        proxy["network"] = "ws"
        proxy["ws-opts"] = opts
    elif network == "grpc":
        service = _first(query, "serviceName", "service") or ""
        proxy["network"] = "grpc"
        proxy["grpc-opts"] = {"grpc-service-name": service}
    elif network == "h2":
        opts: dict = {"path": _first(query, "path") or "/"}
        host = _first(query, "host")
        if host:
            opts["host"] = [part for part in host.split(",") if part]
        proxy["network"] = "h2"
        proxy["h2-opts"] = opts
    elif network == "tcp" and header_type and header_type.lower() == "http":
        proxy["network"] = "http"
        request: dict = {"path": [_first(query, "path") or "/"]}
        host = _first(query, "host")
        if host:
            request["headers"] = {"Host": [host]}
        proxy["http-opts"] = {"method": "GET", "path": request["path"], **(
            {"headers": request["headers"]} if "headers" in request else {}
        )}


def _apply_tls(proxy: dict, query: dict[str, list[str]]) -> None:
    security = (_first(query, "security") or "").lower()
    tls = security in {"tls", "reality", "xtls"} or _truthy(_first(query, "tls"))
    if not tls:
        return
    proxy["tls"] = True
    server_name = _first(query, "sni", "peer")
    if server_name:
        proxy["servername"] = server_name
    if _truthy(_first(query, "allowInsecure", "insecure", "skip-cert-verify")):
        proxy["skip-cert-verify"] = True
    fingerprint = _first(query, "fp", "fingerprint")
    if fingerprint:
        proxy["client-fingerprint"] = fingerprint
    public_key = _first(query, "pbk", "public-key")
    if security == "reality" and public_key:
        reality: dict = {"public-key": public_key}
        short_id = _first(query, "sid", "short-id")
        if short_id is not None:
            reality["short-id"] = short_id
        proxy["reality-opts"] = reality


def _vmess(body: str, name_hint: str) -> dict | None:
    payload = body.split("#", 1)[0]
    text = payload if payload.lstrip().startswith("{") else _b64(payload)
    if text is None:
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    server, uuid, port = obj.get("add"), obj.get("id"), _port(obj.get("port"))
    if not server or not uuid or port is None:
        return None
    proxy: dict = {
        "name": obj.get("ps") or name_hint,
        "type": "vmess",
        "server": server,
        "port": port,
        "uuid": uuid,
        "alterId": int(obj.get("aid") or 0),
        "cipher": obj.get("scy") or "auto",
        "udp": True,
    }
    query: dict[str, list[str]] = {}
    for key in ("path", "host", "serviceName", "sni", "alpn"):
        value = obj.get(key)
        if value:
            query[key] = [str(value)]
    _apply_transport(proxy, obj.get("net"), query, obj.get("type"))
    if str(obj.get("tls") or "").lower() in {"tls", "reality"}:
        proxy["tls"] = True
        if obj.get("sni") or obj.get("host"):
            proxy["servername"] = obj.get("sni") or obj.get("host")
        if obj.get("allowInsecure"):
            proxy["skip-cert-verify"] = True
        if obj.get("fp"):
            proxy["client-fingerprint"] = obj["fp"]
    return proxy


def _vless(clean: str, parts, name_hint: str) -> dict | None:
    parsed = urlsplit(clean)
    if not parsed.hostname or not parsed.username:
        return None
    port = parsed.port
    if port is None:
        return None
    query = parse_qs(parsed.query)
    proxy: dict = {
        "name": name_hint,
        "type": "vless",
        "server": parsed.hostname,
        "port": port,
        "uuid": unquote(parsed.username),
        "udp": True,
    }
    flow = _first(query, "flow")
    if flow:
        proxy["flow"] = flow
    _apply_transport(proxy, _first(query, "type"), query, _first(query, "headerType"))
    _apply_tls(proxy, query)
    packet_encoding = _first(query, "packetEncoding")
    if packet_encoding:
        proxy["packet-encoding"] = packet_encoding
    return proxy


def _trojan(clean: str, parts, name_hint: str) -> dict | None:
    parsed = urlsplit(clean)
    if not parsed.hostname or parsed.username is None or parsed.port is None:
        return None
    query = parse_qs(parsed.query)
    proxy: dict = {
        "name": name_hint,
        "type": "trojan",
        "server": parsed.hostname,
        "port": parsed.port,
        "password": unquote(parsed.username),
        "udp": True,
        "sni": _first(query, "sni", "peer") or parsed.hostname,
    }
    if _truthy(_first(query, "allowInsecure", "insecure", "skip-cert-verify")):
        proxy["skip-cert-verify"] = True
    alpns = _first(query, "alpn")
    if alpns:
        proxy["alpn"] = [part for part in alpns.split(",") if part]
    _apply_transport(proxy, _first(query, "type"), query)
    return proxy


def _shadowsocks(clean: str, body: str, name_hint: str) -> dict | None:
    payload, _, fragment = body.partition("#")
    payload = payload.split("?", 1)[0]
    query: dict[str, list[str]] = {}
    if "@" in payload:
        userinfo, hostport = payload.rsplit("@", 1)
        if ":" in userinfo:
            method, password = userinfo.split(":", 1)
        else:
            decoded = _b64(userinfo)
            if decoded is None or ":" not in decoded:
                return None
            method, password = decoded.split(":", 1)
    else:
        decoded = _b64(payload)
        if decoded is None:
            return None
        try:
            userinfo, hostport = decoded.rsplit("@", 1)
            method, password = userinfo.split(":", 1)
        except ValueError:
            return None
    host, _, port_text = hostport.rpartition(":")
    port = _port(port_text)
    if not host or not method or not password or port is None:
        return None
    # Plugin options live in the query string and may themselves contain '&'
    # escaped as %26 by the publisher.
    raw = clean.split("?", 1)[1].split("#", 1)[0] if "?" in clean else ""
    plugin_value = None
    for pair in raw.split("&"):
        key, _, value = pair.partition("=")
        if key == "plugin":
            plugin_value = unquote(value)
    if plugin_value:
        plugin_parts = plugin_value.split(";")
        plugin_name = plugin_parts[0]
        opts: dict = {}
        for part in plugin_parts[1:]:
            key, _, value = part.partition("=")
            if key:
                opts[key] = value
        proxy_plugin = "obfs" if plugin_name.startswith("obfs") else plugin_name
        proxy_opts: dict = {}
        if proxy_plugin == "obfs":
            proxy_opts["mode"] = opts.get("obfs", "http")
            if "obfs-host" in opts:
                proxy_opts["host"] = opts["obfs-host"]
        else:
            for key in ("mode", "host", "path", "tls"):
                if key in opts:
                    proxy_opts[key] = opts[key]
        query = {"plugin": [proxy_plugin], "opts": [json.dumps(proxy_opts)]}
    proxy: dict = {
        "name": _remark(fragment, name_hint),
        "type": "ss",
        "server": host,
        "port": port,
        "cipher": method,
        "password": password,
        "udp": True,
    }
    if query:
        proxy["plugin"] = query["plugin"][0]
        proxy["plugin-opts"] = json.loads(query["opts"][0])
    return proxy


def _hysteria2(clean: str, name_hint: str) -> dict | None:
    parsed = urlsplit(clean)
    if not parsed.hostname:
        return None
    query = parse_qs(parsed.query)
    auth = unquote(parsed.username or "") or _first(query, "auth", "password") or ""
    password = f"{auth}:{unquote(parsed.password)}" if parsed.password else auth
    proxy: dict = {
        "name": name_hint,
        "type": "hysteria2",
        "server": parsed.hostname,
        "port": parsed.port or 443,
        "password": password,
    }
    sni = _first(query, "sni", "peer")
    if sni:
        proxy["sni"] = sni
    if _truthy(_first(query, "insecure", "allowInsecure")):
        proxy["skip-cert-verify"] = True
    obfs = _first(query, "obfs")
    if obfs:
        proxy["obfs"] = obfs
        obfs_password = _first(query, "obfs-password")
        if obfs_password:
            proxy["obfs-password"] = obfs_password
    return proxy


def _hysteria(clean: str, name_hint: str) -> dict | None:
    parsed = urlsplit(clean)
    if not parsed.hostname:
        return None
    query = parse_qs(parsed.query)
    proxy: dict = {
        "name": name_hint,
        "type": "hysteria",
        "server": parsed.hostname,
        "port": parsed.port or 443,
    }
    auth = _first(query, "auth")
    if auth:
        proxy["auth-str"] = auth
    protocol = _first(query, "protocol")
    if protocol:
        proxy["protocol"] = protocol
    sni = _first(query, "peer", "sni")
    if sni:
        proxy["sni"] = sni
    if _truthy(_first(query, "insecure", "allowInsecure")):
        proxy["skip-cert-verify"] = True
    alpns = _first(query, "alpn")
    if alpns:
        proxy["alpn"] = [part for part in alpns.split(",") if part]
    return proxy


def _tuic(clean: str, name_hint: str) -> dict | None:
    parsed = urlsplit(clean)
    if not parsed.hostname or not parsed.username or parsed.port is None:
        return None
    query = parse_qs(parsed.query)
    proxy: dict = {
        "name": name_hint,
        "type": "tuic",
        "server": parsed.hostname,
        "port": parsed.port,
        "uuid": unquote(parsed.username),
        "password": unquote(parsed.password or "") or _first(query, "password") or "",
    }
    sni = _first(query, "sni")
    if sni:
        proxy["sni"] = sni
    if _truthy(_first(query, "allow_insecure", "insecure", "skip-cert-verify")):
        proxy["skip-cert-verify"] = True
    congestion = _first(query, "congestion_control", "congestion-controller")
    if congestion:
        proxy["congestion-controller"] = congestion
    alpns = _first(query, "alpn")
    if alpns:
        proxy["alpn"] = [part for part in alpns.split(",") if part]
    return proxy


def _anytls(clean: str, name_hint: str) -> dict | None:
    parsed = urlsplit(clean)
    if not parsed.hostname or parsed.username is None or parsed.port is None:
        return None
    query = parse_qs(parsed.query)
    proxy: dict = {
        "name": name_hint,
        "type": "anytls",
        "server": parsed.hostname,
        "port": parsed.port,
        "password": unquote(parsed.username),
    }
    sni = _first(query, "sni", "peer")
    if sni:
        proxy["sni"] = sni
    if _truthy(_first(query, "insecure", "allowInsecure", "skip-cert-verify")):
        proxy["skip-cert-verify"] = True
    return proxy


def _plain_proxy(clean: str, scheme: str, name_hint: str) -> dict | None:
    parsed = urlsplit(clean)
    if not parsed.hostname or parsed.port is None:
        return None
    proxy: dict = {
        "name": name_hint,
        "type": "socks5" if scheme == "socks5" else scheme,
        "server": parsed.hostname,
        "port": parsed.port,
    }
    if parsed.username:
        proxy["username"] = unquote(parsed.username)
    if parsed.password:
        proxy["password"] = unquote(parsed.password)
    if scheme in {"http", "https"} and parsed.scheme == "https":
        proxy["tls"] = True
    return proxy


def uri_to_proxy(line: str) -> dict | None:
    """Convert one subscription URI into a Mihomo proxy mapping.

    Returns ``None`` when the scheme is unsupported or required fields are
    missing, so callers can keep such nodes unprobed instead of dropping them.
    """
    clean = line.strip().lstrip("﻿")
    match = _SCHEME_RE.match(clean)
    if not match:
        return None
    scheme = match.group(1).lower()
    body = match.group(2)
    fragment = clean.split("#", 1)[1] if "#" in clean else ""

    def hint() -> str:
        try:
            parsed = urlsplit(clean)
            host = parsed.hostname or ""
            return f"{host}:{parsed.port or 443}"
        except ValueError:
            # Inline-JSON vmess URIs are not URL-shaped.
            return clean[:32]

    name_hint = _remark(fragment, hint())

    if scheme == "vmess":
        return _vmess(body, name_hint)
    if scheme in {"vless"}:
        return _vless(clean, match, name_hint)
    if scheme == "trojan":
        return _trojan(clean, match, name_hint)
    if scheme == "ss":
        return _shadowsocks(clean, body, name_hint)
    if scheme in {"hysteria2", "hy2"}:
        return _hysteria2(clean, name_hint)
    if scheme == "hysteria":
        return _hysteria(clean, name_hint)
    if scheme == "tuic":
        return _tuic(clean, name_hint)
    if scheme == "anytls":
        return _anytls(clean, name_hint)
    if scheme in {"socks", "socks5", "http", "https"}:
        return _plain_proxy(clean, scheme, name_hint)
    return None
