# 2026-11-20 — CI 日志暴露的 LLM 健康追踪与陈旧节点问题

> 分支：`fix/llm-empty-response`
> 依据：GitHub Actions run #149–#152（2026-11-16 → 11-19）的完整日志

## 问题 1：空响应被当成提供商故障，最终禁用唯一可用渠道

### 现象

- 四次运行中 OpenRouter 返回 67 次 HTTP 200，却没有一条 `LLM call failed [openrouter/...]`
- 同时出现 52 次 `ALL LLM providers failed`，其中 47 次的 `Providers tried` 包含 openrouter
- 每次运行还有 0–3 次 `Providers tried: none`，之后该次运行再无 openrouter 请求

### 根因

`src/llm_router.py` 的 `_response_text(resp, is_reasoning)` 只在 `is_reasoning_model: true`
时读取 `msg.reasoning`。`openrouter/free` 与 `kilo-auto/free` 在配置里是 `false`，
而它们实际会返回 `content=""` + `reasoning="..."`。于是：

1. `_try_provider` 静默返回 `None`
2. `ask()` 调用 `record_failure(provider)`
3. 连续 5 次后 `HealthTracker` 禁用该提供商 30 分钟
4. 所有提供商都不可用时，后续 `ask()` 直接返回空

实测（2026-11-20，用本地 `.env`）：

| 渠道 | 结果 |
| --- | --- |
| openrouter/free | HTTP 200，`content_len=28`，`reasoning_len=357` |
| kilo-auto/free | HTTP 200，`content_len=28`，`reasoning_len=289` |
| opencode | 密钥有效，但 `429 FreeUsageLimitError`（免费额度用尽） |

### 修复

- `_response_text` 不再接收 `is_reasoning`，`content` 为空时始终回退到 `reasoning`
- 空响应记录 `WARNING`，不再静默
- `_try_provider` 返回 `(text, provider_failed)`；只有"所有模型都抛异常"才算提供商故障，
  空响应不计入健康追踪
- `generate_pattern` 的 `max_tokens` 从 256 提到 1024（reasoning 会先消耗预算）

## 问题 2：`yt-dlp` 未声明，两个 cloud_drive 站点每次都崩

- `pyproject.toml` 未声明 `yt-dlp`，workflow 也未安装
- `src/youtube.py` 只捕获 `TimeoutError`，`FileNotFoundError` 直接冒泡
- 结果：`fxrj`、`zyfxs` 四次运行全部 0 产出

修复：加入 `yt-dlp` 依赖；三处 `create_subprocess_exec` 增加 `FileNotFoundError` 处理。

## 问题 3：长期失败的站点持续贡献陈旧节点

- `nodes/fxrj.yaml` 最后成功抓取是 2026-07-23，仍被合入 `merged.yaml`
- 实测 2,504 条 merged proxies 中有 1,564 条（62%）来自该文件
- `nodes/fxrj.txt` 是 2026-07-23 提交的 3 行二进制垃圾，每天让 `validate-nodes` 失败

修复：

- 新增 `merge.max_node_age_days`（默认 14），按 `config.yaml` 的 `up_date`
  跳过过期站点的 txt/yaml，provider.yaml 同步排除
- 用 `up_date` 而不是文件 mtime：CI 一次性 checkout，mtime 无意义
- 删除 `nodes/fxrj.txt`

## 问题 4：Cerebras 已不可用

Cerebras 免费模型现在要求绑卡，且原配置里的 `gemma-4-31b` 已归档（404）。
已从 `config.yaml` 的 providers 与 `task_routing` 中移除；workflow 的
`CEREBRAS_API_KEY` 也一并删除。

同时补上了 workflow 缺失的 `KILOCODE_API_KEY` —— 之前 CI 从未收到该变量，
每次运行都报 `No API key for kilocode`。

## 验证

- `pytest tests/`：327 passed
- 真实数据副本试跑：`fxrj` 被跳过，`merged.yaml` 2,504 → 2,010 条，
  `merged.txt` 2,083 行
- 本地端到端 `LLMRouter.ask()`：3/3 返回文本，openrouter / kilocode 健康计数为 0

## 未处理（需要人工）

- 更新 GitHub Secrets：`OPENCODE_API_KEY`（新密钥有效但免费额度已用尽）、
  `KILOCODE_API_KEY`（workflow 已引用，需确认 Secret 存在）
- opencode 免费额度恢复后可重新参与路由
