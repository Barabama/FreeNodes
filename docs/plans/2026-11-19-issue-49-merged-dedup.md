# Issue #49 — merged 产物去重与测速筛选

> 关联 issue：`merged建议去重。 #49`
> 分支：`fix/49-merged-dedup`
> 日期：2026-11-19

## 问题

`merged` 订阅条目数量多，但可用节点是少数。原 issue 提出两点：

1. 去重
2. 测速，删除无效节点后再转成 YAML 上传

## 现状分析（基线 `df2333b6` 上的实测）

| 产物 | 改动前 | 问题 |
| --- | --- | --- |
| `merged.txt` | 5,779 行 | 只做**整行** MD5 去重。同一节点仅显示名（`#备注`）不同就被当成两个节点 |
| `merged.yaml` | 4,368 条 | `_dedup_proxies` 用 `server:port:type` 去重，**会误合并**：凭据或传输参数不同、端口相同的两个节点被当成一个 |
| `provider.yaml` | 仅引用 | 不做节点级筛选 |
| 测速 | **不存在** | `node_validator` 只做格式校验，`scripts/validate_with_clients.py` 只做客户端加载检查，都不能证明节点可用 |

## 方案

### 1. 连接配置指纹去重（`src/node_fingerprint.py`）

- `txt_fingerprint(line)`：解析 URI，vmess 展开 base64/inline JSON（忽略 `ps`），
  只剥掉 `#备注` 片段，其余查询参数逐字保留。
- `proxy_fingerprint(proxy)`：把所有连接字段（凭据、`network`、`ws-opts`/`grpc-opts`、
  `servername`、`reality-opts`、`plugin-opts` …）按 `key=value` 排序拼接，只排除
  `DISPLAY_FIELDS`（`name`/`ps`/`remarks`/`remark`）。
- `canonical_value` 统一 `443` 与 `"443"`、忽略映射键顺序，避免伪差异。

结果：同一节点被多个站点改名重发时合并；凭据/传输/SNI/插件不同的节点全部保留。

### 2. 测速后端（`src/node_probe.py`），二选一、默认 TCP

配置 `probe.backend`：

| 后端 | 做法 | 代价 | 能证明什么 |
| --- | --- | --- | --- |
| `tcp`（默认，Action 也用它） | 对 `host:port` 做 TCP 握手并计时 | 无外部依赖，秒级 | 端口在时限内可连。**不验证认证、TLS/Reality、实际转发** |
| `mihomo` | 起本地 Mihomo，用 RESTful `/proxies/{name}/delay` 真实请求 | 需 Mihomo 二进制，慢 | 更接近真实客户端 |

两者解耦：`probe(items, settings)` 一个入口分派，`ProbeReport` 是唯一契约。

关键安全约束：

- **UDP-only 协议（hysteria/hysteria2/tuic/wireguard…）不参与 TCP 判定**，一律记为
  `unprobed` 并保留——TCP 连不上不能证明 UDP 节点是死的。
- 未知协议同理保留，不做猜测性删除。
- 后端整体不可用（二进制缺失、API 未就绪）返回 `unavailable`，调用方**保留全部节点**。
- 筛选后若某一产物会变空，回退为不筛选并打印告警，避免发布空订阅。

默认参数：`max_delay_ms=3000`、`timeout_ms=5000`、`concurrency=32`。

### 3. 接入点

- `Merger.run()` / `run_async()`：`run()` 给 CLI/测试用（内部 `asyncio.run`），
  `run_async()` 给已运行事件循环用（`Scheduler`）——否则会触发
  `asyncio.run() cannot be called from a running event loop`。
- `Scheduler` 从 `config.probe` 构造 `ProbeSettings`；`probe.enabled=false` 时完全不探测。
- `provider.yaml` 仍引用各站点原始文件，**不宣称**它经过筛选（按需求明确不切换）。
- 探测不可用（后端缺失/API 未就绪）时**保留上一份产物**，不覆盖；写入使用
  临时文件 + `os.replace` 原子替换。
- 探测前先解析并校验目标地址：非公网（回环/私网/链路本地/保留地址）一律视为
  「不可探测」并保留节点，TCP 与 mihomo 两个后端都执行此检查。
- README 由 `readme_updater` 生成，写明去重/筛选口径与 TCP 测速的局限；
  写进生成器才不会在下次抓取时被覆盖。

### 4. Workflow

`.github/workflows/crawl.yml` **无需改动**：默认 TCP 后端不依赖任何外部二进制。
如需 mihomo 后端，在本地或 CI 自行提供二进制路径（`probe.mihomo_binary`）。

## 验证

- 单元测试 312 个全部通过（`pytest tests/`）。
- 新增 `tests/test_node_fingerprint.py`、`tests/test_node_probe.py`、
  `tests/test_clash_uri.py`、`tests/test_probe_integration.py`。
- 探测相关测试只用**本地** TCP 监听器与伪造的 HTTP 客户端，不接触任何公开节点；
  测试里显式关闭 `require_public_targets` 才能用 `127.0.0.1`。
- 真实数据试跑（临时目录副本）：`merged.txt` 5,779 → 3,188 行（−44.8%）。
  `merged.yaml` 重建为 4,368 条：旧规则以 `server:port:type` 为键时，同一快照上
  有 1,647 组同名键，合计 5,993 条会被删掉，而这些条目的凭据或传输参数并不相同。

## 已知限制

- TCP 测速不等于可用性：能连上端口但认证失败/额度耗尽的节点仍会保留。
- 需要真实可用性时把 `probe.backend` 改为 `mihomo`，代价是运行时间显著增加。
- 订阅者会看到 `merged.txt` 数量下降，属预期行为；`merged.yaml` 反而可能变多，
  因为旧规则误合并的节点被还原。
- 探测拒绝非公网目标（回环/私网/链路本地 → 视为不可探测并保留），
  这样第三方订阅无法把 runner 引向内网。
