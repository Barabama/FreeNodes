# MVP: clashmeta 单站点 — 规则优先 + LLM兜底 + 自愈

> **目标:** 用最小代码验证 Crawl4AI + OpenRouter + 自愈 Pipeline 的完整链路
> **站点:** clashmeta (https://clash-meta.github.io/free-nodes/)
> **核心策略:** 正则命中即 0 token；正则失效 LLM 兜底；LLM 成功后自动回写规则到 config

---

## 一、Playwright 页面分析结论

### 博客页 `https://clash-meta.github.io/free-nodes/`

```
banner → 12 篇 h3 文章卡片 → 分页 → 侧栏(广告+热门+归档)
```

每篇文章：标题含 `X月X日` 日期 + 图片 + 摘要 + URL

```
最新: /newly-discovered-nodes/index.html?date=2026-6-18
其他: /free-nodes/YYYY-M-D-slug.htm
```

### 文章页 `.../index.html?date=2026-6-18`

```
标题 "新发现节点"
├── 4 个机场推广（广告，可忽略）
└── h2 "订阅链接"
    ├── strong "clash订阅链接"  → 5 个 .yaml
    ├── strong "v2ray订阅链接"  → 5 个 .txt
    └── strong "sing-box订阅链接" → 1 个 .json

所有链接格式: https://node.freeclashnode.com/uploads/YYYY/MM/N-YYYYMMDD.ext
```

> **结论:** clashmeta 是纯静态页，链接模式极规律。

---

## 二、MVP 文件结构

```
FreeNodeSpider/
├── .env                         # OPENROUTER_API_KEY=sk-or-v1-xxx
├── config.yaml                  # 站点配置（含 link_pattern 自愈字段）
├── mvp_clashmeta.py             # 主入口：端到端跑通
├── src/
│   ├── __init__.py
│   ├── config.py                # config 加载 + 持久化
│   ├── crawler.py               # Crawl4AI (页面) + httpx (文件下载)
│   ├── llm.py                   # LLM 提取 + 正则生成 + 四层校验
│   └── pipeline.py              # 去重 + base64 decode + 输出
└── nodes/                       # 输出目录
    ├── clashmeta.txt
    └── clashmeta.yaml
```

---

## 三、config.yaml

```yaml
# FreeNodeSpider 站点配置
# link_pattern 为空时 → LLM 自动提取，成功后回写正则

sites:
  - name: clashmeta
    start_url: https://clash-meta.github.io/free-nodes/
    description: "博客站点，文章标题含日期(月日格式)，每篇文章内直接提供订阅链接"
    link_pattern: null  # 初始为空，LLM 提取成功后自动回写
    # 自愈后变为:
    # link_pattern: "https://node\\.freeclashnode\\.com/uploads/[^\\s\"'<>]+\\.(yaml|txt)"

crawl:
  max_articles: 3
  timeout: 30

output:
  dir: nodes
```

---

## 四、核心代码

### src/config.py

```python
"""配置加载 + 持久化 + link_pattern 自愈回写."""
import yaml
from dataclasses import dataclass, field


@dataclass
class SiteConfig:
    name: str
    start_url: str
    description: str = ""
    link_pattern: str | None = None  # None→LLM提取, str→正则命中
    # 仅用于重置过时 pattern
    failed_count: int = 0


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
    """保存配置，包括 LLM 自愈后回写的 link_pattern."""
    raw = {
        "sites": [
            {"name": s.name, "start_url": s.start_url,
             "description": s.description, "link_pattern": s.link_pattern}
            for s in config.sites
        ],
        "crawl": config.crawl,
        "output": config.output,
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, default_flow_style=False)
```

### src/crawler.py

```python
"""双引擎爬取：Crawl4AI 取页面结构 + httpx 下载文件."""
import asyncio
import httpx
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from dataclasses import dataclass


@dataclass
class Page:
    url: str
    markdown: str
    html: str
    links: list[dict]  # [{"href": "...", "text": "..."}]


async def fetch_page(url: str) -> Page:
    """Crawl4AI 爬取页面，返回结构化内容."""
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url=url,
            config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=30000),
        )
    if not result.success:
        raise RuntimeError(f"Fetch failed [{url}]: {result.error_message}")

    md_obj = result.markdown
    markdown_text = md_obj.raw_markdown if md_obj and hasattr(md_obj, "raw_markdown") else ""
    html_text = result.html or ""

    links = []
    for scope in ("internal", "external"):
        for link in (result.links or {}).get(scope, []):
            href = link.get("href", "")
            if href and not href.startswith("javascript:"):
                links.append({"href": href, "text": link.get("text", "")[:200]})

    return Page(url=url, markdown=markdown_text, html=html_text, links=links)


async def download_file(url: str) -> str:
    """httpx 下载文件，比浏览器快 10-50 倍."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        resp = await c.get(url)
        resp.raise_for_status()
        return resp.text
```

### src/llm.py

```python
"""LLM 客户端 + 正则生成 + 四层校验."""
import os
import re
import json
from openai import OpenAI


class LLM:
    def __init__(self):
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
        )

    # ── Level 0: 纯提取（规则失效时调用） ──

    def extract_links(self, markdown: str) -> dict[str, list[str]]:
        """从 markdown 中提取 .txt / .yaml 订阅链接.

        返回: {"txt": [...], "yaml": [...]}
        """
        prompt = f"""从以下网页内容提取所有订阅链接（仅 .txt 和 .yaml 结尾的URL）。
返回 JSON: {{"txt": ["url1",...], "yaml": ["url1",...]}}
不返回任何 JSON 以外的内容。没有找到就返回空数组。

内容:
{markdown[:8000]}"""

        resp = self.client.chat.completions.create(
            model="openrouter/free",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1024,
        )
        return self._parse_json(resp.choices[0].message.content)

    # ── Level 1: 正则生成 ──

    def generate_pattern(self, links: list[str], html: str) -> str | None:
        """让 LLM 根据已知链接生成提取正则，备四层校验.

        返回: regex 字符串，生成失败返回 None
        """
        prompt = f"""以下是从网页中找到的订阅链接：
{chr(10).join(links[:10])}

请观察这些 URL 的共同规律，写一个 Python 正则表达式来匹配它们。
要求：
- 正则必须足够通用，能匹配同一网站其他日期的类似链接
- 正则必须足够精确，不会匹配到页面中的广告、导航、JS 等无关内容
- 只返回正则表达式本身，不要用引号包裹，不要解释

正则:"""

        resp = self.client.chat.completions.create(
            model="openrouter/free",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=256,
        )
        pattern = resp.choices[0].message.content.strip()
        # 清洗：去掉可能的 markdown 代码块包装
        if "```" in pattern:
            pattern = re.sub(r"```\w*|```", "", pattern).strip()
        return pattern if pattern else None

    # ── 四层校验 ──

    @staticmethod
    def verify_pattern(pattern: str, known_links: list[str],
                       html: str, html2: str | None = None) -> bool:
        """四层校验正则表达式是否可靠.

        Returns True 表示可安全写入 config.
        """
        # 校验1: 语法
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return False

        # 校验2: Recall — 不能漏掉任何已知正确的链接
        matches = compiled.findall(html)
        for link in known_links:
            if link not in str(matches):
                print(f"    ⚠ verify fail: pattern missed known link {link[:60]}...")
                return False

        # 校验3: Precision — 不能匹配到导航/广告/JS
        false_positives = 0
        for m in matches:
            if isinstance(m, tuple):
                m = m[0]  # 捕获组取第一个
            if not m.startswith("http"):
                false_positives += 1
            elif any(n in m.lower() for n in ("javascript:", "#", "xmlrpc")):
                false_positives += 1
        if false_positives > len(matches) * 0.2:
            print(f"    ⚠ verify fail: {false_positives}/{len(matches)} false positives")
            return False

        # 校验4: Cross-validation — 同一站点另一篇文章也能用
        if html2 is not None:
            cross_matches = compiled.findall(html2)
            if not cross_matches:
                print("    ⚠ verify fail: pattern overfitted, no cross-match")
                return False

        return True

    # ── 内部方法 ──

    def _parse_json(self, raw: str) -> dict[str, list[str]]:
        """从 LLM 响应中解析 JSON."""
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"txt": [], "yaml": []}
```

### src/pipeline.py

```python
"""去重 + base64 decode + 输出到 nodes/."""
import base64
import hashlib
from pathlib import Path


def process_txt(raw: str) -> str:
    """Decode base64 v2ray 节点，按行 hash 去重."""
    try:
        decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
    except Exception:
        decoded = raw

    seen, unique = set(), []
    for line in decoded.splitlines():
        line = line.strip()
        if not line:
            continue
        h = hashlib.md5(line.encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(line)
    return "\n".join(unique)


def save(site: str, ext: str, content: str, out_dir: str = "nodes"):
    """输出到 nodes/{site}.{ext}."""
    path = Path(out_dir)
    path.mkdir(exist_ok=True)
    if ext == ".txt":
        content = process_txt(content)
    filepath = path / f"{site}{ext}"
    filepath.write_text(content, encoding="utf-8")
    lines = content.count("\n") + 1 if content else 0
    print(f"  💾 saved: {filepath} ({len(content)}B, {lines} lines)")
```

### mvp_clashmeta.py（主入口）

```python
#!/usr/bin/env python
"""MVP: clashmeta 单站点 — 规则优先 + LLM 兜底 + 自愈.

流程:
  1. 加载 config → 查 link_pattern
  2. link_pattern 存在 → 正则提取 (0 token, 结束)
  3. link_pattern 不存在或失效 → LLM 提取 → 生成 pattern → 四层校验
  4. 校验通过 → 回写 config.yaml (自愈)
  5. httpx 下载 → 去重 → 输出 nodes/

Usage: python mvp_clashmeta.py
"""
import asyncio
import re
import sys
from datetime import date
from urllib.parse import urljoin

sys.path.insert(0, ".")

from src.config import load_config, save_config
from src.crawler import fetch_page, download_file
from src.pipeline import save

BLOG_URL = "https://clash-meta.github.io/free-nodes/"
BASE = "https://clash-meta.github.io"
MAX_ARTICLES = 3


# ── 文章选择：始终规则（日期正则匹配中文格式） ──

def pick_newest_articles(blog) -> list[dict]:
    """从 Crawl4AI 的 link 列表中按日期选最新 N 篇.

    日期来源：标题文字 "6月18日" 或 URL路径 "2026-6-18"
    """
    articles = []
    for link in blog.links:
        text = link.get("text", "")
        href = link.get("href", "")

        # 从标题提取日期
        m = re.search(r"(\d{1,2})月(\d{1,2})日", text)
        if m:
            d = f"{date.today().year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        else:
            # 从 URL 路径提取日期
            m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", href)
            if m:
                d = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            else:
                continue

        # 排除非文章页
        if href in ("/free-nodes/", "/", "") or "category" in href or "page-" in href:
            continue

        full = urljoin(BASE, href)
        articles.append({"url": full, "date": d, "text": text[:80]})

    # 去重 → 按日期降序 → 取 top N
    seen, unique = set(), []
    for a in sorted(articles, key=lambda x: x["date"], reverse=True):
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)
    return unique[:MAX_ARTICLES]


# ── 订阅链接提取：规则优先 + LLM 兜底 + 自愈 ──

def extract_by_pattern(html: str, pattern: str) -> list[str]:
    """用已保存的正则提取链接."""
    matches = re.findall(pattern, html, re.IGNORECASE)
    # 处理捕获组：re.findall 对单组返回字符串列表，多组返回元组列表
    if matches and isinstance(matches[0], tuple):
        matches = [m[0] for m in matches]
    # 清洗尾部标点
    return [re.sub(r'[),;.\'"]+$', "", m) for m in matches if m.startswith("http")]


async def extract_with_fallback(page, site_cfg) -> tuple[list[str], bool]:
    """提取订阅链接：先规则、后 LLM、成功后自愈.

    Returns: (links, pattern_updated)
    """
    html = page.html

    # —— Step 1: 规则优先 ——
    if site_cfg.link_pattern:
        result = extract_by_pattern(html, site_cfg.link_pattern)
        if result:
            print(f"    ✅ regex hit: {site_cfg.link_pattern[:60]}... → {len(result)} links")
            return result, False  # 0 token, 0 配置变更

        print(f"    ⚠ regex miss: pattern {site_cfg.link_pattern[:60]}... failed, falling back to LLM")
        site_cfg.failed_count += 1

    # —— Step 2: LLM 兜底 ——
    from src.llm import LLM
    llm = LLM()

    llm_result = llm.extract_links(page.markdown)
    all_links = llm_result.get("txt", []) + llm_result.get("yaml", [])
    if not all_links:
        print("    ❌ LLM also found nothing")
        return [], False

    print(f"    🤖 LLM found {len(all_links)} links: {all_links[:3]}...")

    # —— Step 3: LLM 生成正则 ——
    new_pattern = llm.generate_pattern(all_links, html)
    if not new_pattern:
        print("    ⚠ LLM failed to generate pattern, skipping self-heal")
        return all_links, False

    # —— Step 4: 四层校验 ——
    # 校验4 需要另一篇文章的 HTML（找列表里第二篇）
    html2 = None
    try:
        articles = pick_newest_articles(await fetch_page(BLOG_URL))
        if len(articles) >= 2:
            page2 = await fetch_page(articles[1]["url"])
            html2 = page2.html
    except Exception:
        pass  # 拿不到第二篇就跳过校验4

    if llm.verify_pattern(new_pattern, all_links, html, html2):
        print(f"    ✅ pattern verified, writing to config: {new_pattern}")
        site_cfg.link_pattern = new_pattern
        site_cfg.failed_count = 0
        return all_links, True  # True = 需要 save_config
    else:
        print(f"    ⚠ pattern rejected by verification, keeping null")
        return all_links, False


# ── 主流程 ──

async def main():
    print("=" * 60)
    print("MVP: clashmeta — Rule-first + LLM fallback + Self-healing")
    print("=" * 60)

    config = load_config()
    site = config.sites[0]
    pattern_updated = False

    print(f"\nSite: {site.name} ({site.start_url})")
    print(f"Pattern: {site.link_pattern or '(null — will use LLM)'}")

    # 1. 爬博客首页
    print(f"\n[1/4] Fetching blog page...")
    blog = await fetch_page(BLOG_URL)
    print(f"  Got {len(blog.links)} links")

    # 2. 选最新文章
    print(f"\n[2/4] Selecting newest {MAX_ARTICLES} articles...")
    articles = pick_newest_articles(blog)
    for a in articles:
        print(f"  [{a['date']}] {a['url']}")
    if not articles:
        print("  ❌ No articles found!"); return

    # 3. 逐篇提取订阅链接
    print(f"\n[3/4] Extracting subscription links from {len(articles)} articles...")
    all_txt, all_yaml = set(), set()

    for a in articles:
        print(f"  → {a['url']}")
        page = await fetch_page(a["url"])

        links, updated = await extract_with_fallback(page, site)
        if updated:
            pattern_updated = True

        # 按扩展名分类
        for url in links:
            if url.endswith(".txt"):
                all_txt.add(url)
            elif url.endswith(".yaml"):
                all_yaml.add(url)

    print(f"\n  Total: {len(all_txt)} txt + {len(all_yaml)} yaml unique links")

    if not all_txt and not all_yaml:
        print("  ❌ No subscription links found!"); return

    # 自愈：回写 config
    if pattern_updated:
        print("\n  🔧 Self-healing: saving updated config...")
        save_config(config)

    # 4. 下载 + 输出
    print("\n[4/4] Downloading files...")
    txt_content, yaml_content = [], []

    for url in sorted(all_txt):
        try:
            body = await download_file(url)
            txt_content.append(body)
            print(f"  ✓ txt: {url} ({len(body)}B)")
        except Exception as e:
            print(f"  ✗ txt: {url} — {e}")

    for url in sorted(all_yaml):
        try:
            body = await download_file(url)
            yaml_content.append(body)
            print(f"  ✓ yaml: {url} ({len(body)}B)")
        except Exception as e:
            print(f"  ✗ yaml: {url} — {e}")

    if txt_content:
        save("clashmeta", ".txt", "\n".join(txt_content))
    if yaml_content:
        save("clashmeta", ".yaml", "\n---\n".join(yaml_content))

    print("\n" + "=" * 60)
    print("✓ MVP complete!")
    print(f"  Downloaded: {len(txt_content)} txt, {len(yaml_content)} yaml")
    print(f"  Pattern:    {'freshly self-healed' if pattern_updated else site.link_pattern or '(remains null)'}")
    print(f"  Output:     nodes/clashmeta.txt, nodes/clashmeta.yaml")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 五、自愈机制完整流程图

```
每次运行 mvp.py
      │
      ▼
┌─────────────┐    有规则且命中
│ 查 link_pattern ├────────────────────┐
└──────┬──────┘                        │
       │ null 或 失效                    │
       ▼                               ▼
┌─────────────┐                  ┌──────────┐
│  LLM 提取链接 │                  │ 正则提取   │
│  (花 token)  │                  │ (0 token) │
└──────┬──────┘                  └────┬─────┘
       │                             │
       ▼                             │
┌─────────────┐                      │
│  LLM 观察规律 │                      │
│  生成正则    │                      │
└──────┬──────┘                      │
       │                             │
       ▼                             │
┌─────────────┐                      │
│  四层校验    │                      │
│ ┌───────┐   │                      │
│ │1.语法  │   │                      │
│ │2.recall│   │                      │
│ │3.prec. │   │                      │
│ │4.x-val │   │                      │
│ └───┬───┘   │                      │
│     ▼       │                      │
│  通过? ──YES──→ 回写 config ────────┘
│     │              (自愈)
│     NO
│     │
│     ▼
│  保持 null
│  (下次再试)
└─────────────┘
       │
       ▼
  httpx 下载 → 去重 → 输出 nodes/
```

---

## 六、设计决策

| 决策 | 理由 |
|------|------|
| **文章日期选择：始终规则** | 中文 `X月X日` 格式稳定，regex 解析零成本且不会出错 |
| **订阅链接提取：规则优先** | clashmeta URL 模式极规律，regex 100% 准确 |
| **规则失效 → LLM 兜底** | 站点改版时不崩溃，自动适应 |
| **LLM 生成的正则：四层校验** | 语法+recall+precision+交叉验证，缺一不保存 |
| **校验失败 → 不保存** | 宁可下次再调 LLM，也不写入不可靠的规则 |
| **正则写回 config** | 自愈后下一次 0 token，永久受益 |
| **httpx 下载文件** | 比 Playwright/CDP 快 10-50 倍，不需要浏览器 |

---

## 七、验证清单

```bash
export OPENROUTER_API_KEY=sk-or-v1-xxx
python mvp_clashmeta.py
```

**5 个成功标准：**

1. ✅ 博客页提取到当前日期前最新的 3 篇文章
2. ✅ `link_pattern: null` 时 LLM 成功提取链接 + 生成正则 + 校验通过 + 回写 config
3. ✅ 第二次运行 `link_pattern` 非空，正则直接命中，0 token
4. ✅ `nodes/clashmeta.txt` 包含有效 `vmess://` / `vless://` 节点
5. ✅ `nodes/clashmeta.yaml` 包含有效 YAML 的 `proxies:` 列表
