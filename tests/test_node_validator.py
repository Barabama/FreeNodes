"""Tests for TXT/YAML proxy artifact validation."""
import base64

from src.node_validator import (
    normalize_yaml_text,
    validate_proxy,
    validate_txt_text,
    validate_yaml_text,
)
from src.pipeline import process_txt


VALID_VMESS = "vmess://" + base64.b64encode(
    b'{"add":"example.com","id":"418048af-a293-4b99-9b0c-98ca3580dd24","port":443}'
).decode()


class TestTxtValidation:
    def test_accepts_common_uri_schemes(self):
        text = "\n".join([
            "vless://418048af-a293-4b99-9b0c-98ca3580dd24@example.com:443?security=tls",
            "trojan://secret@example.com:443?security=tls",
            "hysteria2://secret@example.com:443?sni=example.com",
            "anytls://secret@example.com:443?insecure=1",
            VALID_VMESS,
        ])
        result = validate_txt_text(text)
        assert result.ok
        assert result.stats["valid_lines"] == 5

    def test_accepts_base64_subscription(self):
        raw = base64.b64encode(
            b"vless://418048af-a293-4b99-9b0c-98ca3580dd24@example.com:443\n"
        ).decode()
        result = validate_txt_text(raw)
        assert result.ok
        assert result.stats["base64"] == 1

    def test_rejects_json_fragments_and_unknown_lines(self):
        result = validate_txt_text('{\n"inbounds": [],\n"outbounds": []\n}')
        assert not result.ok
        assert result.stats["valid_lines"] == 0
        assert any(issue.code == "no_proxy_lines" for issue in result.errors)

    def test_pipeline_filters_invalid_lines_and_deduplicates(self):
        raw = "# header\nvless://418048af-a293-4b99-9b0c-98ca3580dd24@example.com:443\nnot a node\nvless://418048af-a293-4b99-9b0c-98ca3580dd24@example.com:443\n"
        assert process_txt(raw).splitlines() == [
            "vless://418048af-a293-4b99-9b0c-98ca3580dd24@example.com:443"
        ]


class TestProxyValidation:
    def test_rejects_zero_port(self):
        proxy = {"name": "bad", "type": "socks5", "server": "@...", "port": 0}
        result = validate_proxy(proxy)
        assert not result.ok
        assert any(issue.code == "invalid_port" for issue in result.errors)

    def test_validates_protocol_specific_fields(self):
        result = validate_proxy({
            "name": "hy2",
            "type": "hysteria2",
            "server": "example.com",
            "port": 443,
            "password": "secret",
        })
        assert result.ok

    def test_rejects_invalid_reality_public_key(self):
        result = validate_proxy({
            "name": "bad-reality",
            "type": "vless",
            "server": "example.com",
            "port": 443,
            "uuid": "418048af-a293-4b99-9b0c-98ca3580dd24",
            "reality-opts": {"public-key": "enabled"},
        })
        assert not result.ok
        assert any(issue.code == "invalid_reality_public_key" for issue in result.errors)

    def test_rejects_non_hex_reality_short_id(self):
        result = validate_proxy({
            "name": "bad-short-id",
            "type": "vless",
            "server": "example.com",
            "port": 443,
            "uuid": "418048af-a293-4b99-9b0c-98ca3580dd24",
            "reality-opts": {
                "public-key": "L3X1eh1Jq_6PKJ6LlwjgiWq0XNaDOqCVKgIElJ5nkVA",
                "short-id": "zzzz",
            },
        })
        assert not result.ok
        assert any(issue.code == "invalid_reality_short_id" for issue in result.errors)

    def test_accepts_hex_reality_short_id(self):
        result = validate_proxy({
            "name": "good-short-id",
            "type": "vless",
            "server": "example.com",
            "port": 443,
            "uuid": "418048af-a293-4b99-9b0c-98ca3580dd24",
            "reality-opts": {
                "public-key": "L3X1eh1Jq_6PKJ6LlwjgiWq0XNaDOqCVKgIElJ5nkVA",
                "short-id": "062898e8",
            },
        })
        assert result.ok

    def test_accepts_valid_reality_public_key(self):
        result = validate_proxy({
            "name": "good-reality",
            "type": "vless",
            "server": "example.com",
            "port": 443,
            "uuid": "418048af-a293-4b99-9b0c-98ca3580dd24",
            "reality-opts": {"public-key": "L3X1eh1Jq_6PKJ6LlwjgiWq0XNaDOqCVKgIElJ5nkVA"},
        })
        assert result.ok

    def test_rejects_vmess_without_uuid(self):
        result = validate_proxy({
            "name": "vmess",
            "type": "vmess",
            "server": "example.com",
            "port": 443,
        })
        assert not result.ok
        assert any(issue.code == "invalid_uuid" for issue in result.errors)


class TestYamlValidation:
    def test_accepts_single_mihomo_document(self):
        text = """proxies:\n  - name: vless\n    type: vless\n    server: example.com\n    port: 443\n    uuid: 418048af-a293-4b99-9b0c-98ca3580dd24\n"""
        result = validate_yaml_text(text)
        assert result.ok
        assert result.stats["proxy_entries"] == 1

    def test_warns_on_multi_document_yaml(self):
        text = """proxies:\n  - name: one\n    type: trojan\n    server: example.com\n    port: 443\n    password: secret\n---\nproxies:\n  - name: two\n    type: trojan\n    server: example.org\n    port: 443\n    password: secret\n"""
        result = validate_yaml_text(text)
        assert result.ok
        assert any(issue.code == "multiple_documents" for issue in result.warnings)

    def test_validates_provider_definitions(self):
        result = validate_yaml_text("""proxy-providers:\n  site:\n    type: file\n    path: ./site.yaml\nproxy-groups: []\nrules: []\n""")
        assert result.ok
        assert result.stats["provider_definitions"] == 1

    def test_normalizes_multi_document_yaml(self):
        raw = """proxies:\n  - name: one\n    type: trojan\n    server: example.com\n    port: 443\n    password: secret\n---\nproxies:\n  - name: two\n    type: trojan\n    server: example.org\n    port: 443\n    password: secret\n"""
        normalized = normalize_yaml_text(raw)
        result = validate_yaml_text(normalized)
        assert result.ok
        assert result.stats["documents"] == 1
        assert result.stats["proxy_entries"] == 2
        assert result.stats["valid_proxy_entries"] == 2

class TestFragmentRepair:
    def test_repairs_params_written_after_hash(self):
        from src.node_validator import _repair_trapped_fragment_params as repair
        fixed = repair("vless://u@h:443?type=tcp#Name&pbk=KEY#Tag")
        assert "&pbk=KEY" in fixed
        assert fixed.endswith("#Tag")

    def test_keeps_single_fragment_untouched(self):
        from src.node_validator import _repair_trapped_fragment_params as repair
        line = "vless://u@h:443?type=tcp#Tag"
        assert repair(line) == line

    def test_repaired_reality_uri_passes_validation(self):
        from src.node_validator import valid_txt_lines
        bad = "vless://418048af-a293-4b99-9b0c-98ca3580dd24@h:443?type=tcp#n&security=reality&pbk=L3X1eh1Jq_6PKJ6LlwjgiWq0XNaDOqCVKgIElJ5nkVA&sid=062898e8#Tag"
        valid, issues = valid_txt_lines(bad)
        assert valid, issues

class TestYamlNameUniqueness:
    def test_normalize_makes_duplicate_names_unique(self):
        from src.node_validator import normalize_yaml_text, validate_yaml_text
        raw = "proxies:\n  - {name: dup, type: trojan, server: a.com, port: 443, password: p}\n  - {name: dup, type: trojan, server: b.com, port: 443, password: p}\n"
        normalized = normalize_yaml_text(raw)
        result = validate_yaml_text(normalized)
        assert result.stats["proxy_entries"] == 2
        import yaml as _yaml
        names = [p["name"] for p in _yaml.safe_load(normalized)["proxies"]]
        assert len(set(names)) == 2

class TestClientFingerprint:
    def test_unsafe_fingerprint_is_dropped(self):
        from src.node_validator import normalize_yaml_text
        raw = "proxies:\n  - {name: n, type: trojan, server: a.com, port: 443, password: p, client-fingerprint: unsafe}\n"
        import yaml as _yaml
        out = _yaml.safe_load(normalize_yaml_text(raw))["proxies"][0]
        assert "client-fingerprint" not in out

    def test_valid_fingerprint_is_kept(self):
        from src.node_validator import normalize_yaml_text
        raw = "proxies:\n  - {name: n, type: trojan, server: a.com, port: 443, password: p, client-fingerprint: chrome}\n"
        import yaml as _yaml
        out = _yaml.safe_load(normalize_yaml_text(raw))["proxies"][0]
        assert out["client-fingerprint"] == "chrome"
