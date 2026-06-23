# P6 — YouTube / 密码保护站点实现计划

> **前置：** 三个目标站点已全部模拟完成，掌握了完整的页面结构、解密流程、数据格式

---

## 一、三个站点的实测数据流

### FXRJ（YouTube 频道 → Google Drive → zip）

```
1. yt-dlp list_channel(@fxrj) → 获取视频列表
2. 标题中提取日期 → 选最新 N 个
3. yt-dlp dump_json(视频URL) → 获取 description
4. 正则提取 description 中的 Google Drive 链接
5. 下载 zip（Google Drive direct download API）
6. 解压 → 取 .txt/.yaml 文件
```

**关键参数：**
- 频道名：`分享日记`
- 视频标题：`【每日更新】290个免费节点（2026/6/22）`
- Drive 链接格式：`https://drive.google.com/file/d/{FILE_ID}/view`
- 直接下载：`https://drive.google.com/uc?export=download&id={FILE_ID}`

---

### Yudou（博客 → YouTube 字幕 → 密码 → 解密）

```
1. Crawl4AI 爬取博客列表 → 提取文章链接
2. Crawl4AI 爬取文章 → 检测密码输入框 (.cl-input)
3. 正则提取 YouTube 链接（youtu.be / youtube.com）
4. yt-dlp 获取视频字幕 → 提取 4 位密码
5. Playwright 填入密码 → 点击 .cl-btn → 获取解密内容
6. 正则提取订阅链接
```

**关键参数：**
- 博客 URL：`https://www.yudou789.top/category/jiedian/`
- 文章 URL 格式：`https://www.yudou789.top/{id}.html`
- 密码输入框：`.cl-input`（`placeholder="在此输入密码"`）
- 解密按钮：`.cl-btn`（文字 "解密"）
- 订阅链接格式：`https://hh.yudou226.top/{YYYYMM}/{YYYYMMDD}{random}.txt` / `.yaml`
- 密码类型：4 位数字，AABB 型（如 6767）或 ABAB 型（如 1122），优先级：字幕 > 页面正则 > 暴力枚举
- 旧文章（>2天）不受密码保护，直接可见

---

### ZYFXS（YouTube → paste.to 加密粘贴 → OneDrive 链接）

```
1. yt-dlp list_channel(@ZYFXS) → 获取视频列表
2. yt-dlp dump_json(视频URL) → 获取 description
3. 从 description 提取 paste.to 完整 URL（含 #fragment 密钥）
4. Playwright 打开 paste.to → 输入密码（从字幕获取）
5. 解密 → 提取 OneDrive 订阅链接
6. 下载 .jpg 文件（实际是 base64 订阅数据）
```

**关键参数：**
- paste.to 是客户端 AES 加密，密钥在 URL fragment（`#` 后）
- YouTube 重定向会丢 fragment → 必须从原始描述提取完整 URL
- 一键 `event=video_description` 重定向格式 → 需解析出真实 URL
- paste.to 密码输入框：`#passworddecrypt`
- paste.to 解密按钮：`button:has-text("解密")`
- 订阅链接伪装为 `.jpg`，实际是 base64 编码的订阅数据
- OneDrive 链接格式：`https://1drv.ms/f/c/{path}`

---

## 二、模块设计

### 2.1 `src/youtube.py` — yt-dlp 封装

```python
@dataclass
class YouTubeVideo:
    url: str
    video_id: str
    title: str
    description: str          # 完整描述（保留原始链接含 fragment）
    upload_date: str          # YYYYMMDD
    subtitles_text: str       # 合并字幕纯文本
    channel: str
    success: bool = False

class YouTubeExtractor:
    """yt-dlp wrapper for channel listing, metadata, and subtitles."""

    async def list_channel_videos(channel_url: str, limit: int = 10) -> list[YouTubeVideo]:
        """列出频道最新视频（flat-playlist，不下载）"""

    async def get_video_metadata(video_url: str) -> YouTubeVideo:
        """获取单个视频的完整元数据 + 字幕"""

    async def _download_subtitles(video_url: str) -> str:
        """下载字幕并合并为纯文本"""

    def extract_password_from_text(text: str) -> list[str]:
        """从文本中提取 4 位数字密码候选"""

    def extract_external_links(description: str) -> list[str]:
        """从描述中提取外部链接（Drive/paste.to 等）"""
```

### 2.2 `src/drive.py` — Google Drive 下载

```python
class DriveDownloader:
    """Google Drive file download with anti-scan handling."""

    def extract_file_id(url: str) -> str | None:
        """从 Drive URL 提取 file ID"""

    async def download(file_id: str, dest: Path, timeout: int = 60) -> Path:
        """下载文件到指定路径"""

    async def download_and_extract_zip(file_id: str, dest_dir: Path) -> list[Path]:
        """下载 zip 并解压，返回包含的订阅文件列表"""
```

### 2.3 `src/decryptor.py` — 密码解密模块

```python
class Decryptor:
    """Playwright-based page decryption."""

    async def detect_protection(page: Page) -> bool:
        """检测页面是否需要密码"""

    async def submit_password(url: str, password: str, selectors: dict) -> PageResult:
        """填写密码并提交，返回解密后的内容"""

    async def brute_force_4digit(url: str, selectors: dict, hint: str = "AABB") -> str | None:
        """暴力破解 4 位密码，优先 AABB/ABAB 型"""

    def generate_password_candidates(hint: str = "AABB") -> Generator[str]:
        """按 hint 类型生成密码候选序列"""
```

### 2.4 `src/paste.py` — 加密粘贴板处理

```python
class PasteDecryptor:
    """Handle client-side encrypted pastes (paste.to, PrivateBin)."""

    def extract_paste_url(description: str) -> str | None:
        """从 YouTube 描述中提取完整 paste.to URL（含 fragment key）"""

    async def decrypt_with_password(url: str, password: str) -> str | None:
        """打开 paste.to URL → 填入密码 → 获取解密内容"""
```

### 2.5 `src/site_processor.py` 扩展

```python
async def _process_youtube_channel(self, site: SiteConfig) -> list[NodeItem]:
    """处理 YouTube 频道型站点（FXRJ/ZYFXS）"""

async def _process_password_blog(self, site: SiteConfig) -> list[NodeItem]:
    """处理密码保护博客（Yudou）"""

async def _find_and_use_password(self, page: Page, yt_url: str) -> PageResult | None:
    """从 YouTube 字幕获取密码 → 尝试解密"""
```

---

## 三、实施顺序

| 阶段 | 内容 | 复杂度 | 前置 |
|------|------|--------|------|
| **P6.1** | `youtube.py`：list_channel + get_metadata + subtitles | 中 | yt-dlp 已安装 |
| **P6.2** | `drive.py`：extract_id + download + unzip | 低 | httpx 已有 |
| **P6.3** | `decryptor.py`：detect + submit + brute_force | 高 | Crawl4AI 已有 |
| **P6.4** | `paste.py`：extract_url + decrypt | 中 | Playwright 已有 |
| **P6.5** | FXRJ 集成（频道 → Drive → zip） | 低 | P6.1 + P6.2 |
| **P6.6** | Yudou 集成（博客 → YouTube → 密码） | 中 | P6.1 + P6.3 |
| **P6.7** | ZYFXS 集成（YouTube → paste → OneDrive） | 中 | P6.1 + P6.3 + P6.4 |

---

## 四、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| yt-dlp 字幕为空（口述密码） | 无法自动获取密码 | 回退：暴力枚举 AABB/ABAB（最多 180 次） |
| YouTube 反爬 | yt-dlp 被 403 | 用 Playwright 兜底获取描述 |
| paste.to fragment 丢失 | 无法解密 | 从 YouTube 原始描述提取完整 URL（含 #key） |
| Google Drive virus scan | 大文件下载失败 | `export=download` 格式 + 重试 |
| `.jpg` 伪装链接 | 扩展名误导 | 检测 Content-Type，忽略扩展名 |
| 密码输入框结构变化 | 解密失败 | 让 LLM 分析页面 → 生成操作指令 |
