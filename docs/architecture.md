# FreeNodeSpider 架构设计

> 设计日期：2026-06-19 | 取代旧版 `ai-crawler-plan.md`（已合并到本文）

---

## 一、核心问题

现有 Scrapy 方案每站点需要硬编码 CSS/XPath 选择器 + 蜘蛛逻辑。网站改版 = 代码更新。本项目目标：

1. **零 CSS 选择器** — 站点理解交给 LLM，不改代码
2. **规则优先，LLM 兜底** — 稳定时 0 token，改版时自愈
3. **多供应商路由** — 不依赖单一家 LLM 服务
4. **并行爬取** — 多站点同时处理

---

## 二、架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                       Scheduler                             │
│  并行调度器 — 同时处理 N 个站点，管理生命周期和输出归集        │
└──────────────────┬──────────────────────────────────────────┘
                   │ 分发站点任务
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│ Site A   │ │ Site B   │ │ Site C   │
│ pipeline │ │ pipeline │ │ pipeline │  ← 并行 (asyncio)
└────┬─────┘ └────┬─────┘ └────┬─────┘
     │            │            │
     └─────┬──────┴──────┬─────┘
           ▼             ▼
     ┌──────────┐  ┌──────────┐
     │ Crawler  │  │LLM Router│       ← 共享层
     │ 双引擎   │  │ 三层路由  │
     └──────────┘  └──────────┘
                       │
               ┌───────┼───────┐
               ▼       ▼       ▼
          OpenRouter Cerebras Opencode
                       │
           ┌───────────┘
           ▼
     ┌──────────┐
     │Pipeline  │         ← 单站点级别
     │去重+输出  │
     └────┬─────┘
          ▼
     ┌──────────┐
     │ Merge    │         ← 全局级别
     │合并输出   │
     └──────────┘
```

### 关键设计原则

| 原则 | 含义 |
|------|------|
| **Share-nothing 站点隔离** | 每个站点独立处理，互不阻塞。A 站失败不影响 B 站 |
| **分层降级** | 每一层都有明确的失败路径：规则→LLM→空结果 |
| **配置即代码** | 新站点 = 加一行 yaml，不改 Python |
| **0 状态单次运行** | 每次运行是幂等的（除自愈回写 config 外） |

---

## 三、架构分层

### 第 1 层：配置层（Config Layer）

**职责：** 管理站点定义、运行策略、持久化运行时状态。

```
config.yaml
├── sites[]                  # 站点列表
│   ├── name                 # 站点标识
│   ├── start_url            # 入口 URL
│   ├── description          # 自然语言站点描述（告诉 LLM 这是什么站）
│   └── link_pattern         # 订阅链接正则（null=待LLM生成，非空=直接命中）
│
├── crawl                    # 爬取策略
│   ├── max_articles         # 每站最多取的文章数
│   ├── concurrency          # 并行站点数
│   └── timeout              # 页面超时秒数
│
├── llm                      # LLM 路由配置
│   ├── providers[]          # 供应商定义
│   │   ├── name             # 标识
│   │   ├── base_url         # API 地址
│   │   ├── models[]         # 可用模型
│   │   └── weight           # 路由权重 (0-100)
│   └── task_routing         # 按任务类型的路由权重覆盖
│
└── output
    └── dir                  # 输出目录
```

**与其他层的关系：**
- Scheduler 启动时一次加载 Config，站点循环复用
- Pipeline 完成后更新 Config（更新 up_date、回写 link_pattern）

---

### 第 2 层：调度层（Scheduler）

**职责：** 控制并行度，分发站点任务，归集输出。

```
Scheduler
├── 读取 Config → 得到待处理站点列表
├── 建立 asyncio 并发池（Semaphore 控制上限）
├── 同时运行 N 个 SiteProcessor
│   └── 每个 SiteProcessor 负责一个站点的完整周期
├── 等待全部完成（gather）
└── 触发 Merge（跨站点去重合并）
```

**并行策略：**

| 参数 | 值 |
|------|-----|
| 默认并发数 | 3（可在 config 调整） |
| 调度方式 | `asyncio.Semaphore` + `gather` |
| 失败处理 | 单站失败不影响其他站，日志记录 |
| 超时 | 每站总超时 10 分钟 |

**注意点：**
- 控制并发数避免 IP 被封（同一域名顺次处理）
- 共享 Crawler 和 LLM Router 实例（避免重复初始化 Playwright）

---

### 第 3 层：爬取层（Crawler Layer）

**职责：** 双引擎获取页面/文件内容。

```
Crawler
├── Engine A: Crawl4AI (Playwright)
│   ├── 用于：博客首页（需 JS 渲染的文章列表）
│   ├── 用于：文章详情页（需 JS 渲染的订阅链接区）
│   └── 输出：结构化 Page（markdown + html + links）
│
├── Engine B: httpx
│   ├── 用于：直接下载 .txt / .yaml 订阅文件
│   └── 输出：原始文件文本
│
└── 附加功能：
    ├── 自动重试（3 次，指数退避）
    ├── 超时控制（页面 60s / 文件 60s）
    └── 相对路径转绝对路径
```

**爬取流程：**
```
fetch_page(url)
  └→ Crawl4AI 渲染
      └→ 成功？ → 返回 Page
      └→ 失败？ → 重试 → 3 次全失败 → 返回 error Page

download_file(url)
  └→ httpx GET
      └→ 成功？ → 返回文本
      └→ 403/404？ → 记录日志，跳过（CDN 封锁常见）
      └→ 超时？ → 重试 → 3 次全失败 → 跳过
```

---

### 第 4 层：LLM 路由层（LLM Router）

**职责：** 管理多供应商调用，封装路由逻辑，提供统一接口。

```
LLM Router
├── Provider Registry
│   ├── OpenRouter (权重 50)
│   │   ├── base_url: https://openrouter.ai/api/v1
│   │   └── models: [openrouter/free]
│   │
│   ├── Cerebras (权重 30)
│   │   ├── base_url: https://api.cerebras.ai/v1
│   │   └── models: [zai-glm-4.7, gpt-oss-120b]
│   │
│   └── Opencode (权重 20)
│       ├── base_url: https://opencode.ai/zen/v1
│       └── models: [deepseek-v4-flash-free]
│
├── Task Routing Rules
│   ├── extract_links:    openrouter=60% / cerebras=30% / opencode=10%
│   ├── generate_pattern: openrouter=70% / cerebras=30% / opencode=0%
│   └── (其他任务: 按默认权重)
│
├── Provider Health Tracker
│   ├── 成功/失败计数
│   ├── 连续失败 → 临时禁用 → 定期恢复检查
│   └── 所有失败 → 兜底空结果
│
└── Unified Interface
    └── ask(prompt, task_type) → 返回文本
```

#### LLM 路由选择：加权路由，而非纯随机

**不推荐纯随机的原因：**

| 问题 | 场景 | 后果 |
|------|------|------|
| 质量不一致 | 复杂提取分配到弱模型 | 漏链、错链 |
| 不可复现 | 同一站点每次不同供应商 | 调试困难 |
| 供应商差异 | Cerebras 是推理模型（输出在 reasoning 字段） | 需要特殊处理，不该和普通模型对等随机 |

**推荐方案：任务感知的加权路由**

1. 按任务类型预定权重（同类型任务同一供应商 → 可复现）
2. 权重内随机（同权重内均匀分布 → 避免单 key 限流）
3. 失败时自动降级（当前供应商失败 → 移除 → 从剩余重选）
4. 健康追踪（连续失败 5 次的供应商临时禁用 30 分钟）

```
示例：extract_links 任务
  1. 权重表: OpenRouter 60% / Cerebras 30% / Opencode 10%
  2. 加权随机命中 → OpenRouter
  3. OpenRouter 429 → 移除, 重选 → Cerebras
  4. Cerebras 失败 → Opencode
  5. 全部失败 → 返回空结果（不抛异常）
```

---

### 第 5 层：站点处理层（Site Processor）

**职责：** 单个站点的完整处理周期，含规则提取 + LLM 兜底 + 自愈。

```
SiteProcessor.run()
│
├── 1. fetch_page(start_url)
│     └→ Crawl4AI → Page
│
├── 2. pick_newest_articles(Page)
│     └→ 从标题和 URL 中正则匹配日期 → 返回最新 N 篇
│        (纯规则，不需要 LLM)
│
├── 3. for each article:
│     ├── 3a. fetch_page(article_url)
│     ├── 3b. extract_links_with_fallback()
│     │     ├── link_pattern 存在 → 正则提取 (0 token) → 跳到 3c
│     │     ├── link_pattern 不存在或失效 → LLM 提取
│     │     ├── LLM 提取成功 → 生成正则 → 三层校验
│     │     └── 校验通过 → 回写 config (自愈)
│     └── 3c. download_files(txt/yaml)
│
├── 4. save(site_nodes)
│     └→ base64 decode → 去重 → 写入 nodes/{site}.{txt|yaml}
│
└── 5. 更新 config up_date
```

**自愈流程（关键创新）：**
```
link_pattern = null
  │
  ▼
LLM 提取到链接 → 10 个 URL
  │
  ▼
LLM 观察 URL 规律 → 生成正则
  │
  ▼
三层校验:
  1. 语法: re.compile 不抛异常？
  2. Recall: 正则能匹配到所有已知链接？
  3. Precision: 正则不会匹配导航/广告？
  │
  全部通过 → 写入 config → 下次 0 token
  任一层失败 → 保持 null → 下次再试
```

---

### 第 6 层：输出层（Pipeline + Merge）

**职责：** 去重格式化每个站点的输出，合并为全量文件。

```
Site Pipeline (per site)
├── V2Ray (.txt)
│   ├── base64 decode → 可读节点列表
│   ├── 按行 hash 去重
│   └── 写入 nodes/{site}.txt
│
└── Clash (.yaml)
    ├── YAML 解析 → 提取 proxies 列表
    ├── 按 server:port:type hash 去重
    └── 写入 nodes/{site}.yaml

Global Merge (post-processing)
├── merge_txt()
│   ├── 读取所有 {site}.txt
│   ├── 全局去重
│   └── 写入 merged.txt
│
└── merge_yaml()
    ├── 读取所有 {site}.yaml
    ├── 提取所有 proxies
    ├── 全局去重
    ├── 自动生成 proxy-groups + rules
    └── 写入 merged.yaml
```

---

## 四、数据流完整链路

```
config.yaml
    │
    ▼
Scheduler.dispatch()
    │
    ├── Site A ──┬── Crawler ──┬── LLM Router ──┬── Pipeline ──┬── nodes/clashmeta.txt
    │            │             │               │              │
    │            │ 博客页/     │ OpenRouter/   │ 去重/        └── nodes/clashmeta.yaml
    │            │ 文章页      │ Cerebras/     │ 格式化
    │            │ 订阅文件    │ Opencode      │
    │            └─────────────┘               │
    │                                          │
    ├── Site B ──┬── Crawler ──┬── LLM Router ──┘
    │            └─────────────┘
    │
    └── Site C ──┬── Crawler
                 └─────────────
                         │
                         ▼
                    Merge ──→ merged.txt
                             merged.yaml
                         │
                         ▼
                    update config.yaml (up_date, link_pattern)
```

---

## 五、项目目录结构

```
FreeNodeSpider/
├── config.yaml               # 站点配置 + LLM 路由配置 + 运行策略
├── .env                      # API keys（不入 git）
├── src/
│   ├── __init__.py
│   ├── main.py               # CLI 入口，初始化 + 启动 Scheduler
│   ├── scheduler.py          # 并行调度器（asyncio 并发池）
│   ├── config.py             # config 加载 + 持久化
│   ├── site_processor.py     # 单站点处理周期（提取+自愈+保存）
│   ├── crawler.py            # 双引擎爬取（Crawl4AI + httpx）
│   ├── llm_router.py         # LLM 路由层（供应商管理+任务路由+健康追踪）
│   ├── pipeline.py           # 单站输出（去重+格式化）
│   └── merger.py             # 全局合并（merged.txt/yaml）
├── nodes/                    # 输出目录（制品）
├── tests/                    # 测试
└── .github/workflows/        # CI/CD
```

**与旧设计对比：**

| 旧文件 | 新文件 | 变化 |
|--------|--------|------|
| `mvp_clashmeta.py` 252行 | `main.py` + `scheduler.py` + `site_processor.py` | 从单体拆分出调度和站点处理 |
| `src/llm.py` 内嵌 fallback | `src/llm_router.py` | 抽出独立路由层，加权重分配 + 健康追踪 |
| `src/pipeline.py` 单纯输出 | `src/pipeline.py` + `src/merger.py` | 分离单站输出和全局合并 |
| `src/config.py` | `src/config.py` | 新增 LLM 路由配置字段 |

---

## 六、实施优先级

| 阶段 | 内容 | 前置 |
|------|------|------|
| **P0** | Config 增加 LLM 路由配置 + `src/llm_router.py` 实现路由/健康/权重 | 现有 `src/llm.py` |
| **P1** | `src/scheduler.py` + `src/site_processor.py` 从 `mvp_clashmeta.py` 拆分 | P0 |
| **P2** | `src/merger.py` 全局合并 | P1 |
| **P3** | `src/main.py` CLI | P1-P2 |
| **P4** | GitHub Actions workflow | P3 |
| **P5** | 扩展到其他 simple 站点 | P1 |
| **P6** | YouTube / 密码站点 | P5 |
