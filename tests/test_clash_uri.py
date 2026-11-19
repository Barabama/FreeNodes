"""Tests for URI → Clash proxy conversion used by the mihomo probe backend."""
import base64
import json

import pytest

from src.clash_uri import uri_to_proxy


def _vmess(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"vmess://{encoded}"


class TestVmess:

    def test_basic_fields(self):
        proxy = uri_to_proxy(_vmess({
            "ps": "HK 01", "add": "1.1.1.1", "port": "443",
            "id": "418048af-a293-4b99-9b0c-98ca3580dd24", "aid": "0", "scy": "auto",
        }))
        assert proxy["type"] == "vmess"
        assert proxy["server"] == "1.1.1.1"
        assert proxy["port"] == 443
        assert proxy["uuid"] == "418048af-a293-4b99-9b0c-98ca3580dd24"
        assert proxy["alterId"] == 0

    def test_ws_transport(self):
        proxy = uri_to_proxy(_vmess({
            "ps": "ws", "add": "h", "port": "443", "id": "u",
            "net": "ws", "path": "/ray", "host": "cdn.example.com",
        }))
        assert proxy["network"] == "ws"
        assert proxy["ws-opts"] == {"path": "/ray", "headers": {"Host": "cdn.example.com"}}

    def test_tls_uses_sni(self):
        proxy = uri_to_proxy(_vmess({
            "ps": "tls", "add": "h", "port": "443", "id": "u",
            "tls": "tls", "sni": "sni.example.com",
        }))
        assert proxy["tls"] is True
        assert proxy["servername"] == "sni.example.com"

    def test_missing_required_field_returns_none(self):
        assert uri_to_proxy(_vmess({"ps": "x", "port": "443", "id": "u"})) is None

    def test_invalid_port_returns_none(self):
        assert uri_to_proxy(_vmess({"add": "h", "port": "0", "id": "u"})) is None

    def test_malformed_base64_returns_none(self):
        assert uri_to_proxy("vmess://!!!!") is None

    def test_inline_json_is_supported(self):
        proxy = uri_to_proxy("vmess://" + json.dumps({"add": "h", "port": "443", "id": "u", "ps": "x"}))
        assert proxy["server"] == "h"


class TestVless:

    def test_basic_with_remark(self):
        proxy = uri_to_proxy("vless://uuid@example.com:443?security=tls&sni=s.example.com#JP")
        assert proxy["type"] == "vless"
        assert proxy["uuid"] == "uuid"
        assert proxy["port"] == 443
        assert proxy["name"] == "JP"
        assert proxy["servername"] == "s.example.com"

    def test_ws_transport_options(self):
        proxy = uri_to_proxy(
            "vless://uuid@h:443?type=ws&path=%2Fws&host=cdn.example.com#ws"
        )
        assert proxy["network"] == "ws"
        assert proxy["ws-opts"]["path"] == "/ws"
        assert proxy["ws-opts"]["headers"]["Host"] == "cdn.example.com"

    def test_grpc_transport_options(self):
        proxy = uri_to_proxy("vless://uuid@h:443?type=grpc&serviceName=svc#grpc")
        assert proxy["network"] == "grpc"
        assert proxy["grpc-opts"]["grpc-service-name"] == "svc"

    def test_reality_options(self):
        proxy = uri_to_proxy(
            "vless://uuid@h:443?security=reality&pbk=KEY&sid=abc1&fp=chrome#r"
        )
        assert proxy["reality-opts"] == {"public-key": "KEY", "short-id": "abc1"}
        assert proxy["client-fingerprint"] == "chrome"

    def test_flow_is_preserved(self):
        proxy = uri_to_proxy("vless://uuid@h:443?security=tls&flow=xtls-rprx-vision#x")
        assert proxy["flow"] == "xtls-rprx-vision"

    def test_httpupgrade_maps_to_ws(self):
        proxy = uri_to_proxy("vless://uuid@h:443?type=httpupgrade&path=%2Fup#x")
        assert proxy["network"] == "ws"

    def test_insecure_flag(self):
        proxy = uri_to_proxy("vless://uuid@h:443?security=tls&allowInsecure=1#x")
        assert proxy["skip-cert-verify"] is True

    def test_missing_uuid_returns_none(self):
        assert uri_to_proxy("vless://@h:443") is None

    def test_missing_port_returns_none(self):
        assert uri_to_proxy("vless://uuid@h") is None


class TestTrojan:

    def test_basic(self):
        proxy = uri_to_proxy("trojan://pass@example.com:443?sni=s.example.com#HK")
        assert proxy["type"] == "trojan"
        assert proxy["password"] == "pass"
        assert proxy["sni"] == "s.example.com"

    def test_sni_defaults_to_host(self):
        proxy = uri_to_proxy("trojan://pass@example.com:443")
        assert proxy["sni"] == "example.com"

    def test_ws_transport(self):
        proxy = uri_to_proxy("trojan://pass@h:443?type=ws&path=%2Ft#x")
        assert proxy["network"] == "ws"

    def test_missing_password_returns_none(self):
        assert uri_to_proxy("trojan://example.com:443") is None


class TestShadowsocks:

    def test_sip002_plain_userinfo(self):
        proxy = uri_to_proxy("ss://YWVzLTI1Ni1nY206cHc=@1.1.1.1:8388#SG")
        assert proxy["type"] == "ss"
        assert proxy["cipher"] == "aes-256-gcm"
        assert proxy["password"] == "pw"
        assert proxy["server"] == "1.1.1.1"
        assert proxy["port"] == 8388

    def test_legacy_fully_encoded(self):
        payload = base64.urlsafe_b64encode(b"aes-128-gcm:secret@2.2.2.2:8389").decode()
        proxy = uri_to_proxy(f"ss://{payload}#JP")
        assert proxy["server"] == "2.2.2.2"
        assert proxy["port"] == 8389
        assert proxy["cipher"] == "aes-128-gcm"

    def test_obfs_plugin(self):
        payload = base64.urlsafe_b64encode(b"aes-256-gcm:pw@3.3.3.3:8388").decode()
        proxy = uri_to_proxy(f"ss://{payload}?plugin=obfs-local%3Bobfs%3Dhttp%3Bobfs-host%3Dbing.com#x")
        assert proxy["plugin"] == "obfs"
        assert proxy["plugin-opts"] == {"mode": "http", "host": "bing.com"}

    def test_malformed_payload_returns_none(self):
        assert uri_to_proxy("ss://not_base64_at_all") is None


class TestModernProtocols:

    def test_hysteria2_password_and_sni(self):
        proxy = uri_to_proxy("hysteria2://secret@example.com:8443?sni=s.example.com#hy")
        assert proxy["type"] == "hysteria2"
        assert proxy["port"] == 8443
        assert proxy["password"] == "secret"
        assert proxy["sni"] == "s.example.com"

    def test_hysteria2_obfs(self):
        proxy = uri_to_proxy("hysteria2://pw@h:443?obfs=salamander&obfs-password=x#o")
        assert proxy["obfs"] == "salamander"
        assert proxy["obfs-password"] == "x"

    def test_tuic(self):
        proxy = uri_to_proxy("tuic://uuid:pw@example.com:443?sni=s.example.com#t")
        assert proxy["type"] == "tuic"
        assert proxy["uuid"] == "uuid"
        assert proxy["password"] == "pw"

    def test_anytls(self):
        proxy = uri_to_proxy("anytls://pw@example.com:443?sni=s.example.com#a")
        assert proxy["type"] == "anytls"
        assert proxy["password"] == "pw"

    def test_hysteria(self):
        proxy = uri_to_proxy("hysteria://example.com:443?auth=secret&protocol=udp#h")
        assert proxy["type"] == "hysteria"
        assert proxy["auth-str"] == "secret"

    def test_socks5_with_credentials(self):
        proxy = uri_to_proxy("socks5://user:pass@1.1.1.1:1080#s")
        assert proxy["type"] == "socks5"
        assert proxy["username"] == "user"
        assert proxy["password"] == "pass"


class TestUnsupported:

    @pytest.mark.parametrize("line", [
        "garbage",
        "ssr://abcdef",
        "wireguard://key@host:51820",
        "juicity://uuid@host:443",
    ])
    def test_unsupported_scheme_returns_none(self, line):
        assert uri_to_proxy(line) is None
