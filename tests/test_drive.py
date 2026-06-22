"""Tests for Google Drive downloader: ID extraction, zip extraction.

Run: pytest tests/test_drive.py -v
"""
import zipfile
from pathlib import Path

from src.drive import extract_drive_id, _extract_subscription_files


# ═══════════════════════════════════════════════════════════════
# extract_drive_id
# ═══════════════════════════════════════════════════════════════

class TestExtractDriveId:

    def test_standard_view_url(self):
        url = "https://drive.google.com/file/d/1rnnLgSZKTxMCtjaEjqN-rTsBc30AtRt4/view?usp=drive_link"
        assert extract_drive_id(url) == "1rnnLgSZKTxMCtjaEjqN-rTsBc30AtRt4"

    def test_open_url(self):
        url = "https://drive.google.com/open?id=1rnnLgSZKTxMCtjaEjqN-rTsBc30AtRt4"
        assert extract_drive_id(url) == "1rnnLgSZKTxMCtjaEjqN-rTsBc30AtRt4"

    def test_uc_url(self):
        url = "https://drive.google.com/uc?id=1rnnLgSZKTxMCtjaEjqN-rTsBc30AtRt4&export=download"
        assert extract_drive_id(url) == "1rnnLgSZKTxMCtjaEjqN-rTsBc30AtRt4"

    def test_short_url(self):
        url = "https://drive.google.com/file/d/abc123DEF456_-/preview"
        assert extract_drive_id(url) == "abc123DEF456_-"

    def test_non_drive_url(self):
        assert extract_drive_id("https://example.com/file.txt") is None

    def test_too_short_id(self):
        assert extract_drive_id("https://drive.google.com/file/d/abc/view") is None


# ═══════════════════════════════════════════════════════════════
# _extract_subscription_files
# ═══════════════════════════════════════════════════════════════

class TestExtractSubscriptionFiles:

    def test_extracts_txt_and_yaml(self, tmp_path):
        """Zip with .txt and .yaml files gets both extracted."""
        zip_path = tmp_path / "test.zip"
        dest = tmp_path / "out"
        dest.mkdir()

        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("sub.txt", "vmess://abc123")
            zf.writestr("config.yaml", "proxies: []")
            zf.writestr("readme.txt", "not a subscription")

        extracted = _extract_subscription_files(zip_path, dest)
        names = sorted(p.name for p in extracted)
        assert "sub.txt" in names
        assert "config.yaml" in names

    def test_extracts_nested_paths_flattened(self, tmp_path):
        """Files in nested directories get flattened to dest_dir."""
        zip_path = tmp_path / "test.zip"
        dest = tmp_path / "out"
        dest.mkdir()

        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("folder/subfolder/node.txt", "content")

        extracted = _extract_subscription_files(zip_path, dest)
        assert len(extracted) == 1
        assert extracted[0].name == "node.txt"
        assert extracted[0].parent == dest

    def test_skips_non_sub_files(self, tmp_path):
        """Files with non-subscription extensions are skipped."""
        zip_path = tmp_path / "test.zip"
        dest = tmp_path / "out"
        dest.mkdir()

        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("image.jpg", "fake")
            zf.writestr("doc.pdf", "fake")
            zf.writestr("script.py", "fake")
            zf.writestr("node.txt", "vmess://abc")

        extracted = _extract_subscription_files(zip_path, dest)
        assert len(extracted) == 1
        assert extracted[0].name == "node.txt"

    def test_skips_directories(self, tmp_path):
        """Directory entries in zip are skipped."""
        zip_path = tmp_path / "test.zip"
        dest = tmp_path / "out"
        dest.mkdir()

        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("folder/", "")  # directory entry
            zf.writestr("folder/node.yaml", "proxies: []")

        extracted = _extract_subscription_files(zip_path, dest)
        assert len(extracted) == 1
        assert extracted[0].name == "node.yaml"

    def test_empty_zip(self, tmp_path):
        """Empty zip returns empty list."""
        zip_path = tmp_path / "empty.zip"
        dest = tmp_path / "out"
        dest.mkdir()

        with zipfile.ZipFile(zip_path, 'w'):
            pass

        assert _extract_subscription_files(zip_path, dest) == []

    def test_multiple_txt_files(self, tmp_path):
        """Multiple .txt files are all extracted."""
        zip_path = tmp_path / "test.zip"
        dest = tmp_path / "out"
        dest.mkdir()

        with zipfile.ZipFile(zip_path, 'w') as zf:
            for i in range(5):
                zf.writestr(f"{i}-20260622.txt", f"content-{i}")

        extracted = _extract_subscription_files(zip_path, dest)
        assert len(extracted) == 5


# ═══════════════════════════════════════════════════════════════
# _needs_confirmation (via mock)
# ═══════════════════════════════════════════════════════════════

class TestNeedsConfirmation:

    def test_virus_scan_page(self):
        from src.drive import _needs_confirmation
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "<html>virus scan warning confirm=t</html>"
        assert _needs_confirmation(resp) is True

    def test_normal_response(self):
        from src.drive import _needs_confirmation
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "vmess://abc123 normal content"
        assert _needs_confirmation(resp) is False

    def test_redirect_response(self):
        from src.drive import _needs_confirmation
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.status_code = 302
        resp.text = ""
        assert _needs_confirmation(resp) is False
