"""Configuration loading, persistence, and self-healing link_pattern storage."""
import yaml
from dataclasses import dataclass, field


@dataclass
class SiteConfig:
    name: str
    start_url: str
    description: str = ""
    link_pattern: str | None = None
    failed_count: int = 0


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key_env: str
    models: list[str]
    is_reasoning_model: bool = False
    default_weight: int = 10


@dataclass
class LLMConfig:
    providers: list[ProviderConfig] = field(default_factory=list)
    task_routing: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass
class CrawlConfig:
    max_articles: int = 3
    timeout: int = 30
    concurrency: int = 3


@dataclass
class Config:
    sites: list[SiteConfig]
    crawl: CrawlConfig
    output: dict
    llm: LLMConfig


def load_config(path: str = "config.yaml") -> Config:
    """Load config from YAML file. Missing llm section yields empty LLMConfig."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    sites = [SiteConfig(**s) for s in raw["sites"]]
    crawl = CrawlConfig(**(raw.get("crawl") or {}))
    output = raw.get("output", {})

    llm_raw = raw.get("llm", {})
    providers = [ProviderConfig(**p) for p in llm_raw.get("providers", [])]
    llm = LLMConfig(providers=providers, task_routing=llm_raw.get("task_routing", {}))

    return Config(sites=sites, crawl=crawl, output=output, llm=llm)


def save_config(config: Config, path: str = "config.yaml"):
    """Persist config, preserving link_pattern and llm section."""
    raw_sites = []
    for s in config.sites:
        entry = {
            "name": s.name,
            "start_url": s.start_url,
            "description": s.description,
        }
        if s.link_pattern:
            entry["link_pattern"] = s.link_pattern
        raw_sites.append(entry)

    raw_llm = {
        "providers": [
            {
                "name": p.name,
                "base_url": p.base_url,
                "api_key_env": p.api_key_env,
                "models": p.models,
                "is_reasoning_model": p.is_reasoning_model,
                "default_weight": p.default_weight,
            }
            for p in config.llm.providers
        ],
        "task_routing": config.llm.task_routing,
    }

    raw = {
        "crawl": {
            "max_articles": config.crawl.max_articles,
            "timeout": config.crawl.timeout,
            "concurrency": config.crawl.concurrency,
        },
        "output": config.output,
        "sites": raw_sites,
        "llm": raw_llm,
    }

    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, default_flow_style=False)
