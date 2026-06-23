# Code Review Report — P6 YouTube/Password Site Modules

> **审查日期:** 2026-06-22
> **审查阶段:** P6 完成（youtube.py / drive.py / decryptor.py / paste.py + site_processor 集成）
> **审查范围:** `src/youtube.py` `src/drive.py` `src/decryptor.py` `src/paste.py` + `src/site_processor.py` 集成部分

---

## 一、功能覆盖情况

| 模块 | 测试数 | 功能 | E2E 验证 |
|------|--------|------|---------|
| `youtube.py` | 26 | yt-dlp 封装、密码提取、链接提取、日期解析 | ✅ FXRJ 频道 + ZYFXS 视频 |
| `drive.py` | 15 | Drive ID 提取、zip 下载、文件解压 | ✅ FXRJ Drive 链接 |
| `decryptor.py` | 21 | 密码检测、表单提交、暴力破解 | ✅ Yudou 页面 6767 解密 |
| `paste.py` | 12 | paste.to URL 提取、客户端加密解密 | ✅ ZYFXS paste.to 1122 解密 |
| `site_processor.py` | 174（总量） | 三种站点类型分发集成 | ⚠️ 单元测试覆盖不足（见下方） |

---

## 二、发现项

### 🔴 严重

#### P6-1. `_run_cloud_drive` 将 zip 内容去重后丢失

| 文件 | 行 | 问题 |
|------|-----|------|
| `site_processor.py` | 116-122 | `all_txt.add(body)` 和 `all_yaml.add(body)` 将整个文件内容加入 `set`，但 `_save_and_finish` 用 `"\n".join(txt_contents)` 拼接。如果同一个 Drive 文件被多个视频引用（如 FXRJ 的不同日期视频用了同一个 zip），内容会被去重到只剩一份。这不是问题；真正的问题是：如果 zip 内有多个 `.txt` 文件（如 `0-20260622.txt` `1-20260622.txt`），它们的内容会被**合并后**加入 set，导致**所有文件变成一个字符串**，而非分别保存。 |

**影响：** FXRJ 等站点的多个订阅文件被错误合并为一个，破坏了多文件订阅的设计。

#### P6-2. `_try_youtube_password_flow` 无异步 `get_video_metadata` 调用但实际不是 async

| 文件 | 行 | 问题 |
|------|-----|------|
| `site_processor.py` | 228 | `from src.youtube import get_video_metadata` 导入的是 `async def`，但 `get_video_metadata` 内部用的是 `subprocess.run`（同步阻塞）。在 `asyncio` 事件循环中调用同步 subprocess 会阻塞整个事件循环。 |

**影响：** 一个站点获取 YouTube 元数据时，所有其他并发站点被阻塞 5-20 秒。

#### P6-3. `brute_force_4digit` 没有被 `_try_youtube_password_flow` 正确调用

| 文件 | 行 | 问题 |
|------|-----|------|
| `site_processor.py` | 250-251 | `generate_password_candidates("AABB")[:50]` 生成密码列表后，代码用 `try_decrypt` 逐个尝试，但 `try_decrypt` 会为**每个密码**创建一个新的 `AsyncWebCrawler`（启动 Chromium），100 次暴力破解 = 100 次 Chromium 启动，极慢。 |

**影响：** Yudou 类站点如果 YouTube 字幕为空，暴力破解会非常慢（100 × ~10s = 16分钟）。

---

### 🟡 高

#### P6-4. `detect_protection` 误报率高

| 文件 | 行 | 问题 |
|------|-----|------|
| `decryptor.py` | 62-72 | 指标包含 `'解密'`、`'password'`、`'密码'` 等纯文本关键词，但这些词在非密码保护页面也可能出现（如"密码：本页面的密码是..."）。此外 `'class="cl-btn"'` 不会在 Crawl4AI 的 HTML 中出现（它是 JS 渲染的），导致对 yudou66 实际页面漏检。 |

**影响：** 简单站点可能被误判为密码保护，触发不必要的 YouTube 密码流程；而 yudou66 可能因为 JS 渲染而漏检。

#### P6-5. `_run_cloud_drive` 重复解析同一 zip 的问题

| 文件 | 行 | 问题 |
|------|-----|------|
| `site_processor.py` | 108-123 | `tempfile.TemporaryDirectory` 在 `for drive_url in drive_urls` 循环内创建，每个 Drive 链接单独一个临时目录。但如果 FXRJ 每个视频只有一个 Drive 链接，这不是问题。真正的问题是：`download_and_extract_zip` 从 zip 解压出的文件被读入内存后，临时目录就销毁了，文件路径也失效了——这本身是正确的（内容已读入 `body`），但 zip 文件的清理逻辑（`zip_path.unlink`）可能因为 Windows 文件锁定而失败。 |

#### P6-6. `_has_subscription_content` 匹配过于宽泛

| 文件 | 行 | 问题 |
|------|-----|------|
| `decryptor.py` | 162-176 | `'clash'` 和 `'v2ray'` 作为关键词匹配，但这些词在页面的广告、推荐文章、导航链接中大量出现。任何页面只要提到"Clash"就会被判定为"有订阅内容"，导致假阳性。 |

**影响：** 解密一个实际上不含节点的页面时，`try_decrypt` 会误判成功。

#### P6-7. `site_processor.py` `_run_cloud_drive` 缺少 `type` 字段访问

| 文件 | 行 | 问题 |
|------|-----|------|
| `site_processor.py` | 43 | `getattr(self.site, 'type', 'simple')` 尝试访问 `SiteConfig.type`，但当前 `SiteConfig` dataclass **没有 `type` 字段**。所有站点都会走 `_run_blog` 路径。 |

**影响：** FXRJ 和 ZYFXS 的 `cloud_drive` / `yt_pwd` 类型永远不会被触发。

---

### 🟢 低

#### P6-8. `_try_youtube_password_flow` 中 `links` 包含非 URL 内容

| 文件 | 行 | 问题 |
|------|-----|------|
| `site_processor.py` | 257-259 | `llm_result.get("other", [])` 和 `llm_result.get("txt", [])` 一起加入 `links`，但 `other` 类型的链接可能不是直接可下载的文件（如 paste.to、OneDrive 需要额外处理）。这些链接直接进入 `_download_retry`，会失败。 |

#### P6-9. `decryptor.py` 的 `try_decrypt` 未利用 `detect_protection`

| 文件 | 行 | 问题 |
|------|-----|------|
| `decryptor.py` | 75-131 | `try_decrypt` 直接尝试解密，不先调用 `detect_protection` 检查页面是否真的需要密码。如果页面没有密码输入框，会静默失败。`_try_youtube_password_flow` 中也没有调用 `detect_protection`。 |

#### P6-10. `paste.py` 未使用 `extract_paste_url` 从视频描述提取

| 文件 | 行 | 问题 |
|------|-----|------|
| `paste.py` | 18-48 | `extract_paste_url` 函数存在但 `site_processor.py` 的 `_run_cloud_drive` 和 `_try_youtube_password_flow` 中都没有调用它。ZYFXS 流程中提取 paste.to URL 这一步没有被集成。 |

#### P6-11. `youtube.py` 的 `_download_subtitles` 同步阻塞

| 文件 | 行 | 问题 |
|------|-----|------|
| `youtube.py` | 162-180 | `subprocess.run` 在 async 上下文中阻塞事件循环。在并发运行多个站点时，一个站点的字幕下载会阻塞所有其他站点。 |

---

## 三、优先级排序

| # | 严重度 | 问题 | 文件 |
|---|--------|------|------|
| P6-7 | 🔴 | SiteConfig 缺 `type` 字段，cloud_drive/yt_pwd 永远不触发 | site_processor.py + config.py |
| P6-1 | 🔴 | zip 内多文件被错误合并为一个字符串 | site_processor.py |
| P6-2 | 🔴 | get_video_metadata 同步阻塞事件循环 | youtube.py |
| P6-4 | 🟡 | detect_protection 误报率高 | decryptor.py |
| P6-6 | 🟡 | _has_subscription_content 太宽泛 | decryptor.py |
| P6-5 | 🟡 | Windows zip 文件锁定 | drive.py |
| P6-10 | 🟢 | paste.to 流程未集成 | paste.py + site_processor.py |
| P6-8 | 🟢 | "other" 链接不可直接下载 | site_processor.py |
| P6-9 | 🟢 | try_decrypt 未调 detect_protection | decryptor.py |
| P6-11 | 🟢 | subprocess 阻塞事件循环 | youtube.py |

---

## 四、建议

### 必须修

1. **P6-7**: 给 `SiteConfig` 加 `type: str = "simple"` 字段，`save_config` 持久化
2. **P6-1**: `_run_cloud_drive` 中把 zip 内文件逐个读入列表而非合并后加入 set
3. **P6-2**: `get_video_metadata` 的 `subprocess.run` 改为 `asyncio.create_subprocess_exec`

### 应该修

4. **P6-4**: `detect_protection` 只保留结构性指标（`.cl-input`、`input[type=password]`），去掉纯文本关键词
5. **P6-6**: `_has_subscription_content` 去掉 `'clash'` 和 `'v2ray'`，只匹配 URL 格式
6. **P6-10**: 在 `_run_blog` 的 yt_pwd 流程中加入 `extract_paste_url` 调用
