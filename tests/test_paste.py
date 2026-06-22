"""Tests for paste.to decryptor: URL extraction, link parsing.

Run: pytest tests/test_paste.py -v
"""
from src.paste import extract_paste_url, _extract_links_from_paste


# ═══════════════════════════════════════════════════════════════
# extract_paste_url
# ═══════════════════════════════════════════════════════════════

class TestExtractPasteUrl:

    def test_paste_to_with_fragment(self):
        text = "资源地址：https://paste.to/?3c4d47bd5fa1f66a#BwJn7AXEmdXR88rdRZyY7JXjKrmd8NgcjVwU2SiwroVf"
        result = extract_paste_url(text)
        assert result is not None
        assert "#BwJn" in result
        assert "3c4d47bd5fa1f66a" in result

    def test_youtube_redirect_with_paste_url(self):
        text = (
            "https://www.youtube.com/redirect?event=video_description"
            "&redir_token=QUFFLUhqbTlVNGpoRDF1TWJXQTNJdGM1RjZPZXVIdk1id3xBQ3Jtc0tuS1NpT1FnSkczc0lqYnhib2JIZ2NLWnUtS3RhaWpBMTZ5Ym9OdjlHRXV0dzlPNmtkeERJTEE1MUJmNjJMMFBqdkU2Y3V3dWVQaGJRNVpGV3BIa1FEdklTeXhoMVd0UWk3dXFfVHk2VDRzM3ZOODJPUQ"
            "&q=https%3A%2F%2Fpaste.to%2F%3F3c4d47bd5fa1f66a%23BwJn7AXEmdXR88rdRZyY7JXjKrmd8NgcjVwU2SiwroVf"
            "&v=wh74r6AfCUM"
        )
        result = extract_paste_url(text)
        assert result is not None
        assert "paste.to" in result

    def test_no_paste_url(self):
        assert extract_paste_url("https://example.com") is None

    def test_paste_without_fragment_returns_none(self):
        """paste.to without fragment key can't be client-side decrypted."""
        text = "https://paste.to/?3c4d47bd5fa1f66a"
        result = extract_paste_url(text)
        assert result is None

    def test_privatebin_url(self):
        text = "https://privatebin.example.com/?abc123#secretkey456"
        result = extract_paste_url(text)
        assert result is not None
        assert "secretkey456" in result


# ═══════════════════════════════════════════════════════════════
# _extract_links_from_paste
# ═══════════════════════════════════════════════════════════════

class TestExtractLinksFromPaste:

    def test_txt_link(self):
        text = "订阅：https://example.com/v2ray.txt"
        links = _extract_links_from_paste(text)
        assert len(links) == 1
        assert links[0]["href"].endswith(".txt")

    def test_yaml_link(self):
        text = "clash: https://example.com/config.yaml"
        links = _extract_links_from_paste(text)
        assert len(links) == 1
        assert links[0]["href"].endswith(".yaml")

    def test_fake_jpg_onedrive(self):
        """OneDrive links disguised as .jpg files are captured."""
        text = "https://dlink.host/1drv/aHR0cHM6Ly8xZHJ2.jpg"
        links = _extract_links_from_paste(text)
        assert len(links) == 1

    def test_fake_jpg_1drv(self):
        text = "https://1drv.ms/f/c/abc123.jpg"
        links = _extract_links_from_paste(text)
        assert len(links) == 1

    def test_real_jpg_ignored(self):
        """Regular .jpg images are not subscription links."""
        text = "https://example.com/photo.jpg"
        links = _extract_links_from_paste(text)
        assert len(links) == 0

    def test_empty_text(self):
        assert _extract_links_from_paste("") == []

    def test_multiple_links(self):
        text = (
            "v2ray: https://example.com/v2.txt\n"
            "clash: https://example.com/c.yaml\n"
            "onedrive: https://dlink.host/1drv/abc.jpg"
        )
        links = _extract_links_from_paste(text)
        assert len(links) == 3
