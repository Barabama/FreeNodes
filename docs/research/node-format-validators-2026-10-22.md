# 代理节点格式校验与订阅合并：开源仓库调研

> 调研日期：2026-10-22  
> 目标：为 FreeNodeSpider 的 `nodes/*.txt`、`nodes/*.yaml`、`nodes/provider.yaml` 找出可参考或可复用的“格式合法性检查”和“subprovider / proxy-provider 合并”实现。  
> 方法：GitHub 检索 + 源码浅克隆 + 子代理独立审查。所有结论以**仓库 HEAD 源码**为准，不以 README 宣称代替实现。

## 0. 结论先行

1. **没有一个现成仓库同时满足**“TXT URI 字段校验 + Mihomo YAML 字段校验 + 多订阅合并 + proxy-provider 生成 + 真实连通性验证”。
2. 最接近 FreeNodeSpider 需求的是 **`corvofiox/openclash-sub-converter`**：它确实实现了多源聚合、URI/YAML 解析、节点级 `mihomo adapter.ParseProxy` 校验、名称去重、完整 Clash YAML 生成和 mihomo `UnmarshalRawConfig` 结构校验；但它输出的是完整配置，不是 file provider，且仓库没有 LICENSE。
3. 最适合借鉴“真实可用性验证”的是 **`LeilaoMi/AutoMergePublicNodes-Optimized`**（MIT）和 **`rekt0ro/ProxyRift`**（MIT）：两者都用 sing-box 做真实 HTTP 验证；前者是 Python，后者是 Rust。
4. 最适合借鉴“Mihomo provider 语义”的是 **Mihomo 内核自身**：`proxy-providers` 支持 `file` / `http` / `inline`，代理组通过 `use` 引用 provider，并校验重复 provider/组名。
5. 最适合借鉴“字段级 YAML schema”的是 **`cherrchen/mihimo-yaml`**（MIT）：用 Zod 对 Mihomo 配置做运行时校验，但其 `port` 等字段约束偏宽松，不能替代内核级校验。
6. **不要把这些仓库当成完整 validator**：`proxy-provider-converter`、`nodelistparser`、`Merge-sub`、`V2Hub2` 都存在明显能力缺口，详见下文。

## 1. 调研方法与证据等级

### 1.1 证据等级

| 等级 | 含义 |
| --- | --- |
| A：源码验证 | 已克隆仓库并核对实现、测试和 HEAD |
| B：README 宣称 | 只在文档中声明，未在源码中确认 |
| C：仅检索到 | 只确认仓库存在，未深入审查 |

本报告只把 A 级作为推荐依据。

### 1.2 仓库快照

源码快照位于本机临时目录（不进入项目仓库）：

```text
C:\Users\bar\AppData\Local\Temp\fns-research-20261022
```

> 注意：这些是浅克隆，后续可能变化；报告中的 HEAD 是本次审查时的快照。

## 1.3 审查快照与许可证

| 仓库 | HEAD | 最近提交 | 许可证 |
| --- | --- | --- | --- |
| `corvofiox/openclash-sub-converter` | `7cb155f` | 2026-08-16 | 无 LICENSE（仅 README 提到依赖 mihomo GPL-3.0） |
| `LeilaoMi/AutoMergePublicNodes-Optimized` | `d533bf9` | 2026-10-21 | MIT |
| `rekt0ro/ProxyRift` | `637f87d` | 2026-10-22 | MIT |
| `cherrchen/mihimo-yaml` | `9983ad9` | 2026-07-20 | MIT |
| `huihuibuswo/merge-clash` | `b5a1c7a` | 2026-08-21 | 无 LICENSE 文件 |
| `MetaCubeX/mihomo`（Meta 分支） | `3f27ef3` | 2026-10-21 | GPL-3.0 |
| `2dust/v2rayN` | `57f17d5` | 2026-10-20 | GPL-3.0 |
| `SagerNet/sing-box` | `dfb8034` | 2026-10-13 | GPL-3.0 |
| `tindy2013/subconverter` | `a0d4eab` | 2026-07-08 | GPL-3.0 |
| `Aethersailor/SubConverter-Extended` | `4cee89d` | 2026-10-20 | GPL-3.0 |
| `SukkaW/nodelistparser` | `17512d8` | 2026-10-12 | MIT |
| `qier222/proxy-provider-converter` | `62459f2` | 2025-11-04 | MIT |
| `eooce/Merge-sub` | `c66449f` | 2026-02-12 | 无 LICENSE 文件 |
| `juewuy/ShellCrash` | `de1d9e2` | 2026-08-27 | GPL-3.0 |
| `sub-store-org/Sub-Store` | `fdcf324` | 2026-10-22 | AGPL-3.0 |
| `daimon3332/easy-proxies` | `ea88a5d` | 2026-10-06 | MIT（GitHub API 显示 NOASSERTION） |
| `Rain-kl/PoolX` | `259b85d` | 2026-09-01 | MIT |
| `4n0nymou3/multi-proxy-config-fetcher` | `c5979b7` | 2026-10-22 | MIT |

## 2. 关键能力矩阵

| 仓库 | TXT/URI 解析 | Clash YAML 解析 | 字段级校验 | 多订阅合并 | proxy-provider | 真实连通性 | 许可证 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `corvofiox/openclash-sub-converter` | 是 | 是 | 是（mihomo `ParseProxy`） | 是 | 完整配置，非 file provider | 否 | 无 LICENSE | 最接近，但不能直接复用 |
| `LeilaoMi/AutoMergePublicNodes-Optimized` | 是 | 是 | 解析器级 | 是 | 否 | sing-box 真测 | MIT | 真实验证最佳参考 |
| `rekt0ro/ProxyRift` | 是 | 是 | 强（协议级） | 是 | 否（`proxies:` 输出） | sing-box 真测 | MIT | 强参考 |
| `cherrchen/mihimo-yaml` | 否 | 是 | Zod 字段级 | 否 | 是（schema） | 否 | MIT | schema 参考 |
| `huihuibuswo/merge-clash` | 是（有限） | 是 | 基础字段 + 组引用 | 是 | 是（两种模式） | mihomo 测试 | 无 LICENSE | 设计参考，谨慎复用 |
| `MetaCubeX/mihomo`（Meta 分支） | 否 | 是 | 内核级 | 否 | 是（file/http/inline） | 内核加载 | GPL-3.0 | 权威语义参考 |
| `2dust/v2rayN` | 是 | 部分 | 协议级 | 否 | 否 | 内核测试 | GPL-3.0 | URI 解析参考 |
| `SagerNet/sing-box` | 否 | JSON | 内核级 | 否 | 否 | 内核运行 | GPL-3.0 | sing-box 语义参考 |
| `tindy2013/subconverter` | 是 | 是 | 转换级 | 是 | 部分 | 否 | GPL-3.0 | 转换参考 |
| `Aethersailor/SubConverter-Extended` | 是 | 是 | 转换级 | 是 | 是 | 否 | GPL-3.0 | provider 生成参考 |
| `SukkaW/nodelistparser` | 部分 | 否（单节点） | 很弱 | 否 | 否 | 否 | MIT | 单节点 codec 参考 |
| `qier222/proxy-provider-converter` | 否 | 是 | 很弱 | 否 | 输出 `proxies:` | 否 | MIT | 最小 provider 示例 |
| `eooce/Merge-sub` | 是（仅 Base64） | 否 | 无 | 是（字符串拼接） | 否 | 否 | 无 LICENSE | 不建议作为核心 |
| `V2Hub2` | 是 | 否 | 很弱 | 是 | 否 | 否 | MIT | 旧式 PHP 参考 |
| `juewuy/ShellCrash` | 是 | 是 | 结构级 | 是 | 是 | 调用内核 `-t` | GPL-3.0 | 客户端消费行为参考 |

## 3. 重点仓库源码结论

### 3.1 `corvofiox/openclash-sub-converter`：最接近完整需求

**HEAD**：`7cb155f`（2026-08-16）  
**许可证**：仓库未发现 LICENSE 文件。

已确认实现：

- `internal/link/link.go` 的 `ParseSubscription` 自动识别 Base64、Clash YAML、纯文本 URI：
  - Base64 解码支持 URL-safe / 标准 / 有无 padding；
  - Clash YAML 只取 `proxies` 列表；
  - 单行解析失败时跳过并记录 warn，不中断整个订阅。
- 支持协议：`ss`、`ssr`、`vmess`、`vless`、`trojan`、`hysteria2`/`hy2`、`hysteria`、`tuic`、`anytls`、`socks5`/`socks`、`http`/`https`。
- `internal/api/api.go` 对每个节点调用 mihomo `adapter.ParseProxy`：
  - 缺必填字段、非法参数、未知 `type` 的节点会被跳过并记录日志；
  - 这是**字段级语义校验**，比单纯 YAML 解析强。
- `internal/output/output.go` 调用 mihomo `config.UnmarshalRawConfig` 做 YAML 结构校验，但注释明确说明它**不执行节点级语义校验**。
- `internal/transform/transform.go` 做 `exclude` → `include` → `rename`，并对重名节点追加 ` (N)` 后缀。
- `internal/fetcher` 支持多源聚合，任一源失败不影响其他源。

不足：

- 输出是完整 Clash 配置，不是 `proxy-providers` file provider；
- 没有真实代理连通性测试；
- 仓库没有 LICENSE，不能直接复制代码；
- 节点级校验依赖 mihomo 的 Go 包，而 mihomo 是 GPL-3.0，直接链接会带来许可证约束。

**对 FreeNodeSpider 的用法**：把它当作“校验流水线设计”的参考，而不是依赖或复制。

### 3.2 `LeilaoMi/AutoMergePublicNodes-Optimized`：真实验证最佳参考

**HEAD**：`d533bf9`（2026-10-21）  
**许可证**：MIT。

已确认实现：

- `core/parser.py` 按“Clash YAML → Base64 → 明文 URI”顺序识别；
- 支持 `vmess`、`vless`、`trojan`、`ss`、`ssr`、`hysteria`/`hysteria2`、`tuic`、`anytls`、`socks`、`http`；
- `core/parser.py` 的 `Node.fingerprint()` 用于全局去重：
  ```text
  type|server|port|credential
  ```
- `main.py` 汇总多个源后去重，生成 `all` / `verified` / `global`；
- `core/tester.py` 为每个节点生成 sing-box 临时配置，启动 `sing-box run`，通过本地 SOCKS 做真实 HTTP 验证；
- 生成 Clash YAML 和 sing-box JSON，但**没有 `proxy-providers` 输出**。

不足：

- 去重 key 不含 transport / TLS / SNI / WS path，可能误删不同节点；
- `quality_prefilter` 还会按 `(server, type)` 只保留一个，可能过度折叠；
- Clash 解析只读 `proxies`，不处理 `proxy-providers` / `proxy-groups`。

**对 FreeNodeSpider 的用法**：借鉴“解析 → 规范化 → 去重 → sing-box 真测”的流水线；不要照搬它的指纹和 `(server, type)` 折叠。

### 3.3 `rekt0ro/ProxyRift`：协议级校验最完整

**HEAD**：`637f87d`（2026-10-22）  
**许可证**：MIT。

已确认实现：

- `src/validator.rs` 有大量协议级兼容性检查和真实探测逻辑；
- `src/clash.rs` 从 URI 生成 Clash `proxies:`，对无法转换的节点会记录跳过原因；
- `src/singbox.rs` 生成 sing-box outbound / subscription；
- `src/parser/mod.rs` 支持 Clash YAML、Base64、HTML 中嵌入的链接；
- `config_dedup_key` 会把协议、endpoint、transport、TLS 等纳入去重 key；
- 验证包含 HTTP 握手、稳定性和吞吐测试。

不足：

- 没有 proxy-provider 输出；
- 代码体量大（validator 约 275 KB），直接移植成本高；
- 需要 sing-box 二进制做真实验证。

**对 FreeNodeSpider 的用法**：作为“强校验”和“去重 key 设计”的参考；不建议整仓移植。

### 3.4 `cherrchen/mihimo-yaml`：字段级 schema 参考

**HEAD**：`9983ad9`（2026-07-20）  
**许可证**：MIT。

已确认实现：

- `src/schema/validation.ts` 用 Zod 定义 Mihomo 配置；
- 覆盖 `proxies`、`proxy-groups`、`proxy-providers`、`rule-providers`、`rules`、DNS、TUN 等模块；
- `ProxyConfigSchema` 要求 `name`、`type` 为字符串，`server`、`port` 可选；
- `ProxyProviderConfigSchema` 包含 `type`、`url`、`path`、`health-check` 等字段；
- `ProxyGroupConfigSchema` 包含 `proxies`、`use`、`url`、`interval` 等字段；
- 有 138 个测试。

不足：

- `port` 是 `z.number().optional()`，没有范围约束；
- 不校验协议必填字段（例如 `trojan` 的 `password`）；
- 不调用 mihomo 内核；
- 不是 CLI 校验器，而是前端编辑器的一部分。

**对 FreeNodeSpider 的用法**：借鉴字段清单和 Zod schema 结构；不要把它当作最终合法性判断。

### 3.5 `huihuibuswo/merge-clash`：subprovider 合并设计参考

**HEAD**：`b5a1c7a`（2026-08-21）  
**许可证**：仓库未发现 LICENSE 文件。

已确认实现：

- `src-tauri/src/merge.rs` 支持两种模式：
  - `embedded-proxies`：把节点内联到 `proxies:`；
  - `proxy-providers`：生成 `proxy-providers` 配置。
- `render_yaml` 在 `proxy-providers` 模式下生成：
  ```yaml
  proxy-providers:
    <id>:
      type: http
      url: <subscription-url>
      path: ./providers/<id>.yaml
      interval: 86400
      health-check: ...
  ```
- 发现跨来源同名节点时：
  - `embedded-proxies`：跳过后续重复；
  - `proxy-providers`：报 blocker。
- `validate_groups` 检查重复组名、组引用、循环引用；
- `src-tauri/src/fetcher.rs` 解析 YAML，要求顶层是对象、`proxies` 是列表，并过滤没有 `name` 的节点；
- 支持用 mihomo 做连通性测试。

不足：

- 没有 LICENSE；
- `proxy-providers` 模式直接写入原始订阅 URL，存在凭证泄露风险；
- 去重主要按 `name`，不是按节点语义 key；
- 项目 star 很少，成熟度有限。

**对 FreeNodeSpider 的用法**：借鉴“两种合并模式 + provider/组引用校验”的设计；不要直接复制代码。

### 3.6 Mihomo 内核：provider 语义的权威来源

**HEAD**：`3f27ef3`（Meta 分支，2026-10-21）  
**许可证**：GPL-3.0。

已确认实现：

- `config/config.go` 定义：
  ```go
  ProxyProvider map[string]map[string]any `yaml:"proxy-providers"`
  Proxy         []map[string]any          `yaml:"proxies"`
  ProxyGroup    []map[string]any          `yaml:"proxy-groups"`
  ```
- `adapter/provider/parser.go` 的 `ParseProxyProvider` 支持：
  - `type: file`：`path`
  - `type: http`：`url`、`path`、`header`、`proxy`、`size-limit`
  - `type: inline`：`payload`
  - 通用字段：`interval`、`filter`、`exclude-filter`、`exclude-type`、`dialer-proxy`、`override`、`health-check`
- `config/config.go` 的 `parseProxies`：
  - 解析 `proxies` 时检测重复名称；
  - 解析 provider 时检测保留名；
  - 解析 proxy group 时检测重复名称和循环引用；
- `adapter/outboundgroup/parser.go` 中 `use` 和 `proxies` 至少有一个，否则报 `` `use` or `proxies` missing ``。

**重要纠正**：本次调研发现，GitHub 上 `MetaCubeX/mihomo` 的默认 `main` 分支当前是一个 Python 的《崩坏：星穹铁道》数据模型项目；真正的 Mihomo 内核位于同仓库的 `Meta` / `Alpha` 分支。不要按 `main` 分支审查内核代码。

**对 FreeNodeSpider 的用法**：用 `mihomo -t -f <config>` 做最终校验是最可信的；但它是 GPL-3.0，调用二进制不等于链接库，仍需确认分发方式。

### 3.7 `2dust/v2rayN`：URI 解析参考

**HEAD**：`57f17d5`（2026-10-20）  
**许可证**：GPL-3.0。

已确认实现：

- `ServiceLib/Handler/Fmt/` 下按协议拆分的 formatter，负责 URI 解析和生成；
- `ServiceLib/Handler/Builder/NodeValidator.cs` 对节点做字段级校验：
  - 地址非空；
  - 端口 1–65535；
  - VMess UUID；
  - VLESS 用户标识和 flow；
  - Shadowsocks cipher/password；
  - TLS/Reality 的 public-key 等。
- 支持 VMess、VLESS、Trojan、Shadowsocks、Hysteria2、AnyTLS、TUIC 等。

不足：

- C# 代码，难以直接复用到 Python；
- 没有 provider 合并；
- 其校验规则面向 v2rayN 自己的核心组合，不等于 Mihomo 规则。

**对 FreeNodeSpider 的用法**：作为 URI 字段规则和边界条件的参考。

### 3.8 `SagerNet/sing-box`：sing-box 语义参考

**HEAD**：`dfb8034`（2026-10-13）  
**许可证**：GPL-3.0。

已确认实现：

- `option/vless.go`、`option/vmess.go`、`option/trojan.go`、`option/hysteria2.go`、`option/anytls.go` 定义出站字段；
- `option/options.go` 的 `checkOptions` / `checkOutbounds` 做配置检查；
- `protocol/*/outbound.go` 实现各协议。

**对 FreeNodeSpider 的用法**：如果未来生成 sing-box JSON，应以这些结构为准；不要用 Mihomo 字段直接拼 sing-box 配置。

### 3.9 `tindy2013/subconverter` / `SubConverter-Extended`

**HEAD**：`a0d4eab`（2026-07-08）/ `4cee89d`（2026-10-20）  
**许可证**：GPL-3.0。

已确认：

- `subconverter` 是成熟的订阅转换器，支持多种输入/输出格式；
- `SubConverter-Extended` 明确增强 Mihomo Provider，支持 `proxy-providers`、`proxy_direct`、`provider_headers` 等；
- `SubConverter-Extended` 使用 Mihomo 解析桥，属于 GPL-3.0 衍生。

**对 FreeNodeSpider 的用法**：如果要做“多客户端输出”，可参考其转换模型；但直接集成会引入 GPL-3.0 约束，且它本身不是校验器。

### 3.9b `V2RayDAR` / `ProxyRift` / `PoolX`：真实探测与去重 key

这三者都偏向“节点可用性”而不是“订阅格式”，但它们的去重和探测实现值得参考。

**`V2RayDAR`**（HEAD `bb645ca`，2026-10-21，AGPL-3.0；AGPL 代码不可直接并入当前项目，除非项目整体采用兼容许可证）：

- `src/parser/mod.rs` 的 `parse_subscription_document` 依次尝试文本、Base64、Clash YAML；
- `src/clash.rs` 的 `try_parse_clash_subscription` 只读 `proxies`，并把节点转成 URI；
- `src/probe.rs` 通过 sing-box 生成临时配置，启动本地 SOCKS/HTTP 入站做主动探测；
- 去重使用 `dedup_key`，包含协议、endpoint 和传输参数。

**`ProxyRift`**（HEAD `637f87d`，2026-10-22，MIT）：

- `src/validator.rs` 的 `config_dedup_key` 对 VMess、Shadowsocks、标准 URI 分别提取去重字段；
- `src/clash.rs` 输出 `proxies:`，对无法转换的节点记录跳过原因；
- `src/singbox.rs` 输出 sing-box outbound；
- 支持 HTTP 握手、稳定性和吞吐验证。

**`PoolX`**（HEAD `259b85d`，2026-09-01，MIT）：

- `backend/internal/infra/clash/proxy/parser.go` 解析 `proxies`，要求 `name`、`type`、`server`、`port`；
- 指纹字段包含 `type`、`server`、`port`、`cipher`、`network`、`password`、`plugin`、`plugin-opts`、`servername`、`sni`、`tls`、`udp`、`uuid`、`username`；
- `mihomo_node_tester.go` 启动 mihomo，通过本地代理端口做 HTTP 延迟测试；
- 解析失败会记录 `ParseIssue`，不会静默丢弃。

不足：三者都不是 provider 文件生成器；PoolX 的 `port` 只检查 `>0`，没有检查上限 65535。

### 3.10 `SukkaW/nodelistparser` / `proxy-provider-converter` / `Merge-sub`

这三个仓库经常被误认为“provider 合并器”，实际能力有限：

- `nodelistparser`：
  - 只处理单个 proxy object，不解析 YAML 订阅；
  - `clash.decode` 只支持 `http`、`ss`、`socks5`、`trojan`、`vmess`、`anytls`；
  - 不生成 `proxy-providers`。
- `proxy-provider-converter`：
  - API 只接受一个 URL，源码没有多订阅合并；
  - Clash→Clash 只检查 `proxies !== undefined`，然后原样输出；
  - 不做去重、重名、端口/协议字段校验；
  - UI 里的 `proxy-providers` 只是静态模板。
- `Merge-sub`：
  - 假设每个订阅都是 Base64，直接 `Buffer.from(content, 'base64')`；
  - 合并只是字符串拼接；
  - 不做节点级去重；
  - 仓库没有 LICENSE 文件（仅 package.json 声明 MIT）。

## 4. 对 FreeNodeSpider 的建议

### 4.1 不建议直接引入的依赖

| 方案 | 原因 |
| --- | --- |
| 直接链接 mihomo Go 包做校验 | GPL-3.0，且会显著增加构建复杂度 |
| 直接复制 `openclash-sub-converter` | 无 LICENSE |
| 直接复制 `merge-clash` | 无 LICENSE |
| 直接复用 `Merge-sub` 合并逻辑 | 只做字符串拼接，且许可证不明确 |
| 把 `mihimo-yaml` 的 Zod schema 当最终校验 | 字段约束偏宽松，不覆盖协议必填字段 |

### 4.2 推荐的校验分层

```text
第 1 层：结构校验（当前已实现）
  - TXT：Base64 / URI / 协议前缀 / JSON 污染
  - YAML：PyYAML 解析 / 多文档 / proxies 列表 / provider 结构

第 2 层：字段校验（建议增强）
  - name/type/server/port 必填
  - port 1–65535
  - 按协议校验 uuid/password/cipher/transport/TLS
  - 节点名唯一性

第 3 层：语义校验（建议新增）
  - 生成最小 Mihomo 配置
  - 调用 mihomo -t -f config.yaml
  - 检查 proxy-provider 的 path/url、proxy-groups 的 use 引用

第 4 层：连通性校验（可选，与格式校验分离）
  - 用 sing-box 逐节点真实 HTTP 验证
  - 不把“节点过期”计入格式 CI 失败
```

### 4.3 对当前项目的具体改动建议

1. 在 `src/node_validator.py` 中增加：
   - `name` 唯一性检查；
   - `proxy-groups[].use` 引用的 provider 是否存在；
   - `proxy-providers` 的 `type` 只能是 `file` / `http` / `inline`；
   - `file` provider 必须有 `path`，`http` provider 必须有 `url`。
2. 新增一个可选的 `scripts/check_mihomo_config.sh`（或 PowerShell 版本）：
   ```bash
   mihomo -t -f nodes/provider.yaml
   ```
   该步骤只作为本地/CI 的语义校验，不进入 Python 单元测试。
3. 保持 `nodes/*.yaml` 为单文档 `proxies:`，`provider.yaml` 作为完整配置单独生成。
4. 如果要支持“多个 provider 文件”，建议输出：
   ```text
   nodes/providers/<site>.yaml   # 每个站点一个文件
   nodes/provider.yaml           # 引用这些文件
   ```
   但当前项目的 `provider.yaml` 已经按站点引用 `nodes/<site>.yaml`，可继续沿用。

## 5. 许可证与复用风险

| 仓库 | 许可证 | 能否直接复制代码 |
| --- | --- | --- |
| `openclash-sub-converter` | 无 | 否，需作者授权 |
| `merge-clash` | 无 | 否，需作者授权 |
| `Merge-sub` | 无 LICENSE 文件 | 否，需确认授权 |
| `XraySubRefiner` | 无 | 否，需作者授权 |
| `mihimo-yaml` | MIT | 可以，保留版权声明 |
| `AutoMergePublicNodes-Optimized` | MIT | 可以，保留版权声明 |
| `ProxyRift` | MIT | 可以，保留版权声明 |
| `V2RayDAR` | AGPL-3.0 | 链接/衍生需遵守 AGPL |
| `PoolX` | MIT | 可以，保留版权声明 |
| `easy-proxies` | MIT（仓库 LICENSE 文件；GitHub API 显示 NOASSERTION） | 可以，保留版权声明 |
| `nodelistparser` | MIT | 可以，保留版权声明 |
| `proxy-provider-converter` | MIT | 可以，保留版权声明 |
| `mihomo` 内核 | GPL-3.0 | 链接/衍生需遵守 GPL |
| `sing-box` | GPL-3.0 | 链接/衍生需遵守 GPL |
| `v2rayN` | GPL-3.0 | 链接/衍生需遵守 GPL |
| `subconverter` / `SubConverter-Extended` | GPL-3.0 | 衍生需遵守 GPL |
| `ShellCrash` | GPL-3.0 | 衍生需遵守 GPL |

## 6. 最终建议

对 FreeNodeSpider 来说，最务实的路线是：

1. **保留当前自研的 Python 校验器**，继续覆盖 TXT/YAML 的结构和字段检查；
2. **借鉴 `openclash-sub-converter` 的校验流水线**，但不要复制其代码；
3. **借鉴 `mihimo-yaml` 的字段清单**，补全 provider/group 引用校验；
4. **借鉴 `AutoMergePublicNodes-Optimized` / `ProxyRift` 的 sing-box 真测**，作为可选的连通性检查；
5. **最终语义校验用 `mihomo -t -f`**，但把二进制调用放在 CI/本地脚本中，不放进单元测试；
6. **不要把“格式合法”与“节点可用”混为一谈**：前者可以阻断提交，后者只应生成报告。

## 7. 附：本次审查的仓库清单

已克隆并审查：

- `corvofiox/openclash-sub-converter`
- `LeilaoMi/AutoMergePublicNodes-Optimized`
- `rekt0ro/ProxyRift`
- `cherrchen/mihimo-yaml`
- `huihuibuswo/merge-clash`
- `MetaCubeX/mihomo`（Meta 分支）
- `2dust/v2rayN`
- `SagerNet/sing-box`
- `tindy2013/subconverter`
- `Aethersailor/SubConverter-Extended`
- `SukkaW/nodelistparser`
- `qier222/proxy-provider-converter`
- `eooce/Merge-sub`
- `juewuy/ShellCrash`
- `sub-store-org/Sub-Store`
- `XraySubRefiner`
- `V2Hub2`
- `easy-proxies`
- `PoolX`
- `multi-proxy-config-fetcher`
- `subs-server`
- `cvt`
- `meow-rs`

## 8. 实测验证记录（2026-10-23）

以下结论来自真实客户端二进制，而不是静态检查：

| 客户端 | 版本 | 结论 |
| --- | --- | --- |
| Mihomo | v1.19.33 | `merged.yaml`、`provider.yaml`、10 个站点 YAML 全部加载成功 |
| Xray | v26.3.27 | 12,960 个节点生成的 outbound 配置 `Configuration OK` |
| V2Ray | v5.53.0 | 基线配置 `Configuration OK` |

### 8.1 重要教训：`mihomo -t` 不读取 provider 文件

把一个故意损坏的 `nodes/bad.yaml` 放进 provider 目录，`mihomo -t -f provider.yaml`
依然输出 `test is successful`。检查 Mihomo 源码（`config/config.go` 的
`parseProxies` → `provider.ParseProxyProvider`）可见 `-t` 只构建 provider
对象，不会立即读取 `file`/`http` 文件内容，因此：

> 校验 provider 产物时，必须逐个校验它引用的源文件，并且最好真实启动内核确认。

### 8.2 真实存在的产物缺陷

用上述方法发现并修复了以下问题：

| 缺陷 | 影响 | 修复 |
| --- | --- | --- |
| `_dedup_proxies` 重名计数器缺陷 | `merged.yaml` 出现 19 个重名节点，Mihomo 直接拒绝加载 | 改为循环查找未占用的后缀 |
| Reality `short-id` 未加引号 | `062898e8` 被 YAML 读成非字符串，Mihomo 报 `invalid REALITY short ID` | 自定义 SafeDumper 强制加引号 |
| 非法 Reality `public-key`（值为 `enabled`） | Mihomo 报 `invalid REALITY public key` | 新增 32 字节 base64url 校验并丢弃 |
| 上游把参数写在字面 `#` 之后 | 71 条 VLESS 丢失 `pbk`/`sid` | 新增 `_repair_trapped_fragment_params` |
| 上游使用 `&amp;` HTML 实体 | 34 条 VLESS 只解析出第一个查询参数 | 新增 `_fix_html_entities` |
| `client-fingerprint: unsafe` | 仅 sing-box 支持，Mihomo 忽略并告警 | 规范化时移除非 Mihomo 指纹 |
| 站点 YAML 自身重名 | 9/10 个站点文件无法被 Mihomo 加载 | 规范化时统一名称唯一化 |

### 8.3 客户端能力差异（不是格式错误）

`merged.txt` 中下列节点在 Xray 中不可用，但在 Mihomo 中可用：

- 协议：Hysteria2、AnyTLS、TUIC、SOCKS、Hysteria v1
- 旧加密：`aes-*-cfb`、`rc4-md5`、`chacha20-ietf`
- 少量 `2022-blake3-*` 密钥长度不符合 Xray 要求

这些属于目标客户端能力差异，不应作为“格式非法”处理。
