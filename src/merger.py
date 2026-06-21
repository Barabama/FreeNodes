"""Merger — cross-site dedup, physical merge, and proxy-provider YAML generation.

Three output modes:
  1. merged.txt       — all V2Ray txt files deduped and concatenated
  2. merged.yaml      — physical merge of all Clash yaml files
  3. provider.yaml    — proxy-provider based config (references each site file)
"""
import base64
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class MergeResult:
    merged_txt: str = ""
    merged_yaml: str = ""
    provider_yaml: str = ""
    total_nodes: int = 0
    txt_sources: int = 0
    yaml_sources: int = 0
    region_count: dict[str, int] = field(default_factory=dict)


REGION_KEYWORDS: dict[str, list[str]] = {
    "🇭🇰 HK 香港": ["香港", "HK", "Hong Kong", "HongKong", "HKG"],
    "🇯🇵 JP 日本": ["日本", "JP", "Japan", "TYO", "Tokyo", "Osaka", "NRT"],
    "🇺🇸 US 美国": ["美国", "US", "United States", "USA", "America", "LAX", "SJC"],
    "🇸🇬 SG 新加坡": ["新加坡", "SG", "Singapore"],
    "🇰🇷 KR 韩国": ["韩国", "KR", "Korea", "Seoul", "ICN"],
    "🇹🇼 TW 台湾": ["台湾", "TW", "Taiwan", "Taipei", "TPE"],
    "🇨🇦 CA 加拿大": ["加拿大", "CA", "Canada", "Toronto", "YVR", "YYZ"],
    "🇬🇧 GB 英国": ["英国", "GB", "UK", "United Kingdom", "London", "LHR"],
    "🇩🇪 DE 德国": ["德国", "DE", "Germany", "Frankfurt", "FRA"],
    "🇫🇷 FR 法国": ["法国", "FR", "France", "Paris"],
    "🇦🇺 AU 澳大利亚": ["澳大利亚", "AU", "Australia", "Sydney", "SYD"],
    "🇳🇱 NL 荷兰": ["荷兰", "NL", "Netherlands", "Amsterdam"],
    "🇷🇺 RU 俄罗斯": ["俄罗斯", "RU", "Russia", "Moscow"],
    "🇮🇳 IN 印度": ["印度", "IN", "India", "Mumbai", "BOM"],
    "🇪🇺 EU 欧洲": ["欧洲", "EU", "Europe"],
}


class Merger:
    """Merge site output files into cross-site aggregated files."""

    def __init__(self, nodes_dir: str = "nodes"):
        self.nodes_dir = Path(nodes_dir)

    def run(self) -> MergeResult:
        """Run all three merge stages and return results."""
        result = MergeResult()
        result.merged_txt = self._merge_txt(result)
        result.merged_yaml = self._merge_yaml(result)
        result.provider_yaml = self._build_provider(result)
        self._print_summary(result)
        return result

    # ── TXT merge ──

    def _merge_txt(self, result: MergeResult) -> str:
        """Concatenate all .txt files, dedup by line hash."""
        all_lines: list[str] = []
        seen: set[str] = set()

        for f in sorted(self.nodes_dir.glob("*.txt")):
            if f.name == "merged.txt":
                continue
            result.txt_sources += 1
            try:
                raw = f.read_text(encoding="utf-8", errors="replace")
                # Base64 decode if possible (standard V2Ray sub encoding)
                try:
                    decoded = base64.b64decode(raw).decode("utf-8", errors="replace")
                except Exception:
                    decoded = raw
                for line in decoded.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    h = hashlib.md5(line.encode()).hexdigest()
                    if h not in seen:
                        seen.add(h)
                        all_lines.append(line)
                        result.total_nodes += 1
            except Exception as e:
                print(f"  [merger] txt skip {f.name}: {e}")

        if not all_lines:
            return ""

        txt = "\n".join(all_lines)
        out = self.nodes_dir / "merged.txt"
        out.write_text(txt, encoding="utf-8")
        print(f"  [merger] merged.txt: {result.txt_sources} files, {result.total_nodes} nodes")
        return str(out)

    # ── YAML physical merge ──

    def _merge_yaml(self, result: MergeResult) -> str:
        """Extract proxies from all .yaml files, dedup, rebuild groups."""
        import yaml

        all_proxies: list[dict] = []
        for f in sorted(self.nodes_dir.glob("*.yaml")):
            if f.name in ("merged.yaml", "provider.yaml"):
                continue
            result.yaml_sources += 1
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                for doc in yaml.safe_load_all(text):
                    if isinstance(doc, dict) and "proxies" in doc:
                        all_proxies.extend(doc["proxies"])
            except Exception as e:
                print(f"  [merger] yaml skip {f.name}: {e}")

        if not all_proxies:
            return ""

        proxies = self._dedup_proxies(all_proxies)
        proxy_names = [p["name"] for p in proxies]
        groups = self._build_default_groups(proxy_names)

        output = self._base_clash_config(proxies=proxies, groups=groups)

        yaml_text = yaml.safe_dump(output, allow_unicode=True, default_flow_style=False)
        out = self.nodes_dir / "merged.yaml"
        out.write_text(self._header(f"Merged {result.yaml_sources} yaml files") + yaml_text, encoding="utf-8")
        print(f"  [merger] merged.yaml: {result.yaml_sources} files, {len(proxies)} proxies")
        return str(out)

    # ── Provider YAML ──

    def _build_provider(self, result: MergeResult) -> str:
        """Build a Clash Meta config using proxy-provider references."""
        import yaml

        yaml_files = sorted(f for f in self.nodes_dir.glob("*.yaml")
                           if f.name not in ("merged.yaml", "provider.yaml"))
        if not yaml_files:
            return ""

        # proxy-providers
        providers: dict[str, dict] = {}
        for f in yaml_files:
            name = f.stem
            providers[name] = {
                "type": "file",
                "path": f"./nodes/{f.name}",
                "health-check": {
                    "enable": True,
                    "url": "http://www.gstatic.com/generate_204",
                    "interval": 300,
                },
            }

        # Collect all proxy names for grouping
        all_names: list[str] = []
        for f in yaml_files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                for doc in yaml.safe_load_all(text):
                    if isinstance(doc, dict):
                        for p in doc.get("proxies", []):
                            all_names.append(p.get("name", ""))
            except Exception as e:
                print(f"  [merger] warning: {f.name} parse skipped ({e})")
                continue

        regions = self._detect_regions(all_names)
        result.region_count = {k: len(v) for k, v in regions.items()}

        provider_list = list(providers.keys())
        groups: list[dict] = []

        # region-based groups
        for region, names in sorted(regions.items()):
            if len(names) < 2 or region not in REGION_KEYWORDS:
                continue
            groups.append({
                "name": region,
                "type": "url-test",
                "use": provider_list,
                "include": f"({'|'.join(REGION_KEYWORDS[region])})",
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
            })

        # auto select group (contains all region groups + all provider nodes)
        auto_includes = [g["name"] for g in groups]
        select_use = provider_list[:]

        groups.append({
            "name": "🚀 自动选择",
            "type": "url-test",
            "use": select_use,
            "url": "http://www.gstatic.com/generate_204",
            "interval": 300,
        })

        select_entries: list[str] = ["🚀 自动选择"] + auto_includes
        groups.append({
            "name": "🌍 手动选择",
            "type": "select",
            "proxies": select_entries,
        })

        output = self._base_clash_config(groups=groups, providers=providers)

        yaml_text = yaml.safe_dump(output, allow_unicode=True, default_flow_style=False)
        out = self.nodes_dir / "provider.yaml"
        out.write_text(self._header("Proxy-provider based config (for Clash Meta / Mihomo)") + yaml_text, encoding="utf-8")
        print(f"  [merger] provider.yaml: {len(yaml_files)} providers, {len(regions)} regions")
        return str(out)

    # ── Helpers ──

    @staticmethod
    def _dedup_proxies(proxies: list[dict]) -> list[dict]:
        """Deduplicate by server:port:type; rename name collisions with _N suffix."""
        seen_key: set[str] = set()
        seen_name: set[str] = set()
        result: list[dict] = []
        name_counter: dict[str, int] = {}

        for p in proxies:
            if not isinstance(p, dict):
                continue
            key = f"{p.get('server', '')}:{p.get('port', '')}:{p.get('type', '')}"
            if key == "::" or key in seen_key:
                continue
            seen_key.add(key)

            name = p.get("name", "unknown")
            if name in seen_name:
                name_counter[name] = name_counter.get(name, 1) + 1
                name = f"{name}_{name_counter[name]}"
            else:
                seen_name.add(name)

            p["name"] = name
            result.append(p)

        return result

    @staticmethod
    def _build_default_groups(names: list[str]) -> list[dict]:
        """Build two default proxy groups: url-test + select."""
        return [
            {
                "name": "🚀 自动选择",
                "type": "url-test",
                "proxies": names,
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
            },
            {
                "name": "🌍 手动选择",
                "type": "select",
                "proxies": ["🚀 自动选择"] + names,
            },
        ]

    @staticmethod
    def _detect_regions(names: list[str]) -> dict[str, list[str]]:
        """Group proxy names by region keywords.

        Returns dict of region_label -> [proxy_name].
        Unmatched names go into "🌍 其他".
        """
        regions: dict[str, list[str]] = {}
        for name in names:
            matched = False
            for region, keywords in REGION_KEYWORDS.items():
                if any(k.lower() in name.lower() for k in keywords):
                    regions.setdefault(region, []).append(name)
                    matched = True
                    break
            if not matched:
                regions.setdefault("🌍 其他", []).append(name)
        return {k: v for k, v in sorted(regions.items()) if v}

    @staticmethod
    def _header(desc: str) -> str:
        """Generate a YAML comment header."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"# FreeNodeSpider - {desc}\n"
            f"# Generated: {now}\n"
            f"# Docs: https://github.com/FreeNodeSpider\n"
            f"# {'-'*60}\n"
        )

    @staticmethod
    def _base_clash_config(groups: list[dict], proxies: list[dict] | None = None,
                           providers: dict | None = None) -> dict:
        """Return shared Clash base config dict.

        Used by both ``_merge_yaml`` and ``_build_provider``.
        """
        config = {
            "mixed-port": 7890,
            "allow-lan": True,
            "mode": "rule",
            "log-level": "info",
            "ipv6": True,
            "dns": {
                "enable": True,
                "listen": "0.0.0.0:53",
                "default-nameserver": ["223.5.5.5", "114.114.114.114"],
                "nameserver": ["https://doh.pub/dns-query", "https://dns.alidns.com/dns-query"],
            },
            "proxy-groups": groups,
            "rules": ["MATCH,🌍 手动选择"],
        }
        if proxies is not None:
            config["proxies"] = proxies
        if providers is not None:
            config["proxy-providers"] = providers
        return config

    @staticmethod
    def _print_summary(result: MergeResult):
        if result.region_count:
            print("  [merger] region distribution:")
            for region, count in sorted(result.region_count.items(),
                                         key=lambda x: -x[1]):
                print(f"    {region}: {count} nodes")
