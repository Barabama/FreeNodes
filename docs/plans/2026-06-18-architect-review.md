# 架构审查：FreeNodeSpider 实现计划

> 审查日期：2026-06-18 | 审查人：Claude (Architect Review)

---

## 一、已验证的技术事实

### 1. Crawl4AI API（v0.8.x）- **计划中的 API 用法有多处错误**

| 计划中写的 | 实际 API | 严重度 |
|-----------|---------|--------|
| `result.markdown` 是字符串 | `result.markdown` 是 `MarkdownGenerationResult` 对象，字段为 `.raw_markdown` `.fit_markdown` | 🔴 **阻断** |
| `result.internal_links` | `result.links["internal"]` 或 `result.links.get("internal", [])` | 🔴 **阻断** |
| `result.external_links` | 同上，`result.links["external"]` | 🔴 **阻断** |
| `result.metadata.get("title")` | `result.metadata` 可能为 None，需 `getattr` 安全访问 | 🟡 可能 crash |
| `AsyncWebCrawler()` 无参 | 正确，但建议传 `BrowserConfig` 控制 headless/proxy | 🟢 OK |

### 2. OpenRouter 免费层

- **50次/天**（未充值），充值 $10 后 → **1000次/天**（一次充值终生有效）
- `openrouter/free` 是智能路由器，自动根据请求特征选择合适的免费模型
- **正确做法**：用 `openrouter/free` 而**不是**硬编码 `google/gemini-2.5-flash:free` 列表
- 免费模型**不支持所有 feature**（如 tool calling 可能受限）

### 3. yt-dlp YouTube 字幕

- **可靠性问题**：2025 年底起 YouTube 对一些字幕请求增加了 POT (Proof of Token) 验证
- 无 cookie 的请求可能被拒（"Sign in to confirm you're not a bot"）
- 可能需要 `yt-dlp-ejs` 插件或 `--cookies-from-browser`
- **在 GitHub Actions 无头环境下尤其脆弱**

---

## 二、架构层面的问题

### 🔴 严重问题

#### 2.1 计划的核心矛盾：「自适应 AI」vs「硬编码策略」

计划宣称"LLM 自适应所有站点"，但实际代码中存在大量硬编码：

```python
# classifier.py - _quick_check 中的硬编码特征
'cl-noindent', 'cl-input', 'cl-btn',  # yudou66 的 CSS class
'secret-key',  # kkzui 的 HTML name

# decryptor.py - 硬编码的两种策略
strategies = [self._try_post, self._try_fill_and_click]

# extractor.py - 硬编码的协议正则
'vmess://', 'vless://', 'trojan://', 'ss://', 'ssr://'
```

**后果**：当 yudou66 更换前端框架、kkzui 改版、或出现一个新的密码保护方式时，`_quick_check` 和 `decryptor` 都会失效——与 Scrapy 版本的问题**完全相同**。

**建议**：
- `_quick_check` 的硬编码特征应从 `config.yaml` 读取，或完全砍掉只用 LLM
- `decryptor` 不应预设策略列表，而应让 LLM 阅读页面 HTML 后**生成**具体的解密 JavaScript
- 正则匹配协议链接可以保留（这是稳定的协议特征，不会变），但 CSS class 猜测必须去掉

#### 2.2 LLM 调用量被严重低估

当前计划对**每个站点**的 LLM 调用：

```
站点首页 → classify (1次)
  ├── 文章1 → classify (1次) → extract_nodes or find_password (1-2次)
  ├── 文章2 → classify (1次) → ...
  └── 文章3 → classify (1次) → ...

每个 site: 4-10 次 LLM 调用
9 个 site: 36-90 次 LLM 调用
```

50次/天的免费额度**勉强够用**，但没有任何余量给重试、debug、或新站点测试。

**建议**：
- 规则优先，LLM 兜底：`_quick_check` 如果 confidence=high 就跳过 LLM（计划已有但实现不够彻底）
- 合并请求：将 classify + extract 合并为一次 LLM 调用（"这是什么页面？如果有节点链接就提取它们"）
- 增加用量监控：记录每次调用的 token 数，在接近限额时降级到纯规则模式

#### 2.3 GitHub Actions 中 Crawl4AI 的隐性成本

Crawl4AI 依赖 Playwright，每次 `AsyncWebCrawler()` 启动需要：
- 下载/加载 Chromium（~300MB）
- 每个页面完整渲染（比纯 HTTP 请求慢 **10-50 倍**）

对于 9 个站点 × 3 篇文章 × 2 次页面（文章 + 链接下载）= **54+ 次浏览器渲染**，GitHub Actions 的 6 小时限制和 14GB 存储可能不够。

**建议**：
- **分层策略**：对简单页面（博客、订阅文件下载）用 `httpx` 纯 HTTP 请求；只在需要 JS 渲染的页面才用 Crawl4AI/Playwright
- 缓存 Playwright 浏览器到 GitHub Actions cache

---

### 🟡 中等问题

#### 2.4 config.yaml 的 type 字段设计不合理

```yaml
type: simple | youtube_password | external_password
```

**问题**：这是**预先分类**——在爬取之前就假设知道站点的类型。但同一个站点的不同文章可能类型不同（有的有密码、有的没有）。而且如果站点改版（比如 simple 站点加了密码保护），type 字段就误导了 LLM。

**建议**：去掉 type 字段，只保留 `description`。让 LLM 自己判断每篇文章的类型。

```yaml
# 改进后
- name: yudou66
  start_url: https://www.yudou789.top/
  description: >
    博客站点，部分文章可能需要密码才能查看内容。
    密码通常是4位数字。页面中可能含有YouTube视频链接，
    视频字幕中可能包含密码。
```

#### 2.5 Clash YAML 合并策略需要明确

计划中"自动生成 proxy-groups"的做法会**丢失原始站点的精选分组**（比如有的站点按地区分组、有的按协议分组）。需要确认这是期望的行为。

#### 2.6 缺少站点去重逻辑

多个站点可能共享同一个订阅文件。比如 `clashmeta` 的订阅链接实际上来自 `node.freeclashnode.com`，而 `freeclashnode` 本身可能也是一个站点。结果是同一个文件被抓了多次。

**建议**：在 Pipeline 中对**下载 URL** 做 content hash 去重，而不仅仅是在文件级别去重。

---

### 🟢 小问题

#### 2.7 .env.example 泄露了 API key

用户已标注 comment 指出。生产环境中必须移除。

#### 2.8 Python 版本声明

`pyproject.toml` 声明 `>=3.12`，但 Crawl4AI 支持 Python 3.10+。如果用户本地是 3.10/3.11 就无法安装。建议改成 `>=3.10` 或确认 GitHub Actions 用的是 3.12。

#### 2.9 用户已做的注释需要纳入

用户在计划中标注的关键意见：
- LLM 优先用 `openrouter/free` 路由而非硬编码模型列表
- 优先测试 API 可用性，暂不用本地部署
- 先做单个站点输出，合并功能后续再做
- 代码风格：Python 3.10+ union types (`str | None`)，英文代码+注释，中文 doc

---

## 三、改进建议汇总

### 必须修改（阻断项）

| # | 问题 | 修改 |
|---|------|------|
| 1 | `result.markdown` 是对象不是字符串 | `result.markdown.raw_markdown` 或 `result.markdown.fit_markdown` |
| 2 | `result.internal_links` 不存在 | `result.links["internal"]` 或 `result.links.get("internal", [])` |
| 3 | 硬编码的 CSS class 猜测 | 移除 `_quick_check` 中的 `cl-noindent` `secret-key` 等；或改为从 config 读取 |
| 4 | API key 泄露 | 从 `.env.example` 中移除真实 key |

### 强烈建议（架构改进）

| # | 问题 | 建议 |
|---|------|------|
| 5 | LLM 用量可能超过免费额度 | 合并 classify + extract 为一次调用；规则优先 LLM 兜底 |
| 6 | Crawl4AI/Playwright 太重 | 简单页面用 `httpx`；只在必要时启动浏览器 |
| 7 | type 字段预设分类 | 去掉 type，让 LLM 自行判断 |
| 8 | yt-dlp 在 CI 中不可靠 | 增加 cookie 机制 + 失败重试 + 降级到暴力破解 |
| 9 | decryptor 硬编码策略 | 让 LLM 阅读 HTML 后**生成**解密 JS |
| 10 | 站点间内容去重 | 对下载 URL 做 content hash |

### 建议采纳（用户反馈）

| # | 用户意见 | 行动 |
|---|---------|------|
| 11 | 使用 `openrouter/free` | 替换模型中硬编码的模型列表 |
| 12 | 先做单站点输出，合并后做 | 砍掉 Phase 4 的 merge 功能，Phase 5 以后再考虑 |
| 13 | 先测 API 可用性 | Phase 2 增加一个 `llm_test.py` 验证 OpenRouter 连通性 |
| 14 | Python 3.10+ 风格 | 全项目使用 `X | None` 替代 `Optional[X]` |

---

## 四、修订后的架构建议

### 修订后的核心循环

```
SiteConfig(只有 url + description, 无 type)
         │
         ▼
    fetch_page(url)
    ┌─────┴─────┐
    │ 规则匹配    │  (协议链接、日期、文件扩展名 — 0 token)
    │ 有结果?    │
    └──┬───┬────┘
       YES NO
       │   │
       │   ▼
       │  LLM Ask (一次调用完成分类+提取+决策):
       │  "这个页面里有什么？如果是博客列表提取文章链接,
       │   如果是文章提取订阅链接,
       │   如果需要密码就找密码的线索(YouTube/外部链接/输入框),
       │   如果什么都没找到就告诉我"
       │   │
       └───┼───→ NodeItem list
           │
      ┌────┴────┐
      │ 需要解密? │
      │ LLM 给出 │
      │ js_code  │ → Crawl4AI 执行 → 重新提取
      └─────────┘
```

### 修订后的项目结构

```
FreeNodeSpider/
├── config.yaml           # 只有 url + description
├── src/
│   ├── crawler.py        # 双模式: httpx (轻量) + Crawl4AI (JS需要时)
│   ├── llm.py            # openrouter/free 路由 + Google fallback
│   ├── extractor.py      # 规则提取 + LLM 提取（合并 classify+extract）
│   ├── youtube.py        # yt-dlp (增加 cookie 策略)
│   ├── pipeline.py       # 单站点输出（暂不做 merge）
│   └── main.py           # 主调度
├── tests/
│   └── llm_test.py       # API 连通性测试（优先实现）
```

---

## 五、结论

**计划整体方向正确**——Crawl4AI + LLM 替代 Scrapy + CSS 选择器是一个好的架构选择。但计划存在三个层面需要修正：

1. **代码层**：Crawl4AI API 调用方式需要更新到 v0.8.x（3 处阻断性错误）
2. **设计层**：宣布"AI 自适应"但保留了大量硬编码策略，形成矛盾。需下定决心：要么全用 AI（贵但灵活），要么规则+AI 分层（便宜但需要维护规则）
3. **运维层**：LLM 免费额度、Playwright 性能、yt-dlp 可靠性都需要在 GitHub Actions 环境中实际测试

**推荐路径**：先写一个最小可行的 `main.py` 跑通 clashmeta（最简单的站点），验证 Crawl4AI + LLM + Pipeline 的完整链路，再逐步扩展到其他站点。**不要一开始就企图覆盖全部 9 个站点。**
