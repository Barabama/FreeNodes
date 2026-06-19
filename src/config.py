"""配置加载 + 持久化 + link_pattern 自愈回写."""
import yaml
from dataclasses import dataclass


@dataclass
class SiteConfig:
    name: str
    start_url: str
    description: str = ""
    link_pattern: str | None = None  # None → use LLM
    failed_count: int = 0            # pattern miss count


@dataclass
class Config:
    sites: list[SiteConfig]
    crawl: dict
    output: dict


def load_config(path: str = "config.yaml") -> Config:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    sites = [SiteConfig(**s) for s in raw["sites"]]
    return Config(sites=sites, crawl=raw.get("crawl", {}), output=raw.get("output", {}))


def save_config(config: Config, path: str = "config.yaml"):
    """持久化配置，包括 LLM 自愈后回写的 link_pattern."""
    raw = {
        "sites": [
            {
                "name": s.name,
                "start_url": s.start_url,
                "description": s.description,
                "link_pattern": s.link_pattern,
            }
            for s in config.sites
        ],
        "crawl": config.crawl,
        "output": config.output,
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, default_flow_style=False)
    print(f"  💾 Config saved to {path}")
