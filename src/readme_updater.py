"""README.md generator — builds subscription table from config + nodes/."""
from datetime import datetime
from pathlib import Path

from src.config import Config


GITHUB_BASE = "https://raw.githubusercontent.com/Barabama/FreeNodes/refs/heads"
GITHUB_PROXY = "https://gh-proxy.com/raw.githubusercontent.com/Barabama/FreeNodes/refs/heads"
BRANCH = "main"


def build_readme(config: Config) -> str:
    """Generate README.md with subscription table from config site list."""
    today = datetime.now().strftime("%Y-%m-%d")

    lines = [
        "# FreeNodes",
        "",
        "v2ray、Clash 免费节点爬虫（AI 版），每日 12:00 自动运行。",
        "",
        "## 免责声明",
        "",
        "订阅节点仅作学习交流使用，用于查找资料，学习知识，不做任何违法行为。",
        "所有资源均来自互联网，仅供大家交流学习使用，出现违法问题概不负责。",
        "",
        "## v2ray / Clash 订阅列表",
        "",
        "| 爬虫目标 | 订阅链接 | 镜像加速订阅链接 | 更新日期 |",
        "| --- | --- | --- | --- |",
    ]

    for site in config.sites:
        name = site.name
        url = site.start_url
        up_date = site.up_date or "—"
        node_count = site.node_count

        # Build file links — one row per available file
        txt_path = Path(f"nodes/{name}.txt")
        yaml_path = Path(f"nodes/{name}.yaml")

        links = []
        mirror_links = []

        if txt_path.exists():
            raw = f"{GITHUB_BASE}/{BRANCH}/nodes/{name}.txt"
            mirror = f"{GITHUB_PROXY}/{BRANCH}/nodes/{name}.txt"
            links.append(f"[{name}.txt]({raw})")
            mirror_links.append(f"[镜像]({mirror})")
        if yaml_path.exists():
            raw = f"{GITHUB_BASE}/{BRANCH}/nodes/{name}.yaml"
            mirror = f"{GITHUB_PROXY}/{BRANCH}/nodes/{name}.yaml"
            links.append(f"[{name}.yaml]({raw})")
            mirror_links.append(f"[镜像]({mirror})")

        count_str = f" ({node_count} nodes)" if node_count else ""
        lines.append(
            f"| [{name}]({url}) "
            f"| {'<br>'.join(links) or '—'}{count_str} "
            f"| {'<br>'.join(mirror_links) or '—'} "
            f"| {up_date} |"
        )

    # Merged files row (no blank line before — would break the table)
    merged_links = []
    merged_mirror = []
    for fname in ("merged.txt", "merged.yaml", "provider.yaml"):
        fpath = Path(f"nodes/{fname}")
        if fpath.exists():
            raw = f"{GITHUB_BASE}/{BRANCH}/nodes/{fname}"
            mirror = f"{GITHUB_PROXY}/{BRANCH}/nodes/{fname}"
            merged_links.append(f"[{fname}]({raw})")
            merged_mirror.append(f"[镜像]({mirror})")
    if merged_links:
        lines.append(
            f"| [merged](https://github.com/Barabama/FreeNodes/tree/{BRANCH}) "
            f"| {'<br>'.join(merged_links)} "
            f"| {'<br>'.join(merged_mirror)} "
            f"| {today} |"
        )

    lines.extend([
        "",
        "## 关于 merged 订阅",
        "",
        "`merged.txt` 与 `merged.yaml` 在发布前做了两步处理：",
        "",
        "1. **去重** — 按连接配置去重，同一节点被多个站点以不同名称重复发布时只保留一条；"
        "凭据或传输参数不同的节点不会被合并。",
        "2. **连通性筛选** — 默认对每个节点的端口做 TCP 握手，"
        f"超过 {config.probe.max_delay_ms} ms 或无法连接的节点会被移除。"
        "TCP 测速只说明端口在时限内可连，**不能验证代理认证或实际转发是否可用**；"
        "UDP 类协议（Hysteria2、TUIC 等）无法用 TCP 判定，一律保留。"
        "如需真实可用性，可将 `probe.backend` 改为 `mihomo`。",
        "",
        "`provider.yaml` 引用的是各站点原始文件，未经上述筛选。",
        "",
        "---",
        "",
        f"*上次更新: {today} | "
        f"运行方式: GitHub Actions (main)*",
        "",
    ])

    return "\n".join(lines) + "\n"


def write_readme(config: Config, path: str = "README.md"):
    """Generate and write README.md."""
    content = build_readme(config)
    Path(path).write_text(content, encoding="utf-8")
    print(f"  [readme] {path} updated ({len(content)} chars)")
