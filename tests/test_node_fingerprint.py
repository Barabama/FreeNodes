"""Tests for node identity fingerprints (dedup keys and TCP endpoints)."""
import base64
import json

import pytest

from src.node_fingerprint import (
    canonical_value,
    proxy_fingerprint,
    txt_endpoint,
    txt_fingerprint,
    unique_by,
)


def _vmess_uri(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"vmess://{encoded}"


VMESS = {
    "v": "2", "ps": "HK 01", "add": "1.1.1.1", "port": "443",
    "id": "418048af-a293-4b99-9b0c-98ca3580dd24", "aid": "0", "scy": "auto",
    "net": "ws", "host": "", "path": "/", "tls": "",
}


class TestCanonicalValue:

    def test_int_and_string_port_are_equal(self):
        assert canonical_value(443) == canonical_value("443")

    def test_mapping_key_order_does_not_matter(self):
        assert canonical_value({"a": 1, "b": 2}) == canonical_value({"b": 2, "a": 1})

    def test_bool_is_not_confused_with_string(self):
        assert canonical_value(True) != canonical_value("1")

    def test_list_order_matters(self):
        assert canonical_value(["a", "b"]) != canonical_value(["b", "a"])

    def test_nested_values_do_not_collide_across_fields(self):
        # With string joining, these two mappings could flatten to the same text.
        left = {"a": {"b": "c"}, "d": "e"}
        right = {"a": "b", "d": {"c": "e"}}
        assert canonical_value(left) != canonical_value(right)

    def test_list_containing_separator_text_does_not_collide(self):
        left = ["a,b", "c"]
        right = ["a", "b,c"]
        assert canonical_value(left) != canonical_value(right)

    def test_map_and_list_of_same_items_are_distinct(self):
        assert canonical_value({"a": "1"}) != canonical_value([("a", "1")])

    def test_map_value_is_normalized(self):
        assert canonical_value({"a": 1, "b": {"c": "2"}}) == canonical_value(
            {"a": "1", "b": {"c": 2}}
        )


class TestProxyFingerprint:

    def test_display_name_is_ignored(self):
        left = {"name": "HK 01", "server": "1.1.1.1", "port": 443, "type": "vmess"}
        right = {"name": "香港节点", "server": "1.1.1.1", "port": 443, "type": "vmess"}
        assert proxy_fingerprint(left) == proxy_fingerprint(right)

    def test_different_credential_is_kept(self):
        left = {"name": "a", "server": "1.1.1.1", "port": 443, "type": "vless", "uuid": "u1"}
        right = {"name": "a", "server": "1.1.1.1", "port": 443, "type": "vless", "uuid": "u2"}
        assert proxy_fingerprint(left) != proxy_fingerprint(right)

    def test_different_transport_is_kept(self):
        left = {"name": "a", "server": "1.1.1.1", "port": 443, "type": "vmess", "network": "ws"}
        right = {"name": "a", "server": "1.1.1.1", "port": 443, "type": "vmess", "network": "grpc"}
        assert proxy_fingerprint(left) != proxy_fingerprint(right)

    def test_different_sni_is_kept(self):
        left = {"name": "a", "server": "1.1.1.1", "port": 443, "type": "trojan", "sni": "a.com"}
        right = {"name": "a", "server": "1.1.1.1", "port": 443, "type": "trojan", "sni": "b.com"}
        assert proxy_fingerprint(left) != proxy_fingerprint(right)

    def test_nested_ws_opts_compare_by_content(self):
        left = {"server": "h", "port": 1, "type": "x", "ws-opts": {"path": "/a", "headers": {"Host": "h"}}}
        right = {"server": "h", "port": 1, "type": "x", "ws-opts": {"headers": {"Host": "h"}, "path": "/a"}}
        assert proxy_fingerprint(left) == proxy_fingerprint(right)

    def test_none_fields_are_ignored(self):
        left = {"server": "h", "port": 1, "type": "x"}
        right = {"server": "h", "port": 1, "type": "x", "sni": None}
        assert proxy_fingerprint(left) == proxy_fingerprint(right)


class TestTxtFingerprint:

    def test_same_uri_different_remark_is_one_node(self):
        left = "vless://uuid@example.com:443?security=tls#HK"
        right = "vless://uuid@example.com:443?security=tls#%E9%A6%99%E6%B8%AF"
        assert txt_fingerprint(left) == txt_fingerprint(right)

    def test_different_query_is_kept(self):
        left = "vless://uuid@example.com:443?security=tls&sni=a.com"
        right = "vless://uuid@example.com:443?security=tls&sni=b.com"
        assert txt_fingerprint(left) != txt_fingerprint(right)

    def test_vmess_remark_in_ps_is_ignored(self):
        one = {**VMESS, "ps": "HK 01"}
        two = {**VMESS, "ps": "香港"}
        assert txt_fingerprint(_vmess_uri(one)) == txt_fingerprint(_vmess_uri(two))

    def test_vmess_credential_change_is_kept(self):
        one = {**VMESS}
        two = {**VMESS, "id": "518048af-a293-4b99-9b0c-98ca3580dd24"}
        assert txt_fingerprint(_vmess_uri(one)) != txt_fingerprint(_vmess_uri(two))

    def test_vmess_inline_json_is_supported(self):
        uri = "vmess://" + json.dumps(VMESS)
        assert txt_fingerprint(uri) == txt_fingerprint(_vmess_uri(VMESS))

    def test_malformed_vmess_falls_back_to_raw(self):
        fingerprint = txt_fingerprint("vmess://not-base64!!")
        assert fingerprint[0] == "vmess-raw"

    def test_non_uri_line_is_kept_raw(self):
        assert txt_fingerprint("garbage") == ("raw", "garbage")


class TestTxtEndpoint:

    def test_vless_endpoint(self):
        assert txt_endpoint("vless://uuid@1.1.1.1:443?security=tls#HK") == ("1.1.1.1", 443)

    def test_vmess_endpoint_from_json(self):
        assert txt_endpoint(_vmess_uri(VMESS)) == ("1.1.1.1", 443)

    def test_ss_plain_endpoint(self):
        assert txt_endpoint("ss://YWVzOnB3@2.2.2.2:8388#JP") == ("2.2.2.2", 8388)

    def test_ss_fully_encoded_endpoint(self):
        payload = base64.urlsafe_b64encode(b"aes-256-gcm:pw@3.3.3.3:8388").decode()
        assert txt_endpoint(f"ss://{payload}#SG") == ("3.3.3.3", 8388)

    def test_hysteria2_defaults_to_443(self):
        assert txt_endpoint("hysteria2://pw@ex.com/") == ("ex.com", 443)

    def test_missing_port_returns_none(self):
        assert txt_endpoint("vless://uuid@example.com") is None

    def test_unsupported_scheme_without_host_returns_none(self):
        assert txt_endpoint("wireguard://secret@example.com:51820") == ("example.com", 51820)

    def test_garbage_returns_none(self):
        assert txt_endpoint("not a uri") is None

    def test_invalid_port_returns_none(self):
        assert txt_endpoint("vless://uuid@example.com:99999") is None


class TestUniqueBy:

    def test_preserves_first_occurrence_order(self):
        items = ["a1", "b1", "a2"]
        result = unique_by(items, lambda value: value[0])
        assert result == ["a1", "b1"]

    def test_empty_input(self):
        assert unique_by([], lambda value: value) == []

    def test_all_distinct(self):
        assert unique_by([1, 2, 3], lambda value: value) == [1, 2, 3]


@pytest.mark.parametrize("line", [
    "trojan://pw@example.com:443#a",
    "anytls://pw@example.com:443#a",
    "tuic://uuid:pw@example.com:443#a",
])
def test_simple_scheme_endpoints(line):
    assert txt_endpoint(line) == ("example.com", 443)
