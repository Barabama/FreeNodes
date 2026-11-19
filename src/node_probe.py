"""Optional liveness probing for merged nodes.

Two interchangeable backends:

``tcp``
    Opens a TCP connection to each node's ``host:port`` and measures the
    handshake time. Cheap enough to run inside the daily GitHub Action, but it
    only proves the port accepts connections: it does not verify credentials,
    TLS/Reality parameters, or that the proxy actually forwards traffic.

``mihomo``
    Loads the nodes into a local Mihomo instance and asks its RESTful API to
    perform a real HTTP request through each proxy. Closer to what a client
    sees, but requires the Mihomo binary and is far slower.

UDP-only protocols (Hysteria, TUIC, WireGuard…) cannot be judged by a TCP
handshake, so they are reported as *unprobed* and always kept. A backend that
cannot run at all reports ``unavailable``; callers must then keep every node
rather than publishing a filtered list built from a failed probe.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

PROBE_URL = "http://www.gstatic.com/generate_204"

# Protocols whose transport is TCP, so a TCP handshake says something about
# whether the endpoint is up. Everything else is left unprobed on purpose.
TCP_PROBE_TYPES = frozenset({
    "anytls", "http", "https", "naive", "shadowtls", "snell", "socks", "socks5",
    "ss", "ssr", "ssh", "trojan", "vless", "vmess",
})

# Protocol names whose transport is UDP-only. TCP_PROBE_TYPES is the positive
# list; everything else (these included) is never judged by a TCP handshake.
UDP_ONLY_TYPES = frozenset({
    "hysteria", "hysteria2", "hy2", "tuic", "wireguard", "wg", "quic", "mieru", "juicity",
})


@dataclass
class ProbeItem:
    """One node to probe, addressed by a caller-chosen key."""

    key: tuple | str
    host: str | None = None
    port: int | None = None
    proxy: dict | None = None
    proxy_type: str = ""


@dataclass
class ProbeReport:
    """Outcome of one probe run."""

    backend: str
    alive: set = field(default_factory=set)
    dead: set = field(default_factory=set)
    unprobed: set = field(default_factory=set)
    unavailable: str = ""
    delays: dict = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        """Whether the report may be used to filter nodes."""
        return not self.unavailable

    def survivor(self, key) -> bool:
        """Whether a node should survive filtering."""
        if not self.usable:
            return True
        return key in self.alive or key in self.unprobed


@dataclass
class ProbeSettings:
    """Probe tuning, normally built from ``config.yaml``."""

    backend: str = "tcp"
    max_delay_ms: int = 3000
    timeout_ms: int = 5000
    concurrency: int = 32
    mihomo_binary: str = "mihomo"
    url: str = PROBE_URL
    # Whether to refuse targets that are not globally routable. Subscription
    # content is third-party data, so this stays on outside tests.
    require_public_targets: bool = True


# ── Address safety ──
#
# Subscription content is attacker-controlled. Probing it makes the runner open
# outbound connections to whatever address the subscription names, so non-public
# destinations are refused before any connection is attempted.

class UnsafeTargetError(ValueError):
    """Raised when a node points at a non-public address."""


def _is_public_ip(address: str) -> bool:
    """Return whether *address* is a globally routable unicast IP."""
    import ipaddress

    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_reserved
        and not ip.is_multicast
        and not ip.is_unspecified
    )


async def resolve_target(host: str, require_public: bool = True) -> tuple[list[str] | None, bool]:
    """Resolve *host* into connectable addresses.

    Returns ``(addresses, unsafe)``:

    * ``(list, False)`` — resolved (or a literal IP) and allowed.
    * ``(None, True)``  — refused by policy: a non-public destination.
    * ``(None, False)`` — nothing to connect to (DNS failure, empty host).

    With *require_public*, every resolved address must be globally routable. A
    hostname answering with any private address is rejected whole, so a DNS
    response cannot steer the probe onto a local network.
    """
    import ipaddress

    stripped = host.strip()
    if not stripped:
        return None, False
    try:
        literal = ipaddress.ip_address(stripped)
    except ValueError:
        literal = None
    if literal is not None:
        if require_public and not _is_public_ip(str(literal)):
            return None, True
        return [str(literal)], False

    try:
        encoded = stripped.encode("idna").decode("ascii")
    except UnicodeError:
        return None, False
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(encoded, None, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return None, False
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        return None, False
    if require_public and not all(_is_public_ip(address) for address in addresses):
        return None, True
    return addresses, False


async def _tcp_connect(host: str, port: int, timeout: float,
                       require_public: bool = True) -> int | None:
    """Return connect time in milliseconds, or ``None`` when unreachable.

    Resolves the host once, optionally verifies every address is public, then
    connects to those verified addresses only — the name is never re-resolved
    during connect, so a second DNS answer cannot redirect the probe.

    Raises ``UnsafeTargetError`` for a refused destination, which callers treat
    as "cannot judge" rather than "dead".
    """
    addresses, unsafe = await resolve_target(host, require_public=require_public)
    if unsafe:
        raise UnsafeTargetError(f"refusing non-public target: {host}")
    if not addresses:
        return None

    started = time.perf_counter()
    for address in addresses:
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(address, port), timeout=timeout
            )
        except (OSError, asyncio.TimeoutError):
            continue
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, asyncio.TimeoutError):
            pass
        return elapsed_ms
    return None


def _tcp_target(item: ProbeItem) -> tuple[str, int] | None:
    """Resolve the ``host:port`` a TCP handshake would test, or ``None``.

    TXT entries carry a parsed endpoint; YAML entries carry a proxy mapping and
    no separate endpoint, so they fall back to ``server``/``port``.

    Only node types known to use TCP are probed. A failed handshake proves
    nothing about a UDP-only endpoint and an unknown protocol is a guess, so in
    both cases the node is left unprobed and therefore kept.
    """
    if item.proxy_type in UDP_ONLY_TYPES:
        return None
    if item.proxy_type and item.proxy_type not in TCP_PROBE_TYPES:
        return None
    if item.host and item.port:
        return item.host, item.port
    if item.proxy:
        server, port = item.proxy.get("server"), item.proxy.get("port")
        if isinstance(server, str) and server.strip() and port is not None:
            try:
                port_number = int(port)
            except (TypeError, ValueError):
                return None
            if 1 <= port_number <= 65535:
                return server.strip(), port_number
    return None


async def _probe_tcp(items: list[ProbeItem], settings: ProbeSettings) -> ProbeReport:
    report = ProbeReport(backend="tcp")
    # Many publishers repeat the same endpoint under different names; probe
    # each endpoint once and fan the result back out.
    endpoint_keys: dict[tuple[str, int], list[str]] = {}
    for item in items:
        target = _tcp_target(item)
        if target is None:
            report.unprobed.add(item.key)
            continue
        host, port = target[0].lower(), target[1]
        endpoint_keys.setdefault((host, port), []).append(item.key)

    semaphore = asyncio.Semaphore(max(1, settings.concurrency))
    timeout = settings.timeout_ms / 1000

    async def probe_endpoint(endpoint: tuple[str, int]) -> tuple[tuple[str, int], int | None, bool]:
        async with semaphore:
            try:
                delay = await _tcp_connect(
                    *endpoint,
                    timeout=timeout,
                    require_public=settings.require_public_targets,
                )
            except UnsafeTargetError:
                return endpoint, None, True
            return endpoint, delay, False

    results = await asyncio.gather(*(probe_endpoint(e) for e in endpoint_keys))
    for endpoint, delay, unsafe in results:
        keys = endpoint_keys[endpoint]
        if unsafe:
            # A non-public target proves nothing about the node; keep it.
            report.unprobed.update(keys)
            continue
        if delay is None:
            report.dead.update(keys)
            continue
        for key in keys:
            report.delays[key] = delay
        if delay <= settings.max_delay_ms:
            report.alive.update(keys)
        else:
            report.dead.update(keys)
    return report


# ── Mihomo backend ──

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _mihomo_config(proxies: list[dict], mixed_port: int, controller_port: int, secret: str) -> str:
    import yaml

    names = [proxy["name"] for proxy in proxies]
    config = {
        "mixed-port": mixed_port,
        "external-controller": f"127.0.0.1:{controller_port}",
        "secret": secret,
        "allow-lan": False,
        "mode": "global",
        "log-level": "silent",
        "proxies": proxies,
        "proxy-groups": [{"name": "PROBE", "type": "select", "proxies": names}],
        "rules": ["MATCH,PROBE"],
    }
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


async def _wait_for_controller(client, deadline: float) -> bool:
    while time.perf_counter() < deadline:
        try:
            response = await client.get("/version")
            if response.status_code == 200:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.25)
    return False


async def _probe_mihomo(items: list[ProbeItem], settings: ProbeSettings) -> ProbeReport:
    import httpx

    report = ProbeReport(backend="mihomo")
    # Mihomo would happily dial whatever the subscription names, so only nodes
    # whose server resolves to a public address are handed to it.
    candidates = [item for item in items if item.proxy]
    for item in items:
        if not item.proxy:
            report.unprobed.add(item.key)

    if not candidates:
        return report

    binary = Path(settings.mihomo_binary)
    if not binary.exists() and not _which(settings.mihomo_binary):
        report.unavailable = f"mihomo binary not found: {settings.mihomo_binary}"
        return report

    server_checks = await asyncio.gather(*(
        resolve_target(
            str(item.proxy.get("server", "")),
            require_public=settings.require_public_targets,
        )
        for item in candidates
    ))
    allowed = [item for item, (addresses, _unsafe) in zip(candidates, server_checks) if addresses]
    for item, (addresses, _unsafe) in zip(candidates, server_checks):
        if not addresses:
            report.unprobed.add(item.key)
    if not allowed:
        return report
    candidates = allowed
    proxies = [item.proxy for item in candidates]
    name_to_key = {item.proxy["name"]: item.key for item in candidates}
    mixed_port, controller_port = _free_port(), _free_port()
    secret = os.urandom(8).hex()
    timeout = settings.timeout_ms / 1000

    with tempfile.TemporaryDirectory(prefix="fns-probe-") as temp_dir:
        config_path = Path(temp_dir) / "config.yaml"
        config_path.write_text(
            _mihomo_config(proxies, mixed_port, controller_port, secret),
            encoding="utf-8",
        )
        process = await _spawn_mihomo(settings.mihomo_binary, config_path)
        if process is None:
            report.unavailable = f"failed to start mihomo: {settings.mihomo_binary}"
            return report
        try:
            headers = {"Authorization": f"Bearer {secret}"}
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{controller_port}",
                headers=headers,
                timeout=timeout + 5,
            ) as client:
                if not await _wait_for_controller(client, time.perf_counter() + 30):
                    report.unavailable = "mihomo API did not become ready"
                    return report
                await _run_delay_checks(client, name_to_key, report, settings, timeout)
        finally:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
    return report


def _which(binary: str) -> str | None:
    from shutil import which

    return which(binary)


async def _spawn_mihomo(binary: str, config_path: Path):
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        return await asyncio.create_subprocess_exec(
            binary, "-f", str(config_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            **kwargs,
        )
    except OSError:
        return None


async def _run_delay_checks(client, name_to_key: dict[str, str], report: ProbeReport,
                            settings: ProbeSettings, timeout: float) -> None:
    semaphore = asyncio.Semaphore(max(1, settings.concurrency))

    async def check(name: str, key: str) -> None:
        async with semaphore:
            path = f"/proxies/{quote(name, safe='')}/delay"
            params = {"url": settings.url, "timeout": int(timeout * 1000)}
            try:
                response = await client.get(path, params=params)
            except Exception:
                report.dead.add(key)
                return
            if response.status_code != 200:
                report.dead.add(key)
                return
            try:
                delay = int(response.json().get("delay"))
            except (ValueError, TypeError, json.JSONDecodeError):
                report.dead.add(key)
                return
            if 0 < delay <= settings.max_delay_ms:
                report.alive.add(key)
                report.delays[key] = delay
            else:
                report.dead.add(key)

    await asyncio.gather(*(check(name, key) for name, key in name_to_key.items()))


# ── Entry point ──

async def probe(items: list[ProbeItem], settings: ProbeSettings) -> ProbeReport:
    """Probe *items* with the configured backend.

    Never raises for environmental problems: an unusable backend comes back as
    ``ProbeReport.unavailable`` so the caller can keep the previous artifacts.
    """
    backend = (settings.backend or "tcp").strip().lower()
    if backend == "tcp":
        return await _probe_tcp(items, settings)
    if backend == "mihomo":
        try:
            return await _probe_mihomo(items, settings)
        except Exception as exc:  # pragma: no cover - environmental failure
            return ProbeReport(backend="mihomo", unavailable=str(exc))
    return ProbeReport(backend=backend, unavailable=f"unknown probe backend: {backend}")