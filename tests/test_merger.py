"""Tests for Merger: txt merge, yaml merge, proxy dedup, region detection.

Run: pytest tests/test_merger.py -v
"""
import yaml
from pathlib import Path
from src.merger import Merger, MergeResult, REGION_KEYWORDS


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

    def test_merge_creates_output_files(self, tmp_path):
        """Run merger against a temp directory with sample yaml/txt files."""
        nodes = tmp_path / "nodes"
        nodes.mkdir()

        # Create a sample txt file (base64 encoded V2Ray sub)
        import base64
        txt_content = base64.b64encode(
            b"vmess://abc-line-1\nvmess://def-line-2\n"
        ).decode()
        (nodes / "site1.txt").write_text(txt_content, encoding="utf-8")

        # Create a sample yaml file
        yaml_content = """proxies:
  - {name: HK 01, server: 1.1.1.1, port: 443, type: vmess}
  - {name: JP 01, server: 2.2.2.2, port: 443, type: trojan}
"""
        (nodes / "site1.yaml").write_text(yaml_content, encoding="utf-8")

        merger = Merger(nodes_dir=str(nodes))
        result = merger.run()

        assert (nodes / "merged.txt").exists()
        assert (nodes / "merged.yaml").exists()
        assert (nodes / "provider.yaml").exists()
        assert result.total_nodes == 2

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

class TestMergeResult:

    def test_defaults(self):
        r = MergeResult()
        assert r.merged_txt == ""
        assert r.total_nodes == 0
        assert r.region_count == {}
