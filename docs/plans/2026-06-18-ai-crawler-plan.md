# FreeNodeSpider — AI 智能爬虫实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 用 Crawl4AI + LLM 替换现有 Scrapy 项目，实现无需 CSS 选择器的智能代理爬虫，支持 YouTube 视频详情提取、自适应解密、自动去重合并。

**Architecture:** 单体 Python CLI 应用，Crawl4AI 负责页面爬取，OpenRouter/Google AI Studio 双通道 LLM 负责智能提取与决策，yt-dlp 负责 YouTube，输出 V2Ray txt 和 Clash yaml 到 nodes/ 目录。

**Tech Stack:** Python 3.12, Crawl4AI (Playwright 后端), openai SDK (调用 OpenRouter), yt-dlp, PyYAML, GitHub Actions

**LLM 策略:** OpenRouter 免费模型openrouter/free为主， 为备，$0/月，每天 ~50-500 次调用。 
comment：https://github.com/cheahjs/free-llm-api-resources/blob/main/README.md 能够获取免费模型列表
OpenRouter使用openrouter/free模型，教程https://openrouter.ai/openrouter/free

---

## 项目结构（目标）

```
FreeNodeSpider/
├── pyproject.toml              # 项目配置 + 依赖
├── config.yaml                 # 站点配置（自然语言驱动，无 CSS）
├── nodes/                      # 输出目录
│   ├── {site}.txt              # 各站点 V2Ray 节点
│   ├── {site}.yaml             # 各站点 Clash 配置
│   ├── merged.txt              # 合并版 V2Ray
│   └── merged.yaml             # 合并版 Clash
├── src/
│   ├── __init__.py
│   ├── main.py                 # CLI 入口：python -m src.main --target all
│   ├── crawler.py              # Crawl4AI 封装，统一爬取 + 反反爬
│   ├── llm.py                  # LLM 客户端（OpenRouter + Google fallback）
│   ├── classifier.py           # 页面分类器（列表页/详情页/加密页）
│   ├── extractor.py            # 智能提取器（链接、密码、节点）
│   ├── youtube.py              # yt-dlp 封装，提取字幕/描述
│   ├── decryptor.py            # 通用解密逻辑（浏览器自动化）
│   ├── pipeline.py             # 数据清洗、去重、合并、输出
│   └── config.py               # config.yaml 加载 + 状态管理
├── prompts/
│   ├── page_classify.txt       # 页面分类提示词
│   ├── extract_links.txt       # 列表页链接提取
│   ├── extract_nodes.txt       # 详情页节点链接提取
│   └── extract_password.txt    # 密码提取（页面/YouTube）
├── tests/
│   ├── test_crawler.py
│   ├── test_extractor.py
│   ├── test_youtube.py
│   └── test_pipeline.py
├── .github/workflows/
│   └── crawl.yml               # 每日定时爬取
└── .env.example                # API key 模板
```

---

## Phase 1: 项目基础设施

### Task 1.1: 初始化项目结构

**Files:**
- Create: `pyproject.toml`
- Create: `src/__init__.py`
- Create: `.env.example`
- Create: `.gitignore`

**Step 1: 创建 pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "freenodespider"
version = "0.1.0"
description = "AI-powered proxy node crawler"
requires-python = ">=3.12"
dependencies = [
    "crawl4ai>=0.5.0",
    "openai>=1.0.0",
    "yt-dlp>=2024.0.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
]
```

**Step 2: 创建 .env.example**

```bash
# OpenRouter (one-time setup at openrouter.ai)
OPENROUTER_API_KEY=sk-or-v1-xxx
comment：sk-or-v1-REDACTED
# # Google AI Studio (one-time setup at aistudio.google.com) 
# GOOGLE_API_KEY=xxx

comment：opencode sk-or-v1-REDACTED

# Optional: for local testing
# OLLAMA_BASE_URL=http://localhost:11434
```
comment：不使用本地部署模型，优先测试api调用可用性
**Step 3: 创建 .gitignore**

```
__pycache__/
*.pyc
.env
.scrapy/
build/
dist/
*.egg-info/
```

**Step 4: Commit**

```bash
git init
git add pyproject.toml src/__init__.py .env.example .gitignore
git commit -m "feat: initialize project structure"
```

---

### Task 1.2: 创建站点配置文件（替代 config.json）

**Files:**
- Create: `config.yaml`
- Create: `src/config.py`

**Step 1: 创建 config.yaml（自然语言驱动，无CSS选择器）**

```yaml
# FreeNodeSpider 站点配置
# 原则: 不写死 CSS 选择器，LLM 自动理解页面结构

sites:
  # ===== Simple 站点：博客 → 文章 → 订阅链接 =====
name:85la
start_url:https://www.85la.com/internet-access/free-network-nodes/
type: simple
description:"85la 博客, 每篇文章提供几个 clash/v2ray/sing-box/shadowsocks 等订阅链接"
amount: 400

name:cfmem
start_url:https://www.cfmem.com/
type:simple
description:"cfmem 博客, 每篇文章提供几个 clash/v2ray/sing-box 订阅链接"
amount: 20

name:clashmeta
start_url:https://clash-meta.github.io/free-nodes/
type: simple
description:"clashmeta 博客, 每篇文章提供几个clash/v2ray/sing-box 订阅链接"
amount: 300

name:clashnode
start_url:https://clashnode.cc/free-node/
type: simple
description:"clashnode 博客, 每篇文章提供几个 clash/v2ray/sing-box 订阅链接"
amount: 300

name:clashstair
start_url:https://clashstair.com/category/freenode/
type: simple
description:"clashstair 博客, 每篇文章提供几个 clash/v2ray/sing-box 订阅链接"
amount: 20

name:datiya
start_url:https://free.datiya.com/
type: simple
description:"datiya 博客, 每篇文章提供几个 clash/v2ray 订阅链接"
amount: 20

name:freeclashnode
start_url:https://www.freeclashnode.com/free-node/
type:simple
description:"freeclashnode 博客, 每篇文章提供几个 clash/v2ray/sing-box 订阅链接"
amount: 300

name:jichangx
start_url:https://jichangx.com/free-subscription/
type:simple
description:"jichangx 博客, 每篇文章提供几个 v2ray 订阅链接 和一些 2vray/shadowsocks 节点"
amount: 20

name:nodefree
start_url:https://nodefree.me/
type: simple
description:"nodefree 博客, 每篇文章提供几个 clash/v2ray 订阅链接"
amount: 20

name:nodev2ray
start_url:https://nodev2ray.com/free-node/
type: simple
description:"nodev2ray 博客, 每篇文章提供几个 clash/v2ray/sing-box 订阅链接"
amount: 200

name:oneclash
start_url:https://oneclash.cc/freenode/
type: simple
description:"oneclash 博客, 每篇文章提供几个 clash/v2ray 订阅链接"
amount: 50

name:yoyapai
start_url:https://yoyapai.com/category/mianfeijiedian/
type: simple
description:"yoyapai 博客, 每篇文章提供clash/v2ray订阅链接"
amount: 100

# complex

name:yudou
start_url:https://www.yudou789.top/category/jiedian/
type: yt_pwd
description:"yudou 博客, 每篇文章提供几个 clash/v2ray 订阅链接, 两天前的文章不受保护, 最新文章受密码保护"
pwd_hint:"4位数字密码, 通常为AABB型, 前两个数字相同, 后两个数字相同, 密码在视频嵌入式字幕中, 密码允许暴力枚举破解"
yt_hint:"文章中通常有一个'本期Youtube视频地址'的 YouTube 视频链接, 视频字幕包含4位数字密码"
amount: 300

name: fxrj
start_url:https://www.youtube.com/@fxrj/videos/
type: cloud_drive
description:"fxrj YouTube 频道, 每个视频详情包含'本期资源下载地址'网盘链接, 链接下载zip文件, zip文件包含 clash/v2ray 订阅文件"
file_hint: "zip文件中包含 clash/v2ray 订阅文件"
amount: 200

name: zyfxs
start_url:https://www.youtube.com/@ZYFXS/videos/
type: yt_pwd
description:"zyfxs YouTube 频道, 每个视频详情包含'本期资源'网页链接, 网页提供几个 clash/v2ray 订阅链接, 网页受密码保护"
pwd_hint:"4位数字密码, 一般形式, 密码在视频字幕中, 密码允许暴力枚举破解"
yt_hint:"视频的详细介绍包含'本期资源'网页链接"
amount: 200


# 爬取策略
crawl:
  max_pages: 3          # 每个站点最多爬 3 篇文章/视频
  timeout: 30           # 单页面超时 sec
  retry: 2              # 失败重试
  force: false   # 是否忽略 up_date 强制更新

# 输出
output:
  dir: nodes

#   merge:
#     - name: merged
#       type: txt                  # 合并所有 txt 为 merged.txt
#     - name: merged
#       type: yaml                 # 合并所有 yaml 为 merged.yaml
```
comment: 对要爬取的目标做了更新, 输出配置优先做单个, 先不做合并的, 合并的后续再考虑


**Step 2: 创建 src/config.py**

```python
"""配置加载与状态管理，替代旧 utils/Config.py"""

import yaml
from pathlib import Path
from dataclasses import dataclass, field
# from typing import Optional 
# comment：python 3.10+ 风格 不使用 Optional List Dict Tuple
# comment: 使用 '|' list dict tuple
# comment: 代码和注释使用英文, doc和md可以使用中文
# comment: 代码保持稳健和易读性, 减少缩进, 每个模块实现后及时实现单元测试, 测试必须要有明确测试用例的边界, 覆盖可能出现的意外情况

@dataclass
class SiteConfig:
    name: str
    start_url: str
    type: str  # simple | yt_pwd | cloud_drive
    description: str
    file_hint: str | None = None
    pwd_hint: str | None = None
    yt_hint: str | None = None
    # 运行时状态（持久化回 config.yaml）
    up_date: str | None = None
    passwords dict[str, str] | None = None  # dict{up_date: pwd} 最大 3 个


@dataclass
class CrawlConfig:
    max_pages: int = 3
    timeout: int = 30
    retry: int = 2
    force: bool = False


@dataclass
class OutputConfig:
    dir: str = "nodes"
    merge: list = field(default_factory=list)


@dataclass
class Config:
    sites: list[SiteConfig]
    crawl: CrawlConfig
    output: OutputConfig


def load_config(path: str = "config.yaml") -> Config:
    """加载配置文件"""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    sites = [SiteConfig(**s) for s in raw["sites"]]
    crawl = CrawlConfig(**raw.get("crawl", {}))
    output = OutputConfig(**raw.get("output", {}))
    return Config(sites=sites, crawl=crawl, output=output)


def save_config(config: Config, path: str = "config.yaml"):
    """保存运行状态（up_date, last_password）回配置文件"""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    for site in config.sites:
        for raw_site in raw["sites"]:
            if raw_site["name"] == site.name:
                raw_site["up_date"] = site.up_date
                if site.last_password:
                    raw_site["last_password"] = site.last_password
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, default_flow_style=False)
```

**Step 3: Commit**

```bash
git add config.yaml src/config.py
git commit -m "feat: add config.yaml and config loader"
```

---

## Phase 2: 核心爬取层

### Task 2.1: Crawl4AI 爬取封装

**Files:**
- Create: `src/crawler.py`

Crawl4AI 替代 Scrapy + Selenium，自带 Playwright 浏览器管理，内置反反爬。

**Step 1: 实现 Crawler 类**

```python
"""Crawl4AI 封装 — 替代 Scrapy Request/Response + Selenium"""

import asyncio
from dataclasses import dataclass
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode


@dataclass
class PageResult:
    """统一页面结果，替代 scrapy.Response"""
    url: str
    markdown: str          # 清洗后的 Markdown（LLM 最友好的格式）
    raw_html: str          # 原始 HTML（正则匹配备用）
    title: str
    links: list[str]       # 页面内所有链接
    success: bool
    error: str = ""


class Crawler:
    """统一爬取器，封装 Crawl4AI"""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    async def fetch(self, url: str) -> PageResult:
        """爬取单个页面，返回结构化内容"""
        config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            page_timeout=self.timeout * 1000,
        )
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)

        if not result.success:
            return PageResult(
                url=url, markdown="", raw_html="", title="",
                links=[], success=False, error=result.error_message
            )

        # 提取所有链接
        internal = list(result.internal_links or [])
        external = list(result.external_links or [])
        all_links = []
        for link in internal + external:
            href = link.get("href", "")
            if href:
                all_links.append(href)

        return PageResult(
            url=url,
            markdown=result.markdown or result.fit_markdown or "",
            raw_html=result.html or "",
            title=result.metadata.get("title", "") if result.metadata else "",
            links=all_links,
            success=True,
        )

    async def fetch_batch(self, urls: list[str]) -> list[PageResult]:
        """并发爬取多个页面"""
        tasks = [self.fetch(url) for url in urls]
        return await asyncio.gather(*tasks)
```

**Step 2: 写测试**

```python
# tests/test_crawler.py
import pytest
from src.crawler import Crawler

@pytest.mark.asyncio
async def test_fetch_success():
    crawler = Crawler()
    result = await crawler.fetch("https://httpbin.org/html")
    assert result.success
    assert result.url == "https://httpbin.org/html"
    assert len(result.raw_html) > 0

@pytest.mark.asyncio
async def test_fetch_failure():
    crawler = Crawler(timeout=5)
    result = await crawler.fetch("https://10.255.255.1/nonexistent")
    assert not result.success
```

**Step 3: Commit**

```bash
git add src/crawler.py tests/test_crawler.py
git commit -m "feat: add Crawl4AI crawler wrapper"
```

---

### Task 2.2: LLM 客户端（OpenRouter + Google fallback）

**Files:**
- Create: `src/llm.py`
- Create: `prompts/page_classify.txt`
- Create: `prompts/extract_links.txt`
- Create: `prompts/extract_nodes.txt`
- Create: `prompts/extract_password.txt`

**Step 1: 实现 LLM 客户端**

```python
"""LLM 客户端 — OpenRouter 免费模型 + Google AI Studio fallback"""

import os
import json
from openai import OpenAI


class LLMClient:
    """双通道 LLM 客户端"""

    # OpenRouter 免费模型列表（按优先级）
    OPENROUTER_FREE_MODELS = [
        "google/gemini-2.5-flash:free",    # 最快、免费
        "qwen/qwen2.5-7b-instruct:free",    # 中文好、免费
        "meta-llama/llama-4-scout:free",    # 备选
    ]

    def __init__(self):
        self.or_client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY", "sk-placeholder"),
        )
        self.google_client = OpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=os.getenv("GOOGLE_API_KEY", "placeholder"),
        )

    def ask(self, prompt: str, system: str = "", model: str = None) -> str:
        """发送 prompt，自动选择可用模型

        返回: {"response": "...", "model_used": "..."}
        """
        # 优先 OpenRouter 免费模型
        if model:
            models_to_try = [model]
        else:
            models_to_try = self.OPENROUTER_FREE_MODELS

        # 尝试 OpenRouter
        for m in models_to_try:
            try:
                resp = self.or_client.chat.completions.create(
                    model=m,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=2048,
                    temperature=0.1,
                )
                return resp.choices[0].message.content
            except Exception as e:
                last_error = str(e)
                continue

        # Fallback 到 Google AI Studio (Gemini Flash)
        try:
            resp = self.google_client.chat.completions.create(
                model="gemini-2.5-flash",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
            )
            return resp.choices[0].message.content
        except Exception:
            raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    def classify(self, markdown: str) -> dict:
        """分类页面类型"""
        prompt = load_prompt("page_classify.txt").format(content=markdown[:8000])
        result = self.ask(prompt)
        return json.loads(result)

    def extract_info(self, markdown: str, instruction: str) -> dict:
        """通用信息提取"""
        prompt = f"{instruction}\n\n页面内容:\n{markdown[:12000]}"
        result = self.ask(prompt)
        return json.loads(result)
```

**Step 2: 创建 Prompt 模板**

```
# prompts/page_classify.txt
分析以下网页内容，判断它属于哪种类型。只返回JSON：

{
  "page_type": "list" | "article" | "protected" | "other",
  "reason": "简短说明",
  "next_action": "extract_links" | "extract_nodes" | "find_password" | null
}

判断规则：
- list: 博客首页、文章列表，有多篇文章标题和链接
- article: 单篇文章，包含具体内容，可能有源代码块或下载链接
- protected: 需要密码才能查看内容，有输入框或密码提示
- other: 无法判断

网页内容：
{content}
```

```
# prompts/extract_nodes.txt
从页面中提取所有代理节点订阅链接（URL）。返回JSON：

{
  "links": [
    {"url": "https://...", "type": "txt" | "yaml", "label": "描述"}
  ],
  "passwords_found": ["1234"],
  "youtube_links": ["https://youtube.com/..."],
  "external_pwd_links": ["https://..."],
  "notes": "其他有用的发现"
}

页面内容：
{content}
```

```
# prompts/extract_password.txt
从内容中提取密码。密码通常是4位数字。返回JSON：

{
  "password": "1234" | null,
  "confidence": "high" | "medium" | "low",
  "source": "页面内" | "YouTube描述" | "YouTube字幕" | "OCR",
  "method_hint": "如何在这个页面使用密码（如：在输入框输入、执行js等）"
}

内容：
{content}
```

**Step 3: Commit**

```bash
git add src/llm.py prompts/
git commit -m "feat: add dual-channel LLM client with OpenRouter + Google fallback"
```

---

## Phase 3: 智能提取层

### Task 3.1: 页面分类器

**Files:**
- Create: `src/classifier.py`

```python
"""页面分类器 — LLM 判断页面是列表/详情/加密"""

from src.crawler import PageResult
from src.llm import LLMClient


class PageClassifier:
    """判断页面类型，决定下一步操作"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def classify(self, page: PageResult) -> dict:
        """分类页面"""
        # 先快速规则匹配（0 token 消耗）
        quick = self._quick_check(page)
        if quick["confidence"] == "high":
            return quick

        # 规则不确定时，交给 LLM
        return self.llm.classify(page.markdown)

    def _quick_check(self, page: PageResult) -> dict:
        """零成本快速规则检查"""
        import re

        html = page.raw_html.lower()

        # 检测密码保护
        pwd_indicators = [
            'password', '密码', 'decrypt', 'decipher',
            'cl-noindent', 'cl-input', 'cl-btn',  # yudou66 特征
            'secret-key',  # kkzui 特征
        ]
        has_pwd_field = any(kw in html for kw in pwd_indicators)
        has_input = '<input' in html and ('password' in html or 'secret' in html)

        if has_pwd_field or has_input:
            return {
                "page_type": "protected",
                "confidence": "high",
                "next_action": "find_password",
            }

        # 检测列表页
        article_patterns = [
            r'<article', r'class="post', r'class="entry',
            r'rel="bookmark"', r'class="blog',
        ]
        article_count = sum(1 for p in article_patterns if re.search(p, html))
        if article_count >= 2:
            return {
                "page_type": "list",
                "confidence": "medium",
                "next_action": "extract_links",
            }

        # 检测直链（vmess://, vless://, trojan://）
        if re.search(r'(vmess|vless|trojan|ss|ssr)://', page.raw_html):
            return {
                "page_type": "article",
                "confidence": "high",
                "next_action": "extract_nodes",
            }

        return {"page_type": "unknown", "confidence": "low", "next_action": None}
```

---

### Task 3.2: 智能提取器

**Files:**
- Create: `src/extractor.py`

```python
"""智能提取器 — 从页面中提取链接、密码、节点"""

import re
import json
from urllib.parse import urljoin
from src.crawler import PageResult
from src.llm import LLMClient


class Extractor:
    """LLM 驱动的智能提取"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def extract_article_links(self, page: PageResult, base_url: str) -> list[str]:
        """从列表页提取文章链接（优先规则，fallback LLM）"""
        # 规则: 提取所有 <a href> 去掉导航链接
        links = page.links

        # 过滤: 去除非文章链接（锚点、RSS、标签等）
        noise = ['#', 'tag', 'category', 'author', 'feed', 'rss', 'comment',
                 'javascript', 'login', 'admin']
        candidates = [
            urljoin(base_url, l) for l in links
            if not any(n in l.lower() for n in noise) and l.startswith(('http', '/'))
        ]

        # 去重 + 保留前 10 个
        seen = set()
        unique = []
        for url in candidates:
            if url not in seen and url != base_url:
                seen.add(url)
                unique.append(url)
        return unique[:10]

    def extract_node_links(self, page: PageResult) -> list[dict]:
        """从详情页提取节点订阅链接"""
        results = []

        # 规则1: 直接匹配协议链接
        patterns = {
            'vmess://': '.txt',
            'vless://': '.txt',
            'trojan://': '.txt',
            'ss://': '.txt',
            'ssr://': '.txt',
        }
        for proto, ext in patterns.items():
            for match in re.finditer(re.escape(proto) + r'[^\s<>"\'\[\]]+', page.raw_html):
                results.append({"url": match.group(), "type": "inline", "ext": ext})

        # 规则2: 匹配 .txt / .yaml 下载链接（保留旧 config 的 pattern 逻辑）
        file_matches = re.findall(
            r'(https?://[^\s<>"\']+\.(txt|yaml))',
            page.raw_html, re.IGNORECASE
        )
        for url, ext in file_matches:
            clean_url = url.rstrip(')');,.')
            results.append({"url": clean_url, "type": "file", "ext": f".{ext.lower()}"})

        # 如果有结果，直接返回（省 LLM 调用）
        if results:
            return results

        # 规则没结果时，用 LLM
        prompt = load_prompt("extract_nodes.txt").format(
            content=page.markdown[:8000]
        )
        llm_result = self.llm.ask(prompt)
        try:
            parsed = json.loads(llm_result)
            for link in parsed.get("links", []):
                results.append({
                    "url": link["url"],
                    "type": "llm_extracted",
                    "ext": f".{link['type']}",
                })
        except json.JSONDecodeError:
            pass

        return results

    def find_passwords(self, page: PageResult) -> list[dict]:
        """从页面中查找所有可能的密码"""
        results = []

        # 规则: 密码：XXXX 或 密码: XXXX
        for match in re.finditer(r'密码[：:]\s*(\d{4,6})', page.raw_html):
            results.append({
                "password": match.group(1),
                "confidence": "medium",
                "source": "page_regex",
            })

        # 规则: 提取 <input> 附近的数字
        if not results:
            # LLM 找密码
            prompt = load_prompt("extract_password.txt").format(
                content=page.markdown[:6000]
            )
            llm_result = self.llm.ask(prompt)
            try:
                parsed = json.loads(llm_result)
                if parsed.get("password"):
                    results.append(parsed)
            except json.JSONDecodeError:
                pass

        return results

    def find_youtube_links(self, page: PageResult) -> list[str]:
        """从页面中提取 YouTube 视频链接"""
        patterns = [
            r'(https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+)',
            r'(https?://youtu\.be/[\w-]+)',
        ]
        links = []
        for pat in patterns:
            links.extend(re.findall(pat, page.raw_html))
        return list(set(links))
```

---

### Task 3.3: YouTube 提取

**Files:**
- Create: `src/youtube.py`

用 yt-dlp 替代 pytubefix，更稳定、无需 OAuth。

```python
"""YouTube 视频信息提取 — yt-dlp 替代 pytubefix"""

import re
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
import tempfile


@dataclass
class YouTubeInfo:
    url: str
    title: str
    description: str
    subtitles_text: str = ""       # 合并后的字幕文本
    publish_date: str = ""
    success: bool = False
    error: str = ""


def extract_info(url: str) -> YouTubeInfo:
    """使用 yt-dlp 提取视频元数据 + 字幕"""

    # Step 1: 获取元数据（不下载视频）
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-playlist",
        "--skip-download",
        url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return YouTubeInfo(url=url, success=False, error=result.stderr)
        info = json.loads(result.stdout)
    except Exception as e:
        return YouTubeInfo(url=url, success=False, error=str(e))

    title = info.get("title", "")
    description = info.get("description", "")
    upload_date = info.get("upload_date", "")  # YYYYMMDD

    # 格式化日期
    publish_date = ""
    if upload_date:
        publish_date = f"{upload_date[:4]}-{upload_date[2:4]}-{upload_date[4:6]}"

    # Step 2: 提取字幕
    subtitles_text = _download_subtitles(url)

    return YouTubeInfo(
        url=url,
        title=title,
        description=description,
        subtitles_text=subtitles_text,
        publish_date=publish_date,
        success=True,
    )


def _download_subtitles(url: str) -> str:
    """下载字幕并合并为纯文本"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "yt-dlp",
            "--write-auto-sub",       # 自动生成字幕（YouTube 的 ASR）
            "--sub-lang", "zh-Hans,zh,en",  # 中文优先
            "--convert-subs", "vtt",  # 转换为 VTT 便于解析
            "--skip-download",
            "--output", f"{tmpdir}/%(id)s",
            url
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return ""

        # 找到字幕文件并读取
        for f in Path(tmpdir).glob("*.vtt"):
            text = _parse_vtt(f)
            if text:
                return text

    return ""


def _parse_vtt(path: Path) -> str:
    """解析 VTT 字幕文件，提取纯文本"""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 去掉 VTT 头部和时间戳
    lines = []
    for line in content.split("\n"):
        line = line.strip()
        if not line or "-->" in line or line.startswith("WEBVTT") or line.startswith("Kind:"):
            continue
        # 去掉 VTT 标签
        line = re.sub(r'<[^>]+>', '', line)
        if line:
            lines.append(line)

    return "\n".join(lines)


def find_password_in_video(info: YouTubeInfo) -> list[str]:
    """从视频信息中找密码（规则匹配，0 token 消耗）"""
    candidates = []

    # 搜索描述中含"码"的行
    for line in info.description.splitlines():
        if '码' in line:
            digits = re.findall(r'\d{4,6}', line)
            candidates.extend(digits)

    # 搜索字幕中含"码"的句子
    if info.subtitles_text:
        for line in info.subtitles_text.splitlines():
            if '码' in line:
                digits = re.findall(r'\d{4,6}', line)
                candidates.extend(digits)

    return list(set(candidates))
```

---

## Phase 4: 解密与流水线

### Task 4.1: 通用解密逻辑

**Files:**
- Create: `src/decryptor.py`

```python
"""通用解密逻辑 — Playwright 自动化 + LLM 驱动"""

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from src.crawler import PageResult


class Decryptor:
    """处理密码保护页面"""

    async def try_decrypt(
        self, url: str, password: str, timeout: int = 15
    ) -> PageResult:
        """尝试用密码解密页面

        使用 Crawl4AI 的 js_code 功能执行解密脚本。
        不硬编码脚本 — 让 LLM 分析页面后给出操作指令。
        """
        # 通用策略: 依次尝试常见解密方式
        strategies = [
            # 策略1: 发送 POST 请求（模拟表单提交）
            self._try_post,
            # 策略2: 在输入框输入密码 + 点击按钮
            self._try_fill_and_click,
        ]

        for strategy in strategies:
            result = await strategy(url, password, timeout)
            if result and result.success:
                return result

        return None

    async def _try_post(self, url: str, password: str, timeout: int) -> PageResult:
        """尝试 POST 密码"""
        import httpx
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, data={"password": password, "key": password})
            if resp.status_code == 200 and len(resp.text) > 100:
                # 成功获取内容
                return PageResult(
                    url=url, markdown="", raw_html=resp.text,
                    title="", links=[], success=True
                )
        return None

    async def _try_fill_and_click(
        self, url: str, password: str, timeout: int
    ) -> PageResult:
        """使用 Playwright 填写密码"""
        js_code = f"""
        (async () => {{
            // 找到输入框（尝试多种选择器）
            const inputs = document.querySelectorAll(
                'input[type="password"], input[name*="password"], ' +
                'input[name*="secret"], input[name*="key"], ' +
                'input.cl-input, .cl-noindent input, input'
            );
            if (inputs.length === 0) return 'no_input';

            // 填入密码
            const input = inputs[0];
            input.value = '{password}';
            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));

            // 找到按钮并点击
            const buttons = document.querySelectorAll(
                'button, input[type="submit"], .cl-btn, [class*="btn"]'
            );
            if (buttons.length > 0) {{
                buttons[0].click();
                await new Promise(r => setTimeout(r, 2000));
                return document.body.innerText;
            }}

            // 尝试回车提交
            input.form?.submit();
            await new Promise(r => setTimeout(r, 2000));
            return document.body.innerText;
        }})()
        """

        config = CrawlerRunConfig(
            page_timeout=timeout * 1000,
            js_code=js_code,
        )
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)

        if result and result.success:
            return PageResult(
                url=url,
                markdown=result.markdown or "",
                raw_html=result.html or "",
                title="",
                links=list(result.internal_links or []) + list(result.external_links or []),
                success=True,
            )
        return None
```

---

### Task 4.2: 数据流水线（输出 + 去重 + 合并）

**Files:**
- Create: `src/pipeline.py`

```python
"""数据处理流水线 — 下载、去重、格式化、合并"""

import os
import re
import yaml
import base64
import hashlib
from pathlib import Path
from dataclasses import dataclass
import httpx


@dataclass
class NodeItem:
    """统一节点项"""
    site_name: str
    url: str
    ext: str          # ".txt" | ".yaml"
    raw_content: str  # 原始内容
    cleaned_content: str = ""  # 去重格式化后的内容
    node_count: int = 0


class Pipeline:
    """数据处理流水线"""

    def __init__(self, output_dir: str = "nodes"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    async def process(self, item: NodeItem):
        """处理单个节点项"""
        if item.ext == ".txt":
            item.cleaned_content = self._process_txt(item.raw_content)
        elif item.ext == ".yaml":
            item.cleaned_content = self._process_yaml(item.raw_content)
        else:
            item.cleaned_content = item.raw_content

        # 写入文件
        filename = f"{item.site_name}{item.ext}"
        filepath = self.output_dir / filename
        filepath.write_text(item.cleaned_content, encoding="utf-8")

        return item

    def _process_txt(self, raw: str) -> str:
        """处理 V2Ray txt 文件

        1. base64 decode (如果编码了)
        2. 按行解析节点
        3. 去重（按协议+地址+端口 hash）
        4. 重新合并
        """
        # 尝试 base64 decode
        try:
            decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
        except Exception:
            decoded = raw  # 已经是明文

        # 按行分割，去重
        lines = [l.strip() for l in decoded.splitlines() if l.strip()]
        seen = set()
        unique = []
        for line in lines:
            h = hashlib.md5(line.encode()).hexdigest()
            if h not in seen:
                seen.add(h)
                unique.append(line)

        return "\n".join(unique)

    def _process_yaml(self, raw: str) -> str:
        """处理 Clash yaml 文件

        1. 解析 YAML
        2. 提取 proxies 列表
        3. 去重（按 server+port+type hash）
        4. 重新生成标准 proxy-groups
        """
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError:
            return raw

        if not data or "proxies" not in data:
            return raw

        # 去重
        seen = set()
        unique_proxies = []
        for proxy in data["proxies"]:
            if not isinstance(proxy, dict):
                continue
            key = f"{proxy.get('server','')}:{proxy.get('port','')}:{proxy.get('type','')}"
            h = hashlib.md5(key.encode()).hexdigest()
            if h not in seen:
                seen.add(h)
                unique_proxies.append(proxy)

        # 获取所有节点名
        all_names = [p.get("name", f"node-{i}") for i, p in enumerate(unique_proxies)]

        # 重新生成标准结构
        output = {
            "proxies": unique_proxies,
            "proxy-groups": [
                {
                    "name": "🚀 自动选择",
                    "type": "url-test",
                    "proxies": all_names,
                    "url": "http://www.gstatic.com/generate_204",
                    "interval": 300,
                },
                {
                    "name": "🌍 手动选择",
                    "type": "select",
                    "proxies": ["🚀 自动选择"] + all_names,
                },
            ],
            "rules": ["MATCH,🌍 手动选择"],
        }

        return yaml.safe_dump(output, allow_unicode=True, default_flow_style=False)

    def merge_txt(self) -> str:
        """合并所有 txt 文件为 merged.txt"""
        all_lines = []
        seen = set()
        for f in self.output_dir.glob("*.txt"):
            content = f.read_text(encoding="utf-8", errors="ignore")
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                h = hashlib.md5(line.encode()).hexdigest()
                if h not in seen:
                    seen.add(h)
                    all_lines.append(line)

        merged_path = self.output_dir / "merged.txt"
        merged_path.write_text("\n".join(all_lines), encoding="utf-8")
        return str(merged_path)

    def merge_yaml(self) -> str:
        """合并所有 yaml 文件的 proxies 为 merged.yaml"""
        all_proxies = []
        seen = set()
        for f in self.output_dir.glob("*.yaml"):
            if f.name == "merged.yaml":
                continue
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8"))
                for proxy in data.get("proxies", []):
                    key = f"{proxy.get('server','')}:{proxy.get('port','')}:{proxy.get('type','')}"
                    h = hashlib.md5(key.encode()).hexdigest()
                    if h not in seen:
                        seen.add(h)
                        all_proxies.append(proxy)
            except yaml.YAMLError:
                continue

        all_names = [p.get("name", f"node-{i}") for i, p in enumerate(all_proxies)]
        output = {
            "proxies": all_proxies,
            "proxy-groups": [
                {
                    "name": "🚀 自动选择",
                    "type": "url-test",
                    "proxies": all_names,
                    "url": "http://www.gstatic.com/generate_204",
                    "interval": 300,
                },
                {
                    "name": "🌍 手动选择",
                    "type": "select",
                    "proxies": ["🚀 自动选择"] + all_names,
                },
            ],
            "rules": ["MATCH,🌍 手动选择"],
        }

        merged_path = self.output_dir / "merged.yaml"
        merged_path.write_text(
            yaml.safe_dump(output, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        return str(merged_path)
```

---

## Phase 5: 主调度器

### Task 5.1: 主程序 — 统一爬取编排

**Files:**
- Create: `src/main.py`

```python
"""主调度器 — 替代 Scrapy 的 CrawlRunner

工作流:
1. 加载 config.yaml
2. 对每个站点: 爬取首页 → LLM分类 → 如果是列表页提取文章链接 → 爬取每篇文章
3. 对每篇文章: LLM分类 → 提取节点 OR 找密码解密
4. Pipeline: 处理每个节点的内容 → 写入文件
5. 合并: 生成 merged.txt + merged.yaml
6. 保存状态回 config.yaml
"""

import asyncio
import logging
from datetime import date

from src.config import load_config, save_config, Config, SiteConfig
from src.crawler import Crawler, PageResult
from src.llm import LLMClient
from src.classifier import PageClassifier
from src.extractor import Extractor
from src.youtube import extract_info as yt_extract, find_password_in_video
from src.decryptor import Decryptor
from src.pipeline import Pipeline, NodeItem

logger = logging.getLogger(__name__)


class SiteProcessor:
    """单个站点的处理流程"""

    def __init__(self, site: SiteConfig, llm: LLMClient, crawler: Crawler):
        self.site = site
        self.llm = llm
        self.crawler = crawler
        self.classifier = PageClassifier(llm)
        self.extractor = Extractor(llm)
        self.decryptor = Decryptor()

    async def run(self) -> list[NodeItem]:
        """处理单个站点，返回提取到的所有节点"""
        items = []
        logger.info(f"[{self.site.name}] Starting, type={self.site.type}")

        # Step 1: 爬取首页
        main_page = await self.crawler.fetch(self.site.start_url)
        if not main_page.success:
            logger.error(f"[{self.site.name}] Failed to fetch start_url")
            return items

        # Step 2: LLM 分类首页（列表页 or 直接是文章？）
        classification = await self.classifier.classify(main_page)
        logger.info(f"[{self.site.name}] Page type: {classification.get('page_type')}")

        # Step 3: 根据类型提取文章链接
        if classification.get("page_type") == "list":
            article_urls = self.extractor.extract_article_links(
                main_page, self.site.start_url
            )
            # 限制每站爬取文章数
            article_urls = article_urls[:3]
        else:
            # 首页本身就是文章
            article_urls = [self.site.start_url]

        logger.info(f"[{self.site.name}] Found {len(article_urls)} articles to process")

        # Step 4: 逐篇处理
        for article_url in article_urls:
            article_items = await self._process_article(article_url)
            items.extend(article_items)

        # 更新状态
        if items:
            self.site.up_date = date.today().strftime("%Y-%m-%d")

        logger.info(f"[{self.site.name}] Done, extracted {len(items)} items")
        return items

    async def _process_article(self, url: str) -> list[NodeItem]:
        """处理单篇文章：分类 → 提取 → 解密 → 获取节点"""
        items = []

        article = await self.crawler.fetch(url)
        if not article.success:
            return items

        # 尝试直接提取节点链接
        node_links = self.extractor.extract_node_links(article)

        if node_links:
            # 成功！下载每个链接
            for link_info in node_links:
                node_page = await self.crawler.fetch(link_info["url"])
                if node_page.success:
                    items.append(NodeItem(
                        site_name=self.site.name,
                        url=link_info["url"],
                        ext=link_info["ext"],
                        raw_content=node_page.raw_html,
                    ))
            return items

        # 没有直接找到节点 → 页面可能受保护
        # 尝试找密码
        passwords = self.extractor.find_passwords(article)

        # 找 YouTube 链接
        yt_links = self.extractor.find_youtube_links(article)

        # 如果有 YouTube 链接，从中提取密码
        for yt_url in yt_links:
            logger.info(f"[{self.site.name}] Extracting YouTube: {yt_url}")
            yt_info = yt_extract(yt_url)
            if yt_info.success:
                yt_passwords = find_password_in_video(yt_info)
                passwords.extend([{"password": p, "source": "youtube", "confidence": "medium"} for p in yt_passwords])

        # 尝试解密
        for pwd_info in passwords[:5]:  # 最多试5个密码
            decrypted = await self.decryptor.try_decrypt(url, pwd_info["password"])
            if decrypted and decrypted.success:
                self.site.last_password = pwd_info["password"]
                logger.info(f"[{self.site.name}] Decrypted with password: {pwd_info['password']}")

                # 从解密后的内容提取节点
                decrypted_links = self.extractor.extract_node_links(decrypted)
                for link_info in decrypted_links:
                    node_page = await self.crawler.fetch(link_info["url"])
                    if node_page.success:
                        items.append(NodeItem(
                            site_name=self.site.name,
                            url=link_info["url"],
                            ext=link_info["ext"],
                            raw_content=node_page.raw_html,
                        ))
                break

        return items


async def main(target: str = "all"):
    """主入口"""
    logging.basicConfig(level=logging.INFO)

    config = load_config()
    llm = LLMClient()
    crawler = Crawler(timeout=config.crawl.timeout_seconds)
    pipeline = Pipeline(output_dir=config.output.dir)

    # 选择目标站点
    sites = config.sites
    if target != "all":
        sites = [s for s in sites if s.name == target]
        if not sites:
            logger.error(f"Unknown target: {target}")
            return

    # 逐个处理站点
    all_items = []
    for site in sites:
        processor = SiteProcessor(site, llm, crawler)
        items = await processor.run()
        all_items.extend(items)

    # 逐项写入 Pipeline
    for item in all_items:
        await pipeline.process(item)

    # 合并
    pipeline.merge_txt()
    pipeline.merge_yaml()

    # 保存状态
    save_config(config)

    logger.info(f"All done. Processed {len(config.sites)} sites, {len(all_items)} items.")


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    asyncio.run(main(target))
```

---

## Phase 6: GitHub Actions

### Task 6.1: CI/CD 工作流

**Files:**
- Create: `.github/workflows/crawl.yml`

```yaml
name: AI Crawl Update

on:
  schedule:
    - cron: "0 4 * * *"   # 每天北京时间12:00
  workflow_dispatch:       # 手动触发

jobs:
  crawl:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Setup Playwright (Crawl4AI dependency)
        run: |
          pip install playwright
          playwright install --with-deps chromium

      - name: Install yt-dlp
        run: pip install yt-dlp

      - name: Install project
        run: pip install -e .

      - name: Run crawler
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
        run: python -m src.main all

      - name: Commit and push updates
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "Auto: daily node update"
          file_pattern: "nodes/* config.yaml"
          commit_user_name: github-actions[bot]
          commit_user_email: github-actions[bot]@users.noreply.github.com
```

---

## 实施顺序（推荐）

| 顺序 | Phase | 说明 |
|------|-------|------|
| 1 | Phase 1 | 项目初始化 (`pyproject.toml`, `config.yaml`, `src/config.py`) |
| 2 | Phase 2 | 核心层 (`crawler.py`, `llm.py` + 4个prompt模板) |
| 3 | Phase 3 | 提取层 (`classifier.py`, `extractor.py`, `youtube.py`) |
| 4 | Phase 4 | 流水线 (`decryptor.py`, `pipeline.py`) |
| 5 | Phase 5 | 主调度 (`main.py`) — 此时已可跑通完整流程 |
| 6 | Phase 6 | GitHub Actions 部署 |

**每个 Phase 完成即可独立测试**。Phase 5 跑通一个站点后，再全量测试所有 9 个站点。

---

## 关键差异总结

| | 旧 (Scrapy) | 新 (FreeNodeSpider) |
|---|---|---|
| 站点配置 | CSS 选择器 + 正则 pattern | 自然语言 description |
| 爬虫引擎 | Scrapy + Selenium | Crawl4AI (Playwright) |
| 新增站点 | 写 Spider 类 | 加一行 config.yaml |
| 页面理解 | 硬编码 XPath | LLM 语义理解 |
| 密码提取 | PwdGenerator 暴力 + pytubefix OCR | yt-dlp 字幕 + LLM 分析 |
| 反反爬 | RandomUserAgent | Crawl4AI 内置 |
| IP 地理标注 | GeoLocPipeline | 砍掉 |
| 合并逻辑 | 简单拼接 | 去重 + 自生成 proxy-groups |
| 依赖 | numpy, opencv, rapidocr, scikit-image | 去掉所有 ML/OCR 依赖 |
