"""Tests for Merger: txt merge, yaml merge, proxy dedup, region detection.

Run: pytest tests/test_merger.py -v
"""
import base64

import pytest
import yaml
from pathlib import Path
from src.merger import Merger, MergeResult, REGION_KEYWORDS
from src.node_probe import ProbeReport, ProbeSettings


# ═══════════════════════════════════════════════════════════════
# _dedup_proxies
# ═══════════════════════════════════════════════════════════════

class TestDedupProxies:

    def test_dedup_by_server_port_type(self):
        proxies = [
            {"name": "HK 01", "server": "1.1.1.1", "port": 443, "type": "vmess"},
            {"name": "HK 01 dup", "server": "1.1.1.1", "port": 443, "type": "vmess"},
        ]
        result = Merger._dedup_proxies(proxies)
        assert len(result) == 1

    def test_preserves_different_proxies(self):
        proxies = [
            {"name": "HK 01", "server": "1.1.1.1", "port": 443, "type": "vmess"},
            {"name": "JP 01", "server": "2.2.2.2", "port": 443, "type": "trojan"},
        ]
        result = Merger._dedup_proxies(proxies)
        assert len(result) == 2

    def test_renames_name_conflict(self):
        proxies = [
            {"name": "HK 01", "server": "1.1.1.1", "port": 443, "type": "vmess"},
            {"name": "HK 01", "server": "2.2.2.2", "port": 443, "type": "trojan"},
        ]
        result = Merger._dedup_proxies(proxies)
        names = [p["name"] for p in result]
        assert "HK 01" in names
        assert "HK 01_2" in names

    def test_renames_three_same_name_proxies_uniquely(self):
        proxies = [
            {"name": "HK 01", "server": "1.1.1.1", "port": 443, "type": "vmess"},
            {"name": "HK 01", "server": "2.2.2.2", "port": 443, "type": "vmess"},
            {"name": "HK 01", "server": "3.3.3.3", "port": 443, "type": "vmess"},
        ]
        result = Merger._dedup_proxies(proxies)
        names = [p["name"] for p in result]
        assert len(names) == len(set(names)) == 3
        assert names == ["HK 01", "HK 01_2", "HK 01_3"]

    def test_reality_fields_remain_strings(self):
        proxies = [{
            "name": "reality",
            "type": "vless",
            "server": "example.com",
            "port": 443,
            "reality-opts": {"public-key": 123, "short-id": "062898e8"},
        }]
        result = Merger._stringify_reality_fields(proxies)
        assert result[0]["reality-opts"]["public-key"] == "123"
        assert result[0]["reality-opts"]["short-id"] == "062898e8"

    def test_keeps_same_endpoint_with_different_credentials(self):
        """Same host/port with different UUIDs are distinct nodes, not duplicates."""
        proxies = [
            {"name": "HK 01", "server": "1.1.1.1", "port": 443, "type": "vless", "uuid": "u1"},
            {"name": "HK 02", "server": "1.1.1.1", "port": 443, "type": "vless", "uuid": "u2"},
        ]
        result = Merger._dedup_proxies(proxies)
        assert len(result) == 2

    def test_keeps_same_endpoint_with_different_transport(self):
        proxies = [
            {"name": "HK 01", "server": "1.1.1.1", "port": 443, "type": "vmess",
             "uuid": "u", "network": "ws", "ws-opts": {"path": "/a"}},
            {"name": "HK 01", "server": "1.1.1.1", "port": 443, "type": "vmess",
             "uuid": "u", "network": "grpc", "grpc-opts": {"grpc-service-name": "x"}},
        ]
        result = Merger._dedup_proxies(proxies)
        assert len(result) == 2

    def test_dedup_ignores_display_name_only(self):
        proxies = [
            {"name": "HK 01", "server": "1.1.1.1", "port": 443, "type": "vmess", "uuid": "u"},
            {"name": "香港 节点", "server": "1.1.1.1", "port": 443, "type": "vmess", "uuid": "u"},
        ]
        result = Merger._dedup_proxies(proxies)
        assert len(result) == 1
        assert result[0]["name"] == "HK 01"

    def test_empty_list(self):
        assert Merger._dedup_proxies([]) == []

    def test_skips_non_dict_items(self):
        deduped = Merger._dedup_proxies([{}, None])
        assert len(deduped) == 0


# ═══════════════════════════════════════════════════════════════
# _detect_regions
# ═══════════════════════════════════════════════════════════════

class TestDetectRegions:

    @staticmethod
    def _detect(names):
        """Helper to call the static method."""
        return Merger._detect_regions(names)

    def test_hk_match(self):
        names = ["HK 01", "香港 02", "HongKong 03", "US 01"]
        regions = self._detect(names)
        assert "🇭🇰 HK 香港" in regions
        assert len(regions["🇭🇰 HK 香港"]) == 3

    def test_us_match(self):
        names = ["US 01", "美国 02", "America 03"]
        regions = self._detect(names)
        assert "🇺🇸 US 美国" in regions
        assert len(regions["🇺🇸 US 美国"]) == 3

    def test_unmatched_goes_to_other(self):
        names = ["zzz-top", "aaaa-bb"]
        regions = self._detect(names)
        assert "🌍 其他" in regions
        assert len(regions["🌍 其他"]) == 2

    def test_case_insensitive(self):
        names = ["hk_01", "Hk_02", "us_03"]
        regions = self._detect(names)
        assert "🇭🇰 HK 香港" in regions
        assert len(regions["🇭🇰 HK 香港"]) == 2

    def test_empty_names(self):
        assert self._detect([]) == {}

    def test_jp_match_via_tokyo(self):
        names = ["Tokyo 01", "TYO 02"]
        regions = self._detect(names)
        assert "🇯🇵 JP 日本" in regions
        assert len(regions["🇯🇵 JP 日本"]) == 2


# ═══════════════════════════════════════════════════════════════
# REGION_KEYWORDS integrity
# ═══════════════════════════════════════════════════════════════

class TestRegionKeywords:

    def test_no_duplicate_keywords_across_regions(self):
        """Each keyword should belong to exactly one region to avoid ambiguity."""
        all_keywords: list[str] = []
        for keywords in REGION_KEYWORDS.values():
            all_keywords.extend(k.lower() for k in keywords)
        assert len(all_keywords) == len(set(all_keywords)), \
            f"duplicate keywords found: {[k for k in all_keywords if all_keywords.count(k) > 1]}"


# ═══════════════════════════════════════════════════════════════
# Integration with real files (requires nodes/ directory)
# ═══════════════════════════════════════════════════════════════

class TestFileIntegration:

    def _site_files(self, nodes: Path):
        # A base64 V2Ray subscription: two distinct nodes plus one republished
        # copy of the first node under a different remark.
        txt_content = base64.b64encode(
            b"vless://418048af-a293-4b99-9b0c-98ca3580dd24@example.com:443?security=tls#HK\n"
            b"vless://418048af-a293-4b99-9b0c-98ca3580dd24@example.com:443?security=tls#%E9%A6%99%E6%B8%AF\n"
            b"vless://518048af-a293-4b99-9b0c-98ca3580dd24@example.org:8443#JP\n"
        ).decode()
        (nodes / "site1.txt").write_text(txt_content, encoding="utf-8")

        yaml_content = """proxies:
  - {name: HK 01, server: 1.1.1.1, port: 443, type: vmess, uuid: 418048af-a293-4b99-9b0c-98ca3580dd24}
  - {name: JP 01, server: 2.2.2.2, port: 443, type: trojan, password: secret}
"""
        (nodes / "site1.yaml").write_text(yaml_content, encoding="utf-8")

    def test_merge_creates_output_files(self, tmp_path):
        """Run merger against a temp directory with sample yaml/txt files."""
        nodes = tmp_path / "nodes"
        nodes.mkdir()
        self._site_files(nodes)

        merger = Merger(nodes_dir=str(nodes))
        result = merger.run()

        assert (nodes / "merged.txt").exists()
        assert (nodes / "merged.yaml").exists()
        assert (nodes / "provider.yaml").exists()
        # Two txt nodes (the duplicate remark collapses) and two yaml proxies.
        assert result.total_nodes == 2

    def test_merge_dedups_republished_txt_node(self, tmp_path):
        nodes = tmp_path / "nodes"
        nodes.mkdir()
        self._site_files(nodes)

        Merger(nodes_dir=str(nodes)).run()

        lines = (nodes / "merged.txt").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        # The first remark seen wins.
        assert lines[0].endswith("#HK")

    def test_merge_empty_dir(self, tmp_path):
        nodes = tmp_path / "nodes"
        nodes.mkdir()
        merger = Merger(nodes_dir=str(nodes))
        result = merger.run()
        assert result.total_nodes == 0
        assert result.merged_txt == ""
        assert result.merged_yaml == ""
        assert result.provider_yaml == ""


# ═══════════════════════════════════════════════════════════════
# MergeResult dataclass
# ═══════════════════════════════════════════════════════════════

class TestProbeFiltering:
    """Probe integration is exercised with a stubbed backend, never the network."""

    @staticmethod
    def _merge(tmp_path, monkeypatch, report: ProbeReport) -> MergeResult:
        nodes = tmp_path / "nodes"
        nodes.mkdir()
        TestFileIntegration()._site_files(nodes)

        async def fake_probe(items, settings):
            return report

        monkeypatch.setattr("src.merger.probe", fake_probe)
        return Merger(nodes_dir=str(nodes), probe_settings=ProbeSettings()).run()

    def test_dead_nodes_are_removed_from_txt_and_yaml(self, tmp_path, monkeypatch):
        report = ProbeReport(backend="tcp", alive=set(), dead=set(), unprobed={"*"})
        # Every node unprobed → nothing is dropped.
        result = self._merge(tmp_path, monkeypatch, report)
        assert result.probe_unprobed == 1
        assert len((tmp_path / "nodes/merged.txt").read_text(encoding="utf-8").splitlines()) == 2

    def test_unavailable_probe_keeps_previous_artifacts_byte_for_byte(
        self, tmp_path, monkeypatch
    ):
        """A probe that cannot run must not overwrite verified artifacts."""
        nodes = tmp_path / "nodes"
        nodes.mkdir()
        TestFileIntegration()._site_files(nodes)

        previous = {
            "merged.txt": "vless://previous@example.com:443#PREV\n",
            "merged.yaml": (
                "proxies:\n"
                "- {name: PREV, type: vless, server: example.com, port: 443, uuid: u}\n"
            ),
            "provider.yaml": "proxy-providers: {}\n",
        }
        for name, content in previous.items():
            (nodes / name).write_text(content, encoding="utf-8")

        async def fake_probe(items, settings):
            return ProbeReport(backend="mihomo", unavailable="binary missing")

        monkeypatch.setattr("src.merger.probe", fake_probe)
        result = Merger(nodes_dir=str(nodes), probe_settings=ProbeSettings()).run()

        assert result.probe_unavailable == "binary missing"
        for name, content in previous.items():
            assert (nodes / name).read_text(encoding="utf-8") == content, name

    def test_unavailable_probe_keeps_all_nodes_when_no_previous_artifacts(
        self, tmp_path, monkeypatch
    ):
        report = ProbeReport(backend="mihomo", unavailable="binary missing")
        result = self._merge(tmp_path, monkeypatch, report)
        assert result.probe_unavailable == "binary missing"
        assert not (tmp_path / "nodes/merged.txt").exists()

    def test_filter_that_would_empty_txt_keeps_it(self, tmp_path, monkeypatch):
        nodes = tmp_path / "nodes"
        nodes.mkdir()
        TestFileIntegration()._site_files(nodes)

        async def fake_probe(items, settings):
            probe_keys = {item.key for item in items}
            return ProbeReport(backend="tcp", dead=probe_keys)

        monkeypatch.setattr("src.merger.probe", fake_probe)
        Merger(nodes_dir=str(nodes), probe_settings=ProbeSettings()).run()

        # Every node is judged dead, but the artifact must not be emptied: the
        # previous merged.txt is kept rather than overwritten with nothing.
        assert len((nodes / "merged.txt").read_text(encoding="utf-8").splitlines()) == 2

    def test_without_probe_settings_no_filtering_happens(self, tmp_path):
        nodes = tmp_path / "nodes"
        nodes.mkdir()
        TestFileIntegration()._site_files(nodes)
        result = Merger(nodes_dir=str(nodes)).run()
        assert result.probe_backend == ""
        assert len((nodes / "merged.txt").read_text(encoding="utf-8").splitlines()) == 2

    def test_partial_filter_keeps_only_alive_nodes(self, tmp_path, monkeypatch):
        nodes = tmp_path / "nodes"
        nodes.mkdir()
        TestFileIntegration()._site_files(nodes)

        async def fake_probe(items, settings):
            keys = {item.key for item in items}
            txt_keys = {key for key in keys if key[0] == "txt"}
            yaml_keys = {key for key in keys if key[0] == "yaml"}
            # Keep one txt node and one yaml proxy, drop the rest.
            return ProbeReport(
                backend="tcp",
                alive={sorted(txt_keys)[0], sorted(yaml_keys)[0]},
                dead=(txt_keys | yaml_keys) - {sorted(txt_keys)[0], sorted(yaml_keys)[0]},
            )

        monkeypatch.setattr("src.merger.probe", fake_probe)
        Merger(nodes_dir=str(nodes), probe_settings=ProbeSettings()).run()

        assert len((nodes / "merged.txt").read_text(encoding="utf-8").splitlines()) == 1
        assert len(yaml.safe_load((nodes / "merged.yaml").read_text(encoding="utf-8"))["proxies"]) == 1


class TestMergeResult:

    def test_defaults(self):
        r = MergeResult()
        assert r.merged_txt == ""
        assert r.total_nodes == 0
        assert r.region_count == {}


# ═══════════════════════════════════════════════════════════════
# Stale artifact filtering (merge.max_node_age_days)
# ═══════════════════════════════════════════════════════════════

class TestStaleArtifacts:

    @staticmethod
    def _write_sites(tmp_path):
        from datetime import date, timedelta
        nodes = tmp_path / "nodes"
        nodes.mkdir()
        (nodes / "fresh.txt").write_text(
            "vless://u1@fresh.example.com:443#FRESH\n", encoding="utf-8"
        )
        (nodes / "old.txt").write_text(
            "vless://u2@old.example.com:443#OLD\n", encoding="utf-8"
        )
        (nodes / "fresh.yaml").write_text(
            "proxies:\n- {name: FRESH, type: vless, server: fresh.example.com, "
            "port: 443, uuid: u1}\n", encoding="utf-8"
        )
        (nodes / "old.yaml").write_text(
            "proxies:\n- {name: OLD, type: vless, server: old.example.com, "
            "port: 443, uuid: u2}\n", encoding="utf-8"
        )
        return nodes, {
            "fresh": date.today().isoformat(),
            "old": (date.today() - timedelta(days=30)).isoformat(),
        }

    def test_stale_txt_and_yaml_are_not_merged(self, tmp_path):
        nodes, dates = self._write_sites(tmp_path)
        Merger(nodes_dir=str(nodes), site_up_dates=dates, max_node_age_days=14).run()

        txt = (nodes / "merged.txt").read_text(encoding="utf-8")
        assert "FRESH" in txt
        assert "OLD" not in txt

        proxies = yaml.safe_load((nodes / "merged.yaml").read_text(encoding="utf-8"))["proxies"]
        assert {p["name"] for p in proxies} == {"FRESH"}

    def test_stale_site_is_not_a_provider(self, tmp_path):
        nodes, dates = self._write_sites(tmp_path)
        Merger(nodes_dir=str(nodes), site_up_dates=dates, max_node_age_days=14).run()
        provider_text = (nodes / "provider.yaml").read_text(encoding="utf-8")
        assert "fresh" in provider_text
        assert "old" not in provider_text

    def test_zero_max_age_disables_filtering(self, tmp_path):
        nodes, dates = self._write_sites(tmp_path)
        Merger(nodes_dir=str(nodes), site_up_dates=dates, max_node_age_days=0).run()
        txt = (nodes / "merged.txt").read_text(encoding="utf-8")
        assert "FRESH" in txt and "OLD" in txt

    def test_missing_up_date_is_not_stale(self, tmp_path):
        nodes, _dates = self._write_sites(tmp_path)
        Merger(nodes_dir=str(nodes), site_up_dates={}, max_node_age_days=1).run()
        txt = (nodes / "merged.txt").read_text(encoding="utf-8")
        assert "FRESH" in txt and "OLD" in txt

    def test_unparsable_up_date_is_not_stale(self, tmp_path):
        nodes, _dates = self._write_sites(tmp_path)
        Merger(
            nodes_dir=str(nodes),
            site_up_dates={"old": "not-a-date", "fresh": "also-bad"},
            max_node_age_days=1,
        ).run()
        txt = (nodes / "merged.txt").read_text(encoding="utf-8")
        assert "OLD" in txt
