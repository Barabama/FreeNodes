"""YouTube video metadata and subtitle extraction via yt-dlp.

Replaces the old pytubefix-based PwdFinder with a more stable implementation.
yt-dlp handles anti-bot measures better and requires no OAuth.
"""
import asyncio
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Proxy config — set via config.yaml crawl.proxy
_YOUTUBE_PROXY: str = ""


def configure(proxy: str = ""):
    """Set global proxy for yt-dlp subprocess calls."""
    global _YOUTUBE_PROXY
    _YOUTUBE_PROXY = proxy


def _proxy_env() -> dict[str, str]:
    """Return environment dict with proxy set for yt-dlp subprocess."""
    env = os.environ.copy()
    if _YOUTUBE_PROXY:
        env["HTTP_PROXY"] = _YOUTUBE_PROXY
        env["HTTPS_PROXY"] = _YOUTUBE_PROXY
    return env


@dataclass
class YouTubeVideo:
    """Result of a YouTube video metadata extraction."""
    url: str
    video_id: str
    title: str
    description: str
    upload_date: str          # YYYYMMDD
    subtitles_text: str       # merged subtitle plain text
    channel: str
    success: bool = False
    error: str = ""


# ── Public API ──

async def list_channel_videos(channel_url: str, limit: int = 10) -> list[YouTubeVideo]:
    """List recent videos from a YouTube channel (flat playlist, no download).

    Returns a list of YouTubeVideo with title/url/upload_date populated.
    description and subtitles_text are empty (use get_video_metadata to fill).
    """
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--playlist-end", str(limit),
        channel_url,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=_proxy_env(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        logger.warning("yt-dlp list_channel timed out for %s", channel_url)
        return []

    if proc.returncode != 0:
        logger.warning("yt-dlp list_channel failed: %s", stderr.decode()[:200])
        return []

    videos: list[YouTubeVideo] = []
    for line in stdout.decode().strip().splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        video_id = data.get("id", "")
        url = data.get("url", f"https://www.youtube.com/watch?v={video_id}")
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"

        videos.append(YouTubeVideo(
            url=url,
            video_id=video_id,
            title=data.get("title", ""),
            description=data.get("description", ""),
            upload_date=data.get("upload_date", ""),
            subtitles_text="",
            channel=data.get("channel", data.get("uploader", "")),
            success=True,
        ))

    return videos


async def get_video_metadata(video_url: str) -> YouTubeVideo:
    """Get full metadata + subtitles for a single video.

    Subtitles are downloaded and merged into plain text.
    """
    video_id = _extract_video_id(video_url)
    if not video_id:
        return YouTubeVideo(url=video_url, video_id="", title="",
                            description="", upload_date="", subtitles_text="",
                            channel="", error="Invalid YouTube URL")

    # Step 1: Get metadata JSON
    cmd = ["yt-dlp", "--dump-json", "--skip-download", video_url]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=_proxy_env(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        return YouTubeVideo(url=video_url, video_id=video_id, title="",
                            description="", upload_date="", subtitles_text="",
                            channel="", error="yt-dlp timed out")

    if proc.returncode != 0:
        return YouTubeVideo(url=video_url, video_id=video_id, title="",
                            description="", upload_date="", subtitles_text="",
                            channel="", error=stderr.decode()[:200])

    try:
        data = json.loads(stdout.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return YouTubeVideo(url=video_url, video_id=video_id, title="",
                            description="", upload_date="", subtitles_text="",
                            channel="", error="Failed to parse yt-dlp JSON")

    # Step 2: Download subtitles
    subtitles = await _download_subtitles(video_url)

    return YouTubeVideo(
        url=video_url,
        video_id=video_id,
        title=data.get("title", ""),
        description=data.get("description", ""),
        upload_date=data.get("upload_date", ""),
        subtitles_text=subtitles,
        channel=data.get("channel", data.get("uploader", "")),
        success=True,
    )


# ── Password extraction ──

def extract_password_from_text(text: str) -> list[str]:
    """Extract 4-digit password candidates from text.

    Scans lines containing "密码" or "password" for digit sequences.
    Returns candidates sorted by pattern preference (AABB > ABAB > other).
    """
    candidates: list[str] = []
    lines = text.splitlines()
    for line in lines:
        if "密码" not in line and "password" not in line.lower():
            continue
        for match in re.finditer(r"\d{4}", line):
            pwd = match.group()
            if pwd not in candidates:
                candidates.append(pwd)

    def _priority(pwd: str) -> int:
        a, b, c, d = pwd[0], pwd[1], pwd[2], pwd[3]
        if a == b and c == d:    # AABB
            return 0
        if a == c and b == d:    # ABAB
            return 1
        return 2

    candidates.sort(key=_priority)
    return candidates


def extract_external_links(description: str) -> list[str]:
    """Extract external links (Drive, paste.to, OneDrive, etc.) from video description.

    Preserves URL fragments (#key) which are critical for paste.to decryption.
    """
    url_pattern = r'https?://[^\s<>"\')\]]+'
    links = re.findall(url_pattern, description)

    real_links: list[str] = []
    for link in links:
        if "youtube.com/redirect" in link:
            m = re.search(r'[&?]q=([^&]+)', link)
            if m:
                from urllib.parse import unquote
                real_links.append(unquote(m.group(1)))
                continue
        real_links.append(link)

    return real_links


def extract_cloud_drive_links(description: str) -> list[str]:
    """Extract Google Drive and OneDrive links from description."""
    links = extract_external_links(description)
    drive_keywords = ("drive.google.com", "1drv.ms", "onedrive", "sharepoint")
    return [l for l in links if any(k in l.lower() for k in drive_keywords)]


def extract_paste_links(description: str) -> list[str]:
    """Extract paste.to / PrivateBin links with fragment keys intact."""
    links = extract_external_links(description)
    paste_keywords = ("paste.to", "privatebin", "hastebin", "dpaste")
    return [l for l in links if any(k in l.lower() for k in paste_keywords)]


def extract_date_from_title(title: str) -> str | None:
    """Extract date from YouTube video title.

    Handles formats like:
      - 【每日更新】290个免费节点（2026/6/22）
      - [Daily Update] 270 Free Nodes (06/16/2026)
      - 2026年06月22日
    """
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', title)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', title)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', title)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    m = re.search(r'(\d{1,2})月(\d{1,2})日', title)
    if m:
        from datetime import date
        today = date.today()
        parsed = date(today.year, int(m.group(1)), int(m.group(2)))
        if (parsed - today).days > 30:
            parsed = parsed.replace(year=today.year - 1)
        return parsed.isoformat()

    return None


# ── Internal helpers ──

def _extract_video_id(url: str) -> str | None:
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
        r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


async def _download_subtitles(video_url: str) -> str:
    """Download auto-generated subtitles and merge into plain text."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "yt-dlp",
            "--write-auto-sub",
            "--sub-lang", "zh-Hans,zh,zh-CN,en",
            "--convert-subs", "srt",
            "--skip-download",
            "--output", f"{tmpdir}/video",
            video_url,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            return ""

        for srt_file in Path(tmpdir).glob("*.srt"):
            text = _parse_srt(srt_file)
            if text:
                return text

    return ""


def _parse_srt(path: Path) -> str:
    """Parse SRT subtitle file into plain text."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

    lines: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or "-->" in line or line.isdigit():
            continue
        line = re.sub(r'<[^>]+>', '', line)
        if line and line not in lines[-1:]:
            lines.append(line)

    return "\n".join(lines)
