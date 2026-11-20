"""Merger — cross-site dedup, physical merge, and proxy-provider YAML generation.

Three output modes:
  1. merged.txt       — all V2Ray txt files deduped and concatenated
  2. merged.yaml      — physical merge of all Clash yaml files
  3. provider.yaml    — proxy-provider based config (references each site file)

Deduplication follows the connection configuration (see ``node_fingerprint``),
so the same node republished under different display names collapses into one
entry, while nodes that differ in credentials or transport options are kept.

Merged artifacts are optionally filtered by a liveness probe. When the probe
cannot run, or it would remove every node, the previous artifacts are left in
place instead of publishing an empty subscription.
"""
import asyncio
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from src.clash_uri import uri_to_proxy
from src.node_fingerprint import proxy_fingerprint, txt_endpoint, txt_fingerprint, unique_by, uri_scheme
from src.node_probe import ProbeItem, ProbeReport, ProbeSettings, probe
from src.node_validator import force_string_proxy_fields, make_safe_dumper, validate_proxy, valid_txt_lines

# Windows console uses GBK which can't encode flag emoji in region names.
# Force UTF-8 output with replacement chars instead of crashing.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


@dataclass
class MergeResult:
    merged_txt: str = ""
    merged_yaml: str = ""
    provider_yaml: str = ""
    total_nodes: int = 0
    txt_sources: int = 0
    yaml_sources: int = 0
    region_count: dict[str, int] = field(default_factory=dict)
    probe_backend: str = ""
    probe_alive: int = 0
    probe_dead: int = 0
    probe_unprobed: int = 0
    probe_unavailable: str = ""


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

    def __init__(self, nodes_dir: str = "nodes", probe_settings: ProbeSettings | None = None,
                 site_up_dates: dict[str, str] | None = None,
                 max_node_age_days: int = 0):
        self.nodes_dir = Path(nodes_dir)
        self.probe_settings = probe_settings
        self.site_up_dates = site_up_dates or {}
        self.max_node_age_days = max_node_age_days
        self._stale_reported: set[str] = set()

    def _is_stale(self, filename: str) -> bool:
        """Whether a per-site artifact is older than the configured age limit.

        Age is taken from ``config.yaml``'s ``up_date`` (the last successful
        crawl), not from the file mtime: CI checks out every file at once, so
        mtimes say nothing about when the data was actually collected.
        """
        if self.max_node_age_days <= 0:
            return False
        up_date = self.site_up_dates.get(Path(filename).stem)
        if not up_date:
            return False
        try:
            last = date.fromisoformat(up_date[:10])
        except ValueError:
            return False
        return (date.today() - last).days > self.max_node_age_days

    def _skip_stale(self, filename: str) -> bool:
        if not self._is_stale(filename):
            return False
        if filename not in self._stale_reported:
            self._stale_reported.add(filename)
            up_date = self.site_up_dates.get(Path(filename).stem, "?")
            print(f"  [merger] skip stale {filename} (last crawl {up_date})")
        return True

    def run(self) -> MergeResult:
        """Run all three merge stages synchronously (CLI, tests)."""
        return asyncio.run(self.run_async())

    async def run_async(self) -> MergeResult:
        """Run the merge inside an existing event loop (Scheduler / asyncio)."""
        result = MergeResult()
        txt_lines = self._collect_txt_lines(result)
        yaml_proxies = self._collect_yaml_proxies(result)

        report = await self._probe(txt_lines, yaml_proxies, result)
        if report is not None:
            if not report.usable:
                # A probe that cannot run must not replace verified artifacts
                # with an unverified list.
                print("  [merger] probe unavailable — keeping previous merged artifacts")
                result.merged_txt = str(self.nodes_dir / "merged.txt")
                result.merged_yaml = str(self.nodes_dir / "merged.yaml")
                result.provider_yaml = str(self.nodes_dir / "provider.yaml")
                self._print_summary(result)
                return result
            txt_lines, yaml_proxies = self._filter_nodes(txt_lines, yaml_proxies, report, result)

        result.merged_txt = self._write_txt(txt_lines, result)
        result.merged_yaml = self._write_yaml(yaml_proxies, result)
        result.provider_yaml = self._build_provider(result)
        self._print_summary(result)
        return result

    # ── Collection ──

    def _collect_txt_lines(self, result: MergeResult) -> list[str]:
        """Read every .txt source, validate, and dedup by node fingerprint."""
        all_lines: list[str] = []

        for f in sorted(self.nodes_dir.glob("*.txt")):
            if f.name == "merged.txt":
                continue
            if self._skip_stale(f.name):
                continue
            result.txt_sources += 1
            try:
                raw = f.read_text(encoding="utf-8", errors="replace")
                # Decode base64 subscriptions and reject comments, JSON/YAML
                # configuration fragments, and malformed protocol lines.
                valid_lines, issues = valid_txt_lines(raw)
                if issues:
                    print(f"  [merger] txt filtered {f.name}: {len(issues)} invalid lines")
                all_lines.extend(valid_lines)
            except Exception as e:
                print(f"  [merger] txt skip {f.name}: {e}")

        unique = unique_by(all_lines, txt_fingerprint)
        result.total_nodes = len(unique)
        return unique

    def _collect_yaml_proxies(self, result: MergeResult) -> list[dict]:
        """Read every .yaml source and validate individual proxies."""
        import yaml

        all_proxies: list[dict] = []
        for f in sorted(self.nodes_dir.glob("*.yaml")):
            if f.name in ("merged.yaml", "provider.yaml"):
                continue
            if self._skip_stale(f.name):
                continue
            result.yaml_sources += 1
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                for doc in yaml.safe_load_all(text):
                    if not isinstance(doc, dict) or not isinstance(doc.get("proxies"), list):
                        continue
                    for index, proxy in enumerate(doc["proxies"], 1):
                        if validate_proxy(proxy, f"{f.name}.proxies[{index}]", strict=False).ok:
                            all_proxies.append(proxy)
                        else:
                            print(f"  [merger] yaml filtered invalid proxy in {f.name} at index {index}")
            except Exception as e:
                print(f"  [merger] yaml skip {f.name}: {e}")

        return self._dedup_proxies(all_proxies)

    # ── Probing ──

    async def _probe(self, txt_lines: list[str], yaml_proxies: list[dict],
                     result: MergeResult) -> ProbeReport | None:
        """Probe nodes when enabled; return ``None`` when probing is off."""
        if self.probe_settings is None:
            return None

        convert_txt = (self.probe_settings.backend or "tcp").strip().lower() == "mihomo"
        items = self._probe_items(txt_lines, yaml_proxies, convert_txt=convert_txt)
        report = await probe(items, self.probe_settings)
        result.probe_backend = report.backend
        result.probe_alive = len(report.alive)
        result.probe_dead = len(report.dead)
        result.probe_unprobed = len(report.unprobed)
        result.probe_unavailable = report.unavailable
        if report.unavailable:
            print(f"  [merger] probe ({report.backend}) unavailable: {report.unavailable}")
        else:
            print(f"  [merger] probe ({report.backend}): {len(report.alive)} alive, "
                  f"{len(report.dead)} dead, {len(report.unprobed)} unprobed")
        return report

    @staticmethod
    def _probe_items(txt_lines: list[str], yaml_proxies: list[dict],
                     convert_txt: bool = False) -> list[ProbeItem]:
        """Index probe targets the same way filtering will look them up.

        YAML proxies are always addressable (they carry server/port). TXT lines
        only need Clash conversion for the mihomo backend, so the default TCP
        path skips it. A line that cannot be converted stays unprobed rather
        than being treated as dead. Proxy names are made unique because Mihomo
        refuses a config with duplicate names; the fingerprint ignores names, so
        renaming never affects the keys used for filtering.
        """
        items: list[ProbeItem] = []
        used_names: set[str] = set()

        def unique_name(name: str) -> str:
            candidate = name or "node"
            index = 1
            while candidate in used_names:
                index += 1
                candidate = f"{name}_{index}"
            used_names.add(candidate)
            return candidate

        for proxy in yaml_proxies:
            items.append(ProbeItem(
                key=_yaml_key(proxy),
                proxy={**proxy, "name": unique_name(proxy.get("name", ""))},
                proxy_type=str(proxy.get("type", "")).lower(),
            ))
        for line in txt_lines:
            endpoint = txt_endpoint(line)
            host, port = endpoint if endpoint else (None, None)
            proxy = uri_to_proxy(line) if convert_txt else None
            if proxy is not None:
                proxy = {**proxy, "name": unique_name(proxy.get("name", ""))}
            items.append(ProbeItem(
                key=_txt_key(line),
                host=host,
                port=port,
                proxy=proxy,
                proxy_type=uri_scheme(line) or "",
            ))
        return items

    def _filter_nodes(self, txt_lines: list[str], yaml_proxies: list[dict],
                      report: ProbeReport, result: MergeResult) -> tuple[list[str], list[dict]]:
        """Drop dead nodes; keep everything when that would empty an artifact.

        Probe keys come from ``_probe_items``; filtering re-derives them from the
        original nodes, so probe-time renaming never leaks into the output.
        """
        kept_txt = [line for line in txt_lines if report.survivor(_txt_key(line))]
        kept_yaml = [proxy for proxy in yaml_proxies if report.survivor(_yaml_key(proxy))]

        if txt_lines and not kept_txt:
            print("  [merger] probe removed every txt node — keeping unfiltered txt")
            kept_txt = txt_lines
        if yaml_proxies and not kept_yaml:
            print("  [merger] probe removed every yaml proxy — keeping unfiltered yaml")
            kept_yaml = yaml_proxies

        # Renaming can only introduce new fingerprints, so a second pass is safe
        # and keeps the output free of name-only duplicates.
        return unique_by(kept_txt, txt_fingerprint), unique_by(kept_yaml, proxy_fingerprint)

    # ── Writing ──

    def _write_atomic(self, path: Path, content: str) -> None:
        """Write *content* to *path* via a temp file, so readers never see a
        truncated artifact if the process dies mid-write."""
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(content, encoding="utf-8")
        os.replace(temp, path)

    def _write_txt(self, lines: list[str], result: MergeResult) -> str:
        if not lines:
            return ""
        txt = "\n".join(lines)
        out = self.nodes_dir / "merged.txt"
        self._write_atomic(out, txt)
        print(f"  [merger] merged.txt: {result.txt_sources} files, {len(lines)} nodes")
        return str(out)

    def _write_yaml(self, proxies: list[dict], result: MergeResult) -> str:
        import yaml

        if not proxies:
            return ""

        stringified = self._stringify_reality_fields(proxies)
        proxy_names = [p["name"] for p in stringified]
        groups = self._build_default_groups(proxy_names)

        output = self._base_clash_config(proxies=stringified, groups=groups)

        yaml_text = yaml.dump(
            output,
            Dumper=make_safe_dumper(),
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        out = self.nodes_dir / "merged.yaml"
        self._write_atomic(
            out, self._header(f"Merged {result.yaml_sources} yaml files") + yaml_text
        )
        print(f"  [merger] merged.yaml: {result.yaml_sources} files, {len(stringified)} proxies")
        return str(out)

    # ── Provider YAML ──

    def _build_provider(self, result: MergeResult) -> str:
        """Build a Clash Meta config using proxy-provider references."""
        import yaml

        yaml_files = sorted(f for f in self.nodes_dir.glob("*.yaml")
                           if f.name not in ("merged.yaml", "provider.yaml")
                           and not self._skip_stale(f.name))
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
                        for index, proxy in enumerate(doc.get("proxies", []), 1):
                            if validate_proxy(proxy, f"{f.name}.proxies[{index}]", strict=False).ok:
                                all_names.append(proxy.get("name", ""))
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
        self._write_atomic(
            out,
            self._header("Proxy-provider based config (for Clash Meta / Mihomo)") + yaml_text,
        )
        print(f"  [merger] provider.yaml: {len(yaml_files)} providers, {len(regions)} regions")
        return str(out)

    # ── Helpers ──

    @staticmethod
    def _stringify_reality_fields(proxies: list[dict]) -> list[dict]:
        """Force Mihomo Reality string fields to serialize as quoted strings."""
        return force_string_proxy_fields(proxies)

    @staticmethod
    def _dedup_proxies(proxies: list[dict]) -> list[dict]:
        """Deduplicate by connection fingerprint; rename name collisions.

        The fingerprint covers every connection field (credentials, transport,
        TLS, plugin options) and ignores only the display name, so two nodes
        sharing ``server:port`` but differing in UUID, path or SNI are both
        kept. Mihomo rejects a config with duplicate names, so collisions are
        still suffixed with ``_N``.
        """
        unique = unique_by(
            (
                p for p in proxies
                if isinstance(p, dict) and proxy_fingerprint(p)
            ),
            proxy_fingerprint,
        )
        seen_name: set[str] = set()
        result: list[dict] = []
        name_counter: dict[str, int] = {}

        for p in unique:
            name = p.get("name", "unknown")
            if name in seen_name:
                base = name
                index = name_counter.get(base, 1)
                while True:
                    index += 1
                    candidate = f"{base}_{index}"
                    if candidate not in seen_name:
                        name_counter[base] = index
                        name = candidate
                        break
            seen_name.add(name)

            result.append({**p, "name": name})

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
        if result.probe_backend and not result.probe_unavailable:
            print(f"  [merger] probe ({result.probe_backend}): "
                  f"{result.probe_alive} alive / {result.probe_dead} dead / "
                  f"{result.probe_unprobed} unprobed")
        if result.region_count:
            print("  [merger] region distribution:")
            for region, count in sorted(result.region_count.items(),
                                         key=lambda x: -x[1]):
                print(f"    {region}: {count} nodes")


# ── Probe keys ──
#
# Probing runs before filtering, and filtering must look up exactly the keys
# the probe produced. Keys are structured tuples rather than joined strings so
# that two different configurations can never collide on a separator.

def _txt_key(line: str) -> tuple:
    return ("txt", *txt_fingerprint(line))


def _yaml_key(proxy: dict) -> tuple:
    return ("yaml", *proxy_fingerprint(proxy))
