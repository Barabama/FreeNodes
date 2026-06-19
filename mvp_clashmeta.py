#!/usr/bin/env python
"""MVP: clashmeta — Rule-first + LLM fallback + Self-healing.

流程:
  1. 加载 config → 查 link_pattern
  2. link_pattern 存在且命中 → 正则提取 (0 token)
  3. link_pattern 不存在/失效 → LLM 提取 → 生成 pattern → 四层校验
  4. 校验通过 → 回写 config.yaml (自愈成功)
  5. httpx 下载 → 去重 → 输出 nodes/

Usage:
    python mvp_clashmeta.py
"""
import asyncio
import os
import re
import sys
from datetime import date
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, ".")

from src.config import load_config, save_config
from src.crawler import fetch_page, download_file
from src.pipeline import save

BASE_URL = "https://clash-meta.github.io"
BLOG_URL = f"{BASE_URL}/free-nodes/"
MAX_ARTICLES = 3


# ── 文章选择：始终规则 ──

def pick_newest_articles(blog) -> list[dict]:
    """从 Crawl4AI link 列表中按日期选最新 N 篇.

    日期来源：标题文字 "6月18日" 或 URL 路径 "2026-6-18"
    """
    articles: list[dict] = []
    for link in blog.links:
        text = link.get("text", "")
        href = link.get("href", "")

        # 从标题提取日期: "6月18日更新" → 2026-06-18
        m = re.search(r"(\d{1,2})月(\d{1,2})日", text)
        if m:
            d = f"{date.today().year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        else:
            # 从 URL 路径提取日期: /free-nodes/2026-6-17-xxx.htm
            m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", href)
            if m:
                d = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            else:
                continue

        # 排除非文章页: 分页 / 分类 / 首页
        if href in ("/free-nodes/", "/", "") or "category" in href or "page-" in href:
            continue

        full = urljoin(BASE_URL, href)
        articles.append({"url": full, "date": d, "text": text[:80]})

    # 去重 → 日期降序 → 取 top N
    seen: set[str] = set()
    unique: list[dict] = []
    for a in sorted(articles, key=lambda x: x["date"], reverse=True):
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)
    return unique[:MAX_ARTICLES]


# ── 订阅链接提取：规则优先 + LLM 兜底 + 自愈 ──

def extract_by_pattern(html: str, pattern: str) -> list[str]:
    """用已保存的正则提取订阅链接."""
    compiled = re.compile(pattern, re.IGNORECASE)
    matches = compiled.findall(html)
    # re.findall 对单组返回字符串列表，多组返回元组列表
    if matches and isinstance(matches[0], tuple):
        matches = [m[0] for m in matches]
    # 清洗尾部标点
    cleaned: list[str] = []
    for m in matches:
        if isinstance(m, str) and m.startswith("http"):
            m = re.sub(r'[),;.\'"]+$', "", m)
            cleaned.append(m)
    return cleaned


async def extract_with_fallback(page, site_cfg) -> tuple[list[str], bool]:
    """提取订阅链接：先规则、后 LLM、成功后自愈.

    Returns: (links, pattern_saved)
    """
    html = page.html

    # ── Step 1: 规则优先 ──
    if site_cfg.link_pattern:
        result = extract_by_pattern(html, site_cfg.link_pattern)
        if result:
            print(f"    regex hit: {len(result)} links (0 LLM)")
            return result, False

        print(f"    regex miss: pattern failed, falling back to LLM (failed_count={site_cfg.failed_count})")
        site_cfg.failed_count += 1

    # ── Step 2: LLM 兜底 ──
    from src.llm import LLM
    llm = LLM()

    llm_result = llm.extract_links(page.markdown)
    all_links = llm_result.get("txt", []) + llm_result.get("yaml", [])
    if not all_links:
        print("    LLM also found nothing, giving up")
        return [], False

    print(f"    LLM found {len(all_links)} links")
    for link in all_links[:3]:
        print(f"       {link}")

    # ── Step 3: LLM 生成正则 ──
    new_pattern = llm.generate_pattern(all_links, html)
    if not new_pattern:
        print("    LLM could not generate pattern, skipping self-heal")
        return all_links, False

    print(f"    generated pattern: {new_pattern[:80]}...")

    # ── Step 4: 三层校验（取消跨文章验证）
    if llm.verify_pattern(new_pattern, all_links, html):
        print("    pattern verified! writing to config")
        site_cfg.link_pattern = new_pattern
        site_cfg.failed_count = 0
        return all_links, True
    else:
        print("    pattern rejected by verification, keeping null")
        return all_links, False


# ── 主流程 ──

async def main():
    print("=" * 60)
    print("MVP: clashmeta — Rule-first + LLM fallback + Self-healing")
    print("=" * 60)

    config = load_config()
    site = config.sites[0]
    pattern_saved = False

    print(f"\nSITE: {site.name}")
    print(f"URL:  {site.start_url}")
    print(f"Cfg:  filter top {MAX_ARTICLES} articles, pattern={site.link_pattern or 'null (LLM)'}")
    print()

    # 1. 爬博客首页
    print("[1/4] Fetching blog page via Crawl4AI...")
    blog = await fetch_page(BLOG_URL)
    print(f"       got {len(blog.links)} links, {len(blog.markdown)} chars markdown\n")

    # 2. 选最新文章
    print(f"[2/4] Picking newest {MAX_ARTICLES} articles by date...")
    articles = pick_newest_articles(blog)
    for a in articles:
        print(f"       [{a['date']}] {a['url']}")
    if not articles:
        print("       FATAL: no articles found!"); return

    # 3. 逐篇提取订阅链接
    print(f"\n[3/4] Processing {len(articles)} articles...")
    all_txt: set[str] = set()
    all_yaml: set[str] = set()

    for i, a in enumerate(articles):
        print(f"  [{i+1}/{len(articles)}] {a['url']}")
        page = await fetch_page(a["url"], timeout_ms=60000)
        if not page.success:
            print(f"    skipping (fetch failed: {page.error[:100]})")
            continue

        links, saved = await extract_with_fallback(page, site)
        if saved:
            pattern_saved = True

        for url in links:
            if url.endswith(".txt"):
                all_txt.add(url)
            elif url.endswith(".yaml"):
                all_yaml.add(url)

    total = len(all_txt) + len(all_yaml)
    print(f"\n       total: {len(all_txt)} txt + {len(all_yaml)} yaml = {total} unique links")
    if not total:
        print("       FATAL: no subscription links found!")
        return

    # 自愈：回写 config
    if pattern_saved:
        print("\n  >>> Self-healing: saving updated config...")
        save_config(config)

    # 4. 下载 + 输出
    print(f"\n[4/4] Downloading {total} files (up to 3 retries each)...")
    txt_content: list[str] = []
    yaml_content: list[str] = []

    async def _download_with_retry(url: str, retries: int = 3) -> str | None:
        for attempt in range(retries):
            try:
                return await download_file(url)
            except Exception as e:
                msg = str(e) or "timeout"
                if attempt < retries - 1:
                    print(f"    retry {attempt + 1}/{retries} {url} ({msg})")
                    await asyncio.sleep(1.5)
        return None

    for url in sorted(all_txt):
        body = await _download_with_retry(url)
        if body:
            txt_content.append(body)
            print(f"  OK  txt: {url} ({len(body)}B)")
        else:
            print(f"  FAIL txt: {url}")

    for url in sorted(all_yaml):
        body = await _download_with_retry(url)
        if body:
            yaml_content.append(body)
            print(f"  OK  yaml: {url} ({len(body)}B)")
        else:
            print(f"  FAIL yaml: {url}")

    if txt_content:
        save("clashmeta", ".txt", "\n".join(txt_content))
    if yaml_content:
        save("clashmeta", ".yaml", "\n---\n".join(yaml_content))

    print()
    print("=" * 60)
    print("RESULT")
    print(f"  downloaded:   {len(txt_content)} txt + {len(yaml_content)} yaml")
    print(f"  pattern:      {'freshly self-healed' if pattern_saved else site.link_pattern or '(null)'}")
    print(f"  output dir:   nodes/")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
