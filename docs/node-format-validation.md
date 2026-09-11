# 节点订阅格式与校验说明

> 审计日期：2026-09-11
> 目标：让 `nodes/*.txt`、`nodes/*.yaml` 和 `nodes/provider.yaml` 在生成后具备可检查、可归因、可被常见客户端导入的结构。
> 说明：格式校验只能判断“结构/字段/编码是否合理”，不能证明节点可连接、速度正常或服务端仍在线。

## 1. 项目当前结果审计

在执行 `git pull --ff-only` 后，仓库快进到 `ffb11a6f`（2026-09-10 的 CI 抓取结果）。当前历史产物的主要问题：

| 文件/类别 | 现象 | 原因 | 处理策略 |
| --- | --- | --- | --- |
| `cfmem.txt` | 节点 URI 后混入 sing-box JSON 配置片段 | 下载内容分类只按“是否像 YAML”判断，JSON 被当作 TXT | 保存/合并时只保留有效协议 URI，并报告嵌入配置 |
| 多个站点 YAML | 文件包含多个 `---` 文档 | 代码以 `"\n---\n".join(...)` 拼接下载结果 | 新保存的 YAML 折叠为单个 `proxies` 文档 |
| `yudou.yaml` | 存在 `socks5` 的 `port: 0`、`server: @...` | 抓取源本身带有损坏节点 | 校验报错；合并时跳过基本字段不合法的条目 |
| 部分 TXT | 同时含 base64 订阅行、明文 URI、注释或异常行 | 不同站点的订阅格式不一致 | 支持 base64、VMess inline JSON、SIP002 SS、常见 URI；异常行单独报告 |
| `provider.yaml` | provider 结构可解析，但依赖源文件本身是合法单一 YAML | provider 只负责引用，不会修复源文件 | 新输出源文件统一成 `proxies:` 单文档 |

## 2. TXT 订阅格式

### 2.1 支持的 URI

目前校验器覆盖：

- `vmess://`：标准 base64 JSON，以及部分站点产生的 inline JSON；至少需要 `add`、`id`、`port`。
- `vless://`：需要用户标识、服务器、端口；常见参数包括 `encryption=none`、`security=tls/reality`、`type=ws/grpc/tcp/xhttp`、`sni`、`host`、`path`、`serviceName`、`flow`、`pbk`、`sid`。
- `trojan://`：需要密码、服务器、端口；通常配合 TLS，常见参数为 `security=tls`、`sni`、`type`、`path`、`host`。
- `ss://`：支持完整 SIP002 base64 形式，以及 `method:password@host:port` 形式；`?` 后的空查询也会被正确处理。
- `ssr://`、`socks://`、`socks5://`、`http://`、`https://`、`tuic://`、`hysteria://`、`hysteria2://`/`hy2://`、`anytls://` 等常见格式。

注：URI 结构正确不代表参数组合一定被每个客户端支持。例如同一个 VLESS 节点可以在 Xray 中使用 `xhttp`，但某些 sing-box 版本/构建可能限制特定传输层；这属于“引擎兼容性”而不是 URI 语法错误。

### 2.2 base64 与明文

标准订阅经常是“整文件 base64”，解码后每行是 `vmess://`、`vless://` 等 URI。校验器只在解码结果确实含协议 URI 时解码，避免把普通 JSON、YAML 或随机文本误当 base64。

TXT 输出阶段会：

1. 去除空行、注释和 BOM；
2. 解码整文件 base64；
3. 解析 VMess base64/inline JSON；
4. 保留有效 URI、按整行去重；
5. 丢弃 JSON/YAML 配置片段和无法识别的行。

## 3. Mihomo / Clash YAML

### 3.1 节点文件的最小结构

面向节点订阅/provider 的最小可移植文件建议是：

```yaml
proxies:
  - name: example-vless
    type: vless
    server: example.com
    port: 443
    uuid: 418048af-a293-4b99-9b0c-98ca3580dd24
    tls: true
```

每个代理至少应有：

- `name`
- `type`
- `server`
- `port`（1–65535）

协议相关字段还包括：

| `type` | 常见必要字段 |
| --- | --- |
| `vmess` | `uuid`（通常为 UUID）、`alterId`/`cipher` 可选或由客户端默认 |
| `vless` | `uuid`/用户标识；TLS、Reality、network/transport 按实际节点配置 |
| `trojan` | `password` |
| `ss` | `cipher`、`password` |
| `ssr` | `cipher`、`password`、`protocol`、`obfs` |
| `hysteria2`/`hy2` | `password`，常见 `sni`、`skip-cert-verify` |
| `anytls` | `password`，具体字段取决于 Mihomo 版本 |
| `tuic` | `uuid`、`password` |

### 3.2 单文档原则

YAML 语法允许多个 `---` 文档，但客户端配置/文件 provider 的兼容性不应依赖多文档行为。项目现在会把下载到的多个 Clash 配置提取为一个单文档：

```yaml
proxies:
  - ...
  - ...
```

这会有意丢弃源站的 `proxy-groups`、`rules`、端口监听和 DNS 设置，因为站点输出的职责是“节点 provider”，而不是把多个完整客户端配置拼成一个配置。

## 4. provider.yaml

`provider.yaml` 是完整 Mihomo 配置，核心结构是：

```yaml
proxy-providers:
  site:
    type: file
    path: ./nodes/site.yaml
    health-check:
      enable: true
      url: http://www.gstatic.com/generate_204
      interval: 300
```

随后由 `proxy-groups[].use` 引用 provider 名称。provider 源文件应是单一 YAML 文档，优先使用 `proxies:` 列表；不要把完整 sing-box JSON、多个 YAML 文档、普通 URI 和 `proxies:` 配置混在同一个源文件中。

`path` 必须根据 Mihomo 实际启动目录/`HomeDir` 解析。当前项目延续“从仓库根目录启动 Mihomo”的路径约定：`provider.yaml` 位于 `nodes/`，provider 源文件位于 `nodes/`，配置中使用 `./nodes/<site>.yaml`。如果把 `provider.yaml` 复制到其他目录，需要同步调整路径。

## 5. Xray、sing-box 与订阅格式的边界

### Xray

Xray 原生配置是 JSON，核心模型是 `outbounds[]`、`protocol`、`settings`、`streamSettings`。VMess/VLESS/Trojan 都需要服务器地址、端口和各自的认证字段；VLESS/Trojan 的传输安全、传输层和 Reality/XTLS 参数不能只靠“有 URL”判断。

### sing-box

sing-box 原生配置也是 JSON，核心模型是 `outbounds[]`。`type` 直接区分 `vmess`、`vless`、`trojan`、`hysteria2`、`anytls` 等；例如 AnyTLS 出站要求 `server`、`server_port`、`password` 和 TLS，Hysteria2 出站要求 `server`/`server_port`、`password` 和 TLS。sing-box JSON 不能直接写入 Clash `proxies:` 文件，也不能当作 TXT URI 订阅。

### ShellCrash / v2rayN

ShellCrash 主要消费 Clash/Mihomo、V2Ray/Xray、sing-box 等不同核心的配置或订阅；v2rayN 的导入逻辑会先识别 URI、base64 订阅或 Clash YAML，再转换为内部 Profile。因而本项目应保持“一个输出文件一种语法”，不要依赖客户端自动猜测混合内容。

## 6. 使用方式

```powershell
# 检查所有当前节点产物
python -m src.node_validator nodes

# 严格模式：YAML 多文档 warning 也视为失败
python -m src.node_validator nodes --strict

# 检查单个文件
python -m src.node_validator nodes\clashnode.yaml
```

退出码：

- `0`：没有 error；普通模式允许 warning；
- `1`：存在 error，或严格模式存在 warning。

## 7. 后续建议

1. 在 GitHub Actions 的 `git add` 前运行普通校验，阻止明显的 HTML/JSON/错误响应进入提交。
2. 待历史文件全部由新逻辑生成一次后，再把 `--strict` 作为 CI 门禁。
3. 进一步增加“引擎兼容性”层：分别针对 Mihomo、Xray、sing-box 检查 transport/security 的组合，而不是把所有协议字段混成一个通用 schema。
4. 增加可选连通性测试，但必须和格式检查分离，避免节点过期导致格式 CI 失败。

## 8. 参考实现与文档

- Mihomo proxy-providers 文档：<https://wiki.metacubex.one/en/config/proxy-providers/>
- Mihomo 配置示例：<https://github.com/MetaCubeX/mihomo/wiki/Configuring-example>
- Xray VLESS/VMess/Trojan 文档：<https://xtls.github.io/en/config/outbounds/vless.html>
- Xray transport 兼容性：<https://xtls.github.io/en/config/transport.html>
- sing-box outbound 总表：<https://sing-box.sagernet.org/configuration/outbound/>
- sing-box AnyTLS：<https://sing-box.sagernet.org/configuration/outbound/anytls/>
- sing-box Hysteria2：<https://sing-box.sagernet.org/configuration/outbound/hysteria2/>
- v2rayN：<https://github.com/2dust/v2rayN>
- ShellCrash：<https://github.com/juewuy/ShellCrash>
