"""Validation helpers for proxy subscription TXT and Mihomo YAML files.

The crawler accepts several subscription dialects, but its published artifacts
should be consumable by common clients.  This module deliberately performs
format validation only; it does not test whether a proxy is reachable.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import yaml


SUPPORTED_URI_SCHEMES = {
    "anytls",
    "hysteria",
    "hysteria2",
    "hy2",
    "http",
    "https",
    "juicity",
    "mieru",
    "naive",
    "quic",
    "shadowsocks",
    "socks",
    "socks5",
    "ssh",
    "ss",
    "ssr",
    "shadowtls",
    "snell",
    "trojan",
    "tuic",
    "vless",
    "vmess",
    "wireguard",
    "wg",
}

SUPPORTED_PROXY_TYPES = {
    "anytls",
    "http",
    "hysteria",
    "hysteria2",
    "hy2",
    "juicity",
    "mieru",
    "naive",
    "quic",
    "socks",
    "socks5",
    "ss",
    "ssr",
    "ssh",
    "shadowtls",
    "snell",
    "trojan",
    "tuic",
    "vless",
    "vmess",
    "wireguard",
}

BASE_REQUIRED_PROXY_FIELDS = ("name", "type", "server", "port")
UUID_TYPES = {"vmess", "vless", "tuic"}


@dataclass(frozen=True)
class ValidationIssue:
    """One validation finding."""

    severity: str
    code: str
    message: str
    location: str = ""

    def render(self) -> str:
        where = f" [{self.location}]" if self.location else ""
        return f"{self.severity.upper()} {self.code}{where}: {self.message}"


@dataclass
class ValidationResult:
    """Validation result for one text or file."""

    path: str = "<text>"
    kind: str = "unknown"
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, issue: ValidationIssue) -> None:
        (self.errors if issue.severity == "error" else self.warnings).append(issue)

    def extend(self, other: "ValidationResult") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        for key, value in other.stats.items():
            self.stats[key] = self.stats.get(key, 0) + value

    def render(self, strict: bool = False, max_issues: int = 20) -> str:
        status = "OK" if self.ok and (not strict or not self.warnings) else "FAIL"
        lines = [f"{status} {self.path} ({self.kind})"]
        issues = [*self.errors, *self.warnings]
        for issue in issues[:max_issues]:
            lines.append(f"  {issue.render()}")
        if len(issues) > max_issues:
            lines.append(f"  ... {len(issues) - max_issues} more findings")
        if self.stats:
            summary = ", ".join(f"{k}={v}" for k, v in sorted(self.stats.items()))
            lines.append(f"  stats: {summary}")
        return "\n".join(lines)


def _issue(result: ValidationResult, severity: str, code: str,
           message: str, location: str = "") -> None:
    result.add(ValidationIssue(severity, code, message, location))


def _decode_base64(value: str) -> bytes | None:
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return None
    compact += "=" * (-len(compact) % 4)
    try:
        return base64.urlsafe_b64decode(compact.encode("ascii"))
    except (ValueError, UnicodeEncodeError, binascii.Error):
        return None


def decode_subscription_text(raw: str) -> str:
    """Decode a base64 subscription only when its decoded content is node text."""
    stripped = raw.strip().lstrip("\ufeff")
    if not stripped or "://" in stripped:
        return raw
    if not re.fullmatch(r"[A-Za-z0-9+/=_\-\s]+", stripped):
        return raw
    decoded = _decode_base64(stripped)
    if decoded is None:
        return raw
    text = decoded.decode("utf-8", errors="replace")
    if re.search(r"(?im)^\s*(?:[a-z][a-z0-9+.-]*)://", text):
        return text
    return raw


def _valid_port(value: object) -> bool:
    """Return whether *value* is an integer TCP/UDP port."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 1 <= value <= 65535
    if isinstance(value, str) and value.isdecimal():
        return 1 <= int(value) <= 65535
    return False


def _non_empty(value: object) -> bool:
    return isinstance(value, (str, int, float)) and str(value).strip() != ""


def _looks_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except (ValueError, AttributeError):
        return False
    return True


def validate_proxy(proxy: object, location: str = "proxy", strict: bool = True) -> ValidationResult:
    """Validate one Mihomo/Clash proxy mapping."""
    result = ValidationResult(path=location, kind="proxy")
    if not isinstance(proxy, dict):
        _issue(result, "error", "proxy_not_mapping", "proxy must be a mapping")
        return result

    for field_name in BASE_REQUIRED_PROXY_FIELDS:
        if not _non_empty(proxy.get(field_name)):
            _issue(result, "error", "missing_field", f"missing required field '{field_name}'", field_name)

    proxy_type = str(proxy.get("type", "")).lower()
    if proxy_type not in SUPPORTED_PROXY_TYPES:
        _issue(result, "error", "unsupported_proxy_type", f"unsupported proxy type '{proxy_type}'", "type")
        return result

    if not _non_empty(proxy.get("server")):
        _issue(result, "error", "invalid_server", "server must be a non-empty hostname or address", "server")
    if not _valid_port(proxy.get("port")):
        _issue(result, "error", "invalid_port", "port must be an integer from 1 to 65535", "port")

    if strict:
        if proxy_type in UUID_TYPES and not _non_empty(proxy.get("uuid")):
            _issue(result, "error", "invalid_uuid", f"{proxy_type} requires a non-empty credential", "uuid")
        elif proxy_type == "vmess" and not _looks_uuid(proxy.get("uuid")):
            _issue(result, "error", "invalid_uuid", "vmess requires a UUID", "uuid")
        elif proxy_type == "vless" and not _looks_uuid(proxy.get("uuid")):
            _issue(result, "warning", "non_uuid_credential", "vless credential is not a UUID; some clients may reject it", "uuid")

    field_requirements = {
        "trojan": ("password",),
        "ss": ("cipher", "password"),
        "ssr": ("cipher", "password", "protocol", "obfs"),
        "hysteria": (),
        "hysteria2": ("password",),
        "hy2": ("password",),
        "anytls": ("password",),
        "tuic": ("password",),
    }
    if strict:
        for field_name in field_requirements.get(proxy_type, ()):
            if not _non_empty(proxy.get(field_name)):
                _issue(result, "error", "missing_field", f"{proxy_type} requires '{field_name}'", field_name)

        # Mihomo accepts hysteria auth/auth-str in addition to password in older
        # configurations.  At least one credential is required for a usable node.
        if proxy_type == "hysteria" and not any(_non_empty(proxy.get(k)) for k in ("auth", "auth-str", "password")):
            _issue(result, "warning", "missing_auth", "hysteria has no auth/password field")

    result.stats["proxies"] = 1
    result.stats[f"proxy_type_{proxy_type}"] = 1
    return result


def _validate_uri(line: str, location: str) -> tuple[str | None, str | None]:
    """Return (scheme, error message) for one subscription URI."""
    clean = line.strip().lstrip("\ufeff")
    match = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)://", clean)
    if not match:
        return None, "line is not a proxy URI"
    scheme = match.group(1).lower()
    if scheme not in SUPPORTED_URI_SCHEMES:
        return scheme, f"unsupported URI scheme '{scheme}'"

    if scheme == "vmess":
        payload = clean.split("://", 1)[1].split("#", 1)[0]
        # v2rayN and several subscription generators emit both the canonical
        # base64 JSON form and the inline JSON form.
        if payload.lstrip().startswith("{"):
            decoded_text = payload
        else:
            decoded = _decode_base64(payload)
            if decoded is None:
                return scheme, "vmess payload is not valid base64"
            decoded_text = decoded.decode("utf-8", errors="replace")
        try:
            obj = json.loads(decoded_text)
        except json.JSONDecodeError:
            return scheme, "vmess payload is not valid JSON"
        if not _non_empty(obj.get("add")) or not _non_empty(obj.get("id")):
            return scheme, "vmess JSON requires add and id"
        if not _valid_port(obj.get("port")):
            return scheme, "vmess JSON requires a valid port"
        return scheme, None

    # SIP002 Shadowsocks may encode the complete method:password@host:port
    # payload after ss://, so it has no URL host/port before decoding.
    if scheme == "ss":
        payload = clean.split("://", 1)[1].split("#", 1)[0]
        payload = payload.split("?", 1)[0]
        if "@" in payload:
            try:
                userinfo, hostport = payload.rsplit("@", 1)
                host, port_text = hostport.rsplit(":", 1)
                port = int(port_text)
            except (ValueError, UnicodeError):
                return scheme, "ss URI has an invalid method/password@host:port form"
            if ":" in userinfo:
                method, password = userinfo.split(":", 1)
            else:
                decoded_user = _decode_base64(userinfo)
                if decoded_user is None:
                    return scheme, "ss userinfo is not valid base64"
                try:
                    method, password = decoded_user.decode("utf-8").split(":", 1)
                except (UnicodeDecodeError, ValueError):
                    return scheme, "ss userinfo must decode to method:password"
            if not method or not password or not host or not (1 <= port <= 65535):
                return scheme, "ss URI must contain method, password, host, and valid port"
            return scheme, None
        decoded = _decode_base64(payload)
        if decoded is None:
            return scheme, "ss payload is not valid base64"
        try:
            decoded_text = decoded.decode("utf-8")
            userinfo, hostport = decoded_text.rsplit("@", 1)
            method, password = userinfo.split(":", 1)
            host, port_text = hostport.rsplit(":", 1)
            port = int(port_text)
        except (UnicodeDecodeError, ValueError):
            return scheme, "ss payload must be method:password@host:port"
        if not method or not password or not host or not (1 <= port <= 65535):
            return scheme, "ss payload must contain method, password, host, and valid port"
        return scheme, None

    try:
        parsed = urlsplit(clean)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return scheme, "URI has an invalid host or port"

    # Hysteria2 URI syntax permits an omitted port and defaults to 443.
    if scheme in {"hysteria2", "hy2"} and port is None:
        port = 443
    if not host:
        return scheme, "URI is missing a server host"
    if port is not None and not (1 <= port <= 65535):
        return scheme, "URI port must be from 1 to 65535"
    if port is None:
        return scheme, "URI is missing a port"

    if scheme in {"vless", "trojan", "anytls", "tuic"} and not parsed.username:
        return scheme, f"{scheme} URI is missing credentials"

    return scheme, None

def _looks_like_config_fragment(line: str) -> bool:
    """Identify JSON/YAML client configuration lines inside a TXT artifact."""
    stripped = line.strip().lstrip("\ufeff")
    if stripped in {"{", "}", "[", "]", "},", "],"}:
        return True
    if re.match(r'^"(?:log|experimental|dns|inbounds|outbounds|route|endpoints|servers|proxy-groups|proxy-providers)"\s*:', stripped):
        return True
    if re.match(r'^(?:mixed-port|socks-port|proxies|proxy-groups|proxy-providers|inbounds|outbounds|dns|rules):\s*', stripped):
        return True
    if stripped.startswith(('"tag":', '"type":', '"server":', '"listen":', '"route":', '"experimental":')):
        return True
    return False


def _expand_txt_lines(raw: str) -> list[tuple[int, str]]:
    """Expand mixed URI/base64 subscription lines without accepting config JSON."""
    decoded = decode_subscription_text(raw)
    expanded: list[tuple[int, str]] = []
    for line_number, original in enumerate(decoded.splitlines(), 1):
        line = original.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        if _looks_like_config_fragment(line):
            continue
        if "://" in line:
            expanded.append((line_number, line))
            continue
        if len(line) >= 20 and re.fullmatch(r"[A-Za-z0-9+/=_\-\s]+", line):
            nested = _decode_base64(line)
            if nested is not None:
                nested_text = nested.decode("utf-8", errors="replace")
                nested_lines = [item.strip().lstrip("\ufeff") for item in nested_text.splitlines() if item.strip()]
                if any("://" in item for item in nested_lines):
                    expanded.extend((line_number, item) for item in nested_lines)
                    continue
        expanded.append((line_number, line))
    return expanded


def valid_txt_lines(raw: str, strict: bool = True) -> tuple[list[str], list[ValidationIssue]]:
    """Return valid proxy URI lines and findings for invalid lines."""
    valid: list[str] = []
    issues: list[ValidationIssue] = []
    config_lines = [
        (number, line)
        for number, line in enumerate(decode_subscription_text(raw).splitlines(), 1)
        if _looks_like_config_fragment(line)
    ]
    if config_lines:
        issues.append(ValidationIssue(
            "error",
            "embedded_config",
            "TXT contains JSON/YAML client configuration fragments",
            f"line {config_lines[0][0]}",
        ))
    for line_number, line in _expand_txt_lines(raw):
        _scheme, error = _validate_uri(line, f"line {line_number}")
        if error and (strict or _scheme is None):
            issues.append(ValidationIssue("error", "invalid_uri", error, f"line {line_number}"))
        else:
            # Merger mode keeps recognizable URI lines for backwards-compatible
            # aggregation; strict validation is still used at publication time.
            valid.append(line)
    return valid, issues


def validate_txt_text(raw: str, path: str = "<text>") -> ValidationResult:
    """Validate a plain-text or base64 proxy subscription."""
    result = ValidationResult(path=path, kind="txt")
    decoded = decode_subscription_text(raw)
    result.stats["base64"] = int(decoded != raw)
    valid, issues = valid_txt_lines(raw)
    for issue in issues:
        result.add(issue)
    result.stats["valid_lines"] = len(valid)
    result.stats["invalid_lines"] = len(issues)
    schemes = Counter()
    for line in valid:
        scheme = line.split(":", 1)[0].lower()
        schemes[scheme] += 1
    for scheme, count in schemes.items():
        result.stats[f"scheme_{scheme}"] = count
    if not valid and raw.strip():
        _issue(result, "error", "no_proxy_lines", "file contains no valid proxy URI lines")
    return result


def _validate_provider_config(doc: dict, result: ValidationResult, doc_index: int) -> None:
    providers = doc.get("proxy-providers")
    if providers is None:
        return
    if not isinstance(providers, dict):
        _issue(result, "error", "invalid_proxy_providers", "proxy-providers must be a mapping", f"doc {doc_index}")
        return
    result.stats["provider_definitions"] = result.stats.get("provider_definitions", 0) + len(providers)
    for name, provider in providers.items():
        location = f"doc {doc_index}.proxy-providers.{name}"
        if not isinstance(provider, dict):
            _issue(result, "error", "provider_not_mapping", "provider must be a mapping", location)
            continue
        provider_type = str(provider.get("type", "")).lower()
        if provider_type not in {"file", "http", "https"}:
            _issue(result, "error", "invalid_provider_type", "provider type must be file/http/https", location)
        if provider_type == "file" and not _non_empty(provider.get("path")):
            _issue(result, "error", "missing_provider_path", "file provider requires path", location)
        if provider_type in {"http", "https"} and not _non_empty(provider.get("url")):
            _issue(result, "error", "missing_provider_url", "HTTP provider requires url", location)


def validate_yaml_text(raw: str, path: str = "<text>") -> ValidationResult:
    """Validate one or more YAML documents containing Mihomo proxies."""
    result = ValidationResult(path=path, kind="yaml")
    try:
        documents = list(yaml.safe_load_all(raw))
    except yaml.YAMLError as exc:
        _issue(result, "error", "yaml_parse_error", str(exc).splitlines()[0])
        return result

    documents = [doc for doc in documents if doc is not None]
    result.stats["documents"] = len(documents)
    if len(documents) > 1:
        _issue(result, "warning", "multiple_documents",
               "YAML contains multiple documents; publish a single Mihomo document")

    for doc_index, doc in enumerate(documents, 1):
        if not isinstance(doc, dict):
            _issue(result, "error", "yaml_root_not_mapping", "YAML document root must be a mapping", f"doc {doc_index}")
            continue
        _validate_provider_config(doc, result, doc_index)
        if "proxies" not in doc:
            continue
        proxies = doc["proxies"]
        if not isinstance(proxies, list):
            _issue(result, "error", "proxies_not_list", "proxies must be a list", f"doc {doc_index}")
            continue
        result.stats["proxy_entries"] = result.stats.get("proxy_entries", 0) + len(proxies)
        for proxy_index, proxy in enumerate(proxies, 1):
            proxy_result = validate_proxy(proxy, f"doc {doc_index}.proxies[{proxy_index}]")
            result.extend(proxy_result)
            if proxy_result.ok:
                result.stats["valid_proxy_entries"] = result.stats.get("valid_proxy_entries", 0) + 1

    if not documents:
        _issue(result, "error", "empty_yaml", "YAML contains no document")
    return result


def normalize_yaml_text(raw: str) -> str:
    """Collapse a multi-document proxy subscription into one provider document.

    Only proxy entries are retained intentionally: this makes the crawler's
    per-site YAML a portable file proxy-provider source for Mihomo and avoids
    concatenating unrelated full client configurations.
    """
    documents = list(yaml.safe_load_all(raw))
    proxies: list[dict] = []
    saw_proxy_list = False
    for doc in documents:
        if not isinstance(doc, dict) or not isinstance(doc.get("proxies"), list):
            continue
        saw_proxy_list = True
        for proxy in doc["proxies"]:
            if isinstance(proxy, dict) and validate_proxy(proxy).ok:
                proxies.append(proxy)
    if not proxies:
        return "" if saw_proxy_list else raw.strip() + ("\n" if raw.strip() else "")
    return yaml.safe_dump({"proxies": proxies}, allow_unicode=True, sort_keys=False, default_flow_style=False)


def validate_file(path: str | Path) -> ValidationResult:
    """Validate a .txt/.yaml/.yml artifact."""
    file_path = Path(path)
    try:
        raw = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result = ValidationResult(path=str(file_path), kind="unknown")
        _issue(result, "error", "read_error", str(exc))
        return result
    if file_path.suffix.lower() in {".yaml", ".yml"}:
        return validate_yaml_text(raw, str(file_path))
    if file_path.suffix.lower() == ".txt":
        return validate_txt_text(raw, str(file_path))
    result = ValidationResult(path=str(file_path), kind="unknown")
    _issue(result, "warning", "unsupported_extension", "only .txt/.yaml/.yml are validated")
    return result


def validate_directory(directory: str | Path = "nodes") -> list[ValidationResult]:
    """Validate all published node artifacts in a directory."""
    root = Path(directory)
    paths = sorted((*root.glob("*.txt"), *root.glob("*.yaml"), *root.glob("*.yml")))
    return [validate_file(path) for path in paths]


def _main() -> int:
    parser = argparse.ArgumentParser(description="Validate FreeNodeSpider node artifacts")
    parser.add_argument("paths", nargs="*", help="files or directories; default: nodes")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = parser.parse_args()

    paths = [Path(value) for value in args.paths] or [Path("nodes")]
    results: list[ValidationResult] = []
    for path in paths:
        if path.is_dir():
            results.extend(validate_directory(path))
        else:
            results.append(validate_file(path))
    if not results:
        print("No .txt/.yaml/.yml files found")
        return 1

    for result in results:
        print(result.render(strict=args.strict))
    return int(any(not result.ok or (args.strict and result.warnings) for result in results))


if __name__ == "__main__":
    raise SystemExit(_main())
