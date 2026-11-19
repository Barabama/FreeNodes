"""Tests for node liveness probing.

These use a local TCP server and a fake HTTP client, so no public node is ever
contacted.
"""
import asyncio
import json

import pytest

from src.node_probe import (
    ProbeItem,
    ProbeReport,
    ProbeSettings,
    probe,
    _probe_tcp,
    _run_delay_checks,
)

pytestmark = pytest.mark.asyncio


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeClient:
    """Stands in for ``httpx.AsyncClient`` in the mihomo delay check."""

    def __init__(self, responses: dict[str, _FakeResponse]):
        self.responses = responses
        self.requested: list[str] = []

    async def get(self, path: str, params=None):
        name = path.split("/")[2]
        self.requested.append(name)
        response = self.responses.get(name)
        if isinstance(response, Exception):
            raise response
        return response or _FakeResponse(404)


class TestProbeReport:

    def test_unavailable_report_keeps_everything(self):
        report = ProbeReport(backend="mihomo", unavailable="no binary")
        assert not report.usable
        assert report.survivor("anything")

    def test_alive_survives_and_dead_does_not(self):
        report = ProbeReport(backend="tcp", alive={"a"}, dead={"b"})
        assert report.usable
        assert report.survivor("a")
        assert not report.survivor("b")

    def test_unprobed_is_never_dropped(self):
        report = ProbeReport(backend="tcp", unprobed={"udp-node"})
        assert report.survivor("udp-node")


class TestTcpProbe:

    async def test_reachable_endpoint_is_alive_and_timed(self):
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            items = [ProbeItem(key="a", host="127.0.0.1", port=port, proxy_type="vless")]
            report = await _probe_tcp(items, ProbeSettings(timeout_ms=2000))
        finally:
            server.close()
            await server.wait_closed()

        assert report.alive == {"a"}
        assert "a" in report.delays

    async def test_closed_port_is_dead(self):
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        server.close()
        await server.wait_closed()

        items = [ProbeItem(key="a", host="127.0.0.1", port=port, proxy_type="vless")]
        report = await _probe_tcp(items, ProbeSettings(timeout_ms=500))
        assert report.dead == {"a"}

    async def test_delay_above_threshold_is_dead(self, monkeypatch):
        async def slow_connect(host, port, timeout):
            return 4000

        monkeypatch.setattr("src.node_probe._tcp_connect", slow_connect)
        items = [ProbeItem(key="a", host="127.0.0.1", port=1, proxy_type="vless")]
        report = await _probe_tcp(items, ProbeSettings(max_delay_ms=3000))
        assert report.dead == {"a"}
        assert report.delays["a"] == 4000

    async def test_delay_at_threshold_is_alive(self, monkeypatch):
        async def borderline_connect(host, port, timeout):
            return 3000

        monkeypatch.setattr("src.node_probe._tcp_connect", borderline_connect)
        items = [ProbeItem(key="a", host="127.0.0.1", port=1, proxy_type="vless")]
        report = await _probe_tcp(items, ProbeSettings(max_delay_ms=3000))
        assert report.alive == {"a"}

    async def test_udp_only_protocol_is_unprobed(self):
        items = [ProbeItem(key="h", host="127.0.0.1", port=1, proxy_type="hysteria2")]
        report = await _probe_tcp(items, ProbeSettings(timeout_ms=100))
        assert report.unprobed == {"h"}
        assert not report.alive
        assert not report.dead

    async def test_endpoint_without_host_is_unprobed(self):
        items = [ProbeItem(key="x", host=None, port=None, proxy_type="vless")]
        report = await _probe_tcp(items, ProbeSettings(timeout_ms=100))
        assert report.unprobed == {"x"}

    async def test_shared_endpoint_is_probed_once(self):
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            items = [
                ProbeItem(key="a", host="127.0.0.1", port=port, proxy_type="vless"),
                ProbeItem(key="b", host="127.0.0.1", port=port, proxy_type="vless"),
            ]
            report = await _probe_tcp(items, ProbeSettings(timeout_ms=2000))
        finally:
            server.close()
            await server.wait_closed()
        assert report.alive == {"a", "b"}


class TestMihomoDelayChecks:

    async def test_successful_delay_is_alive(self):
        client = _FakeClient({"a": _FakeResponse(200, {"delay": 120})})
        report = ProbeReport(backend="mihomo")
        await _run_delay_checks(client, {"a": "key-a"}, report, ProbeSettings(), timeout=1)
        assert report.alive == {"key-a"}
        assert report.delays["key-a"] == 120

    async def test_error_status_is_dead(self):
        client = _FakeClient({"a": _FakeResponse(504)})
        report = ProbeReport(backend="mihomo")
        await _run_delay_checks(client, {"a": "key-a"}, report, ProbeSettings(), timeout=1)
        assert report.dead == {"key-a"}

    async def test_missing_delay_field_is_dead(self):
        client = _FakeClient({"a": _FakeResponse(200, {})})
        report = ProbeReport(backend="mihomo")
        await _run_delay_checks(client, {"a": "key-a"}, report, ProbeSettings(), timeout=1)
        assert report.dead == {"key-a"}

    async def test_transport_error_is_dead(self):
        client = _FakeClient({"a": RuntimeError("boom")})
        report = ProbeReport(backend="mihomo")
        await _run_delay_checks(client, {"a": "key-a"}, report, ProbeSettings(), timeout=1)
        assert report.dead == {"key-a"}

    async def test_delay_above_threshold_is_dead(self):
        client = _FakeClient({"a": _FakeResponse(200, {"delay": 9000})})
        report = ProbeReport(backend="mihomo")
        await _run_delay_checks(
            client, {"a": "key-a"}, report, ProbeSettings(max_delay_ms=3000), timeout=1
        )
        assert report.dead == {"key-a"}

    async def test_zero_delay_is_dead(self):
        client = _FakeClient({"a": _FakeResponse(200, {"delay": 0})})
        report = ProbeReport(backend="mihomo")
        await _run_delay_checks(client, {"a": "key-a"}, report, ProbeSettings(), timeout=1)
        assert report.dead == {"key-a"}


class TestProbeDispatch:

    async def test_unknown_backend_is_unavailable(self):
        report = await probe([], ProbeSettings(backend="nope"))
        assert not report.usable
        assert "unknown probe backend" in report.unavailable

    async def test_missing_mihomo_binary_is_unavailable(self, tmp_path):
        settings = ProbeSettings(backend="mihomo", mihomo_binary=str(tmp_path / "absent"))
        items = [ProbeItem(key="a", proxy={"name": "a", "type": "vmess", "server": "h", "port": 1})]
        report = await probe(items, settings)
        assert not report.usable
        assert "not found" in report.unavailable

    async def test_mihomo_without_proxies_is_a_no_op(self):
        settings = ProbeSettings(backend="mihomo", mihomo_binary="/nonexistent/mihomo")
        report = await probe([ProbeItem(key="udp", proxy_type="wireguard")], settings)
        assert report.usable
        assert report.unprobed == {"udp"}

    async def test_tcp_backend_is_default(self):
        items = [ProbeItem(key="h", host="127.0.0.1", port=1, proxy_type="hysteria2")]
        report = await probe(items, ProbeSettings(timeout_ms=100))
        assert report.backend == "tcp"
        assert report.unprobed == {"h"}
