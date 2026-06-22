"""Tests for YouTube extractor: date parsing, password extraction, link extraction.

Run: pytest tests/test_youtube.py -v
"""
from src.youtube import (
    extract_password_from_text,
    extract_external_links,
    extract_cloud_drive_links,
    extract_paste_links,
    extract_date_from_title,
    _extract_video_id,
)


# ═══════════════════════════════════════════════════════════════
# extract_date_from_title
# ═══════════════════════════════════════════════════════════════

class TestExtractDateFromTitle:

    def test_cn_full_date(self):
        assert extract_date_from_title("2026年06月22日免费节点") == "2026-06-22"

    def test_slash_date_cn(self):
        assert extract_date_from_title("【每日更新】290个免费节点（2026/6/22）") == "2026-06-22"

    def test_slash_date_en(self):
        assert extract_date_from_title("[Daily Update] 270 Free Nodes (06/16/2026)") == "2026-06-16"

    def test_hyphen_date(self):
        assert extract_date_from_title("Free Nodes 2026-6-22 update") == "2026-06-22"

    def test_month_day_only(self):
        result = extract_date_from_title("6月22日更新免费节点")
        assert result is not None
        assert "06-22" in result

    def test_no_date(self):
        assert extract_date_from_title("Free Nodes Update") is None


# ═══════════════════════════════════════════════════════════════
# extract_password_from_text
# ═══════════════════════════════════════════════════════════════

class TestExtractPasswordFromText:

    def test_aabb_pattern_first(self):
        text = "密码：6767\n其他内容"
        result = extract_password_from_text(text)
        assert result[0] == "6767"

    def test_abab_pattern(self):
        text = "密码：1212"
        result = extract_password_from_text(text)
        assert result[0] == "1212"

    def test_prefers_aabb_over_other(self):
        text = "密码可能是5678或3344"
        result = extract_password_from_text(text)
        # 3344 (AABB) should come before 5678 (no pattern)
        assert result.index("3344") < result.index("5678")

    def test_password_keyword_required(self):
        text = "今天是2026年6月22日，有203条节点"
        result = extract_password_from_text(text)
        assert len(result) == 0  # No "密码" keyword

    def test_english_password_keyword(self):
        text = "Password: 5566"
        result = extract_password_from_text(text)
        assert "5566" in result

    def test_multiple_candidates(self):
        text = "密码可能是1234或5678或9900"
        result = extract_password_from_text(text)
        assert len(result) == 3


# ═══════════════════════════════════════════════════════════════
# extract_external_links
# ═══════════════════════════════════════════════════════════════

class TestExtractExternalLinks:

    def test_basic_url(self):
        text = "下载地址：https://drive.google.com/file/d/abc123/view"
        links = extract_external_links(text)
        assert len(links) == 1
        assert "drive.google.com" in links[0]

    def test_preserves_fragment(self):
        text = "https://paste.to/?key123#secretFragment456"
        links = extract_external_links(text)
        assert len(links) == 1
        assert "#secretFragment456" in links[0]

    def test_youtube_redirect_extraction(self):
        text = "https://www.youtube.com/redirect?event=video_description&redir_token=abc&q=https%3A%2F%2Fpaste.to%2F%3Fkey123%23fragment456"
        links = extract_external_links(text)
        assert len(links) >= 1
        assert any("paste.to" in l for l in links)

    def test_no_links(self):
        assert extract_external_links("没有链接的文本") == []


# ═══════════════════════════════════════════════════════════════
# extract_cloud_drive_links
# ═══════════════════════════════════════════════════════════════

class TestExtractCloudDriveLinks:

    def test_google_drive(self):
        text = "下载：https://drive.google.com/file/d/abc123/view"
        links = extract_cloud_drive_links(text)
        assert len(links) == 1

    def test_onedrive(self):
        text = "微软云盘：https://1drv.ms/f/c/abc123"
        links = extract_cloud_drive_links(text)
        assert len(links) == 1

    def test_excludes_non_drive(self):
        text = "链接：https://example.com/file.txt"
        links = extract_cloud_drive_links(text)
        assert len(links) == 0


# ═══════════════════════════════════════════════════════════════
# extract_paste_links
# ═══════════════════════════════════════════════════════════════

class TestExtractPasteLinks:

    def test_paste_to(self):
        text = "资源地址：https://paste.to/?3c4d47bd5fa1f66a#BwJn7AXEmdXR88rdRZyY7JXjKrmd8NgcjVwU2SiwroVf"
        links = extract_paste_links(text)
        assert len(links) == 1
        assert "#BwJn" in links[0]

    def test_excludes_non_paste(self):
        text = "链接：https://drive.google.com/file/d/abc/view"
        links = extract_paste_links(text)
        assert len(links) == 0


# ═══════════════════════════════════════════════════════════════
# _extract_video_id
# ═══════════════════════════════════════════════════════════════

class TestExtractVideoId:

    def test_standard_url(self):
        assert _extract_video_id("https://www.youtube.com/watch?v=abc123def45") == "abc123def45"

    def test_short_url(self):
        assert _extract_video_id("https://youtu.be/abc123def45") == "abc123def45"

    def test_embed_url(self):
        assert _extract_video_id("https://www.youtube.com/embed/abc123def45") == "abc123def45"

    def test_shorts_url(self):
        assert _extract_video_id("https://www.youtube.com/shorts/abc123def45") == "abc123def45"

    def test_invalid_url(self):
        assert _extract_video_id("https://example.com") is None

    def test_with_extra_params(self):
        assert _extract_video_id("https://www.youtube.com/watch?v=abc123def45&t=120") == "abc123def45"
