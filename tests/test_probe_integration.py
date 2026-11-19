"""End-to-end probe + merge checks against a local TCP listener.

No public node is ever contacted: the "live" endpoint is a local asyncio server
and the "dead" endpoint is a just-freed port.
"""
import asyncio
import socket

import pytest
import yaml

from src.merger import Merger
from src.node_probe import ProbeSettings

pytestmark = pytest.mark.asyncio


def _closed_port() -> int:
    sock = socket.socket()
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        # Windows may let another process (often a proxy client) bind a port
        # right after it is released; exclusive bind avoids handing out a
        # port that is already taken.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def test_tcp_probe_drops_dead_node_and_keeps_unprobed(tmp_path):
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    live = server.sockets[0].getsockname()[1]
    dead = _closed_port()
    # Keep the fixture honest: the port must really be closed at test time.
    probe = socket.socket()
    assert probe.connect_ex(("127.0.0.1", dead)) != 0, "fixture port unexpectedly open"
    probe.close()
    nodes = tmp_path / "nodes"
    nodes.mkdir()
    (nodes / "s.txt").write_text(
        f"vless://u1@127.0.0.1:{live}?security=tls#LIVE\n"
        f"vless://u2@127.0.0.1:{dead}?security=tls#DEAD\n"
        f"hysteria2://pw@127.0.0.1:{dead}#UDP\n",
        encoding="utf-8",
    )
    (nodes / "s.yaml").write_text(
        yaml.safe_dump({"proxies": [
            {"name": "L", "type": "vless", "server": "127.0.0.1", "port": live, "uuid": "u1"},
            {"name": "D", "type": "vless", "server": "127.0.0.1", "port": dead, "uuid": "u2"},
            {"name": "H", "type": "hysteria2", "server": "127.0.0.1", "port": dead, "password": "pw"},
        ]}),
        encoding="utf-8",
    )
    try:
        result = await Merger(
            nodes_dir=str(nodes),
            probe_settings=ProbeSettings(backend="tcp", timeout_ms=1000),
        ).run_async()
    finally:
        server.close()
        await server.wait_closed()

    assert result.probe_backend == "tcp"
    assert result.probe_unavailable == ""

    txt = (nodes / "merged.txt").read_text(encoding="utf-8").splitlines()
    remarks = {line.rsplit("#", 1)[-1] for line in txt}
    assert "LIVE" in remarks
    # UDP-only nodes cannot be judged by a TCP handshake and must survive.
    assert "UDP" in remarks
    assert "DEAD" not in remarks

    proxies = yaml.safe_load((nodes / "merged.yaml").read_text(encoding="utf-8"))["proxies"]
    names = {proxy["name"] for proxy in proxies}
    assert "L" in names
    assert "H" in names
    assert "D" not in names
