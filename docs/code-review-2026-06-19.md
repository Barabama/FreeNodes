# Code Review Report — FreeNodeSpider

> **审查日期:** 2026-06-19
> **审查阶段:** P0-P5 完成，P2 Merger 刚落地，P4/P6 尚未开始
> **审查工具:** Claude Code `code-review` skill (high effort, 8 angles, 1-vote verify)
> **审查范围:** `src/` 全部模块 + `main.py` + `tests/`

---

## 项目当前状态

### 业务逻辑简述

FreeNodeSpider 是一个 AI 驱动的代理节点爬虫，核心流程：

```
config.yaml → Scheduler(并行) → SiteProcessor(单站)
  ├─ Crawl4AI 爬取博客首页
  ├─ 规则提取文章日期 → 选择最新 N 篇
  ├─ 正则提取订阅链接 (0 token) / LLM 兜底 (花 token) / 自愈回写
  ├─ httpx 下载 .txt/.yaml 订阅文件
  └─ pipeline 去重输出 nodes/{site}.txt|yaml
                                    ↓
                              Merger(全局合并)
                               ├─ merged.txt
                               ├─ merged.yaml (物理合并)
                               └─ provider.yaml (按地区分组)
```

**LLM 路由:** OpenRouter → Cerebras → Opencode 加权随机 + 健康追踪

### 完成路线图

| 阶段 | 状态 | 内容 |
|------|------|------|
| P0 | ✅ | LLM 路由层 (加权路由 + 健康追踪 + regex 后置提取) |
| P1 | ✅ | Scheduler + SiteProcessor (并发调度 + 错误隔离) |
| P2 | ✅ | Merger 全局合并 (txt/yaml/provider 三种输出 + 地区分组) |
| P3 | ✅ | CLI 入口 (argparse + 单站点支持) |
| P4 | ⏳ | GitHub Actions CI/CD |
| P5 | ✅ | 8 个 simple 博客站点接入 |
| P6 | ⏳ | YouTube / 密码保护站点 |

### 规模

| 指标 | 值 |
|------|-----|
| 源文件 | 8 (`src/*.py` + `main.py`) |
| 测试文件 | 4 (`test_*.py`) |
| 测试数量 | **98** (全部通过) |
| 配置文件 | 9 个站点, 3 个 LLM 供应商 |
| 上一次运行输出 | 4 个站点产出数据, 209 节点去重合并 |

---

## 审查发现

20 个发现项，按严重度排序前 **10 个**。

### 🔴 严重 (3)

#### 1. `all_links` 覆盖导致 "other" 分类和内联协议链接丢失

| 字段 | 值 |
|------|-----|
| **文件** | `src/site_processor.py` |
| **行号** | 192, 210 |
| **类型** | 逻辑错误 |

第 192 行从 LLM 提取结果构建 `all_links`：
```python
all_links = llm_result.get("txt", []) + llm_result.get("yaml", []) + llm_result.get("other", [])
```

但第 210 行无条件覆盖为只保留 txt 和 yaml：
```python
all_links = llm_result.get("txt", []) + llm_result.get("yaml", [])
```

导致：
- `other` 分类（`nodebuf.com/.../preview` 等非标准订阅链接）**丢失**
- 第 197-209 行的 inline-only 哨兵逻辑 (`all_links = inline_links[:1]`) **完全成为死代码**
- 内联协议链接 (`ss://`, `vmess://` 等) 被正确提取但**静默丢弃**

**影响:** cfmem 等站点的 `nodebuf.com` 订阅链接会被提取但不会进入下载流程。站点最终返回"no subscription links found"。

#### 2. `except Exception: continue` 吞掉 LLM 调用错误

| 字段 | 值 |
|------|-----|
| **文件** | `src/llm_router.py` |
| **行号** | 216-217 |
| **类型** | 错误处理缺失 |

```python
except Exception:
    continue  # 静默跳过, 无日志
```

每一轮模型调用失败时，没有任何日志记录失败原因（网络超时、API key 过期、模型下线、速率限制）。操作员无法获知供应商为何失败。

**影响:** API key 过期时，所有该供应商的模型静默失败，fallback 到下一个供应商（或返回空）。操作员看到"提取结果为空"但排查需要数小时。

#### 3. 同步 OpenAI 客户端阻塞 asyncio 事件循环

| 字段 | 值 |
|------|-----|
| **文件** | `src/llm_router.py` |
| **行号** | 96-114 |
| **类型** | 性能/并发错误 |

`LLMRouter._try_provider()` 使用同步的 `OpenAI().chat.completions.create()`，被 `SiteProcessor._extract_links()`（async）调用。每个 LLM 请求（5-20 秒）期间，**整个事件循环被阻塞**。

```
时间线:
  Site A: ──[fetch]──[LLM 5s 阻塞]──[download]──
  Site B:                 ──等待 5s──[fetch]──[LLM]──
  Site C:                 ──等待 5s────等待 5s──[fetch]──
```

**影响:** 本应并行的站点处理，因 LLM 调用阻塞退化为近似串行。总耗时 = 各站点 LLM 调用时间之和，而非最大值。

---

### 🟡 高 (3)

#### 4. `except Exception: continue` 吞掉 YAML 解析错误

| 字段 | 值 |
|------|-----|
| **文件** | `src/merger.py` |
| **行号** | 183-184 |
| **类型** | 错误处理缺失 |

`_build_provider` 中读取 YAML 文件进行地区检测时，解析失败的文件被静默跳过。一个部分下载产生的截断 YAML 会导致该站点的所有节点从 `provider.yaml` 中消失，没有任何警告。

#### 5. `save_config` 无条件覆盖全量配置

| 字段 | 值 |
|------|-----|
| **文件** | `main.py` |
| **行号** | 42 |
| **类型** | 数据竞争 |

单站点运行 (`python main.py clashmeta`) 后，`save_config` 将内存中的完整 Config 对象（包含 9 个站点）写回磁盘。如果有人在运行期间编辑了 `config.yaml`（如添加新站点），这些编辑将被覆盖。

#### 6. 跨年日期解析错误

| 字段 | 值 |
|------|-----|
| **文件** | `src/site_processor.py` |
| **行号** | 252 |
| **类型** | 逻辑缺陷 |

中文月份日期格式 "M月D日" 不含年份，代码使用 `date.today().year`：
```python
d = f"{date.today().year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
```

跨年边界（如 1 月 1 日）时，12 月的文章会被分配当前年份 → 错误的未来日期。

---

### 🟢 低 (4)

#### 7. 假阳性 pattern 自愈后不可撤销

| 字段 | 值 |
|------|-----|
| **文件** | `src/site_processor.py:230-231`, `src/config.py:71-72` |
| **类型** | 可用性 |

验证通过的正则写入 `config.yaml` 后，后续运行直接命中正则，**永不触发 LLM fallback**。一个过宽的正则（如 `https://site\.com/[^"'\<\s]+`）会匹配大量非订阅 URL（图片、脚本），导致下载数百个无效文件。

#### 8. Clash 基础配置重复

| 字段 | 值 |
|------|-----|
| **文件** | `src/merger.py` 第 126 行和 224 行 |
| **类型** | 代码重复 |

`_merge_yaml` 和 `_build_provider` 各自独立编写了相同的 15 行 Clash 基础配置（`mixed-port`, `dns`, `mode` 等）。

#### 9. 硬编码路径排除

| 字段 | 值 |
|------|-----|
| **文件** | `src/site_processor.py` |
| **行号** | 157 |
| **类型** | 可维护性 |

```python
if href in ("/free-nodes/", "/", "") or "category" in href or "page-" in href:
```

子串匹配 `"category"` 和 `"page-"` 误杀率高。站点结构调整为 `/article/page-123/` 时会排除所有文章。

#### 10. Provider 名称不匹配静默降级

| 字段 | 值 |
|------|-----|
| **文件** | `src/llm_router.py` |
| **行号** | 102-108 |
| **类型** | 可维护性 |

`task_routing` 配置中引用了不存在的 provider 名（如 `openrouterr` 三个 r），不会被验证或警告。该请求静默跳过，实际可用的供应商减少。

---

## 发现分布

```
严重 ████████████████████ 3
高   ████████████████████ 3
低   ████████████████████ 4
                    ─────
                    10
```

## 下一步

P2（Merger）刚完成，下一个实施阶段是 **P4 (GitHub Actions)** 或 **P6 (YouTube/密码站点)**。建议在实施前先修复 F1（all_links 覆盖）和 F2（LLM 错误静默），因为这两个直接影响数据产出和调试能力。
