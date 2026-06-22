"""Google Drive file download with zip extraction.

Handles Google Drive's direct download URLs and virus-scan confirmation pages.
Downloads zip files and extracts subscription files (.txt/.yaml).
"""
import logging
import re
import zipfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Google Drive direct download endpoint
_DRIVE_DIRECT = "https://drive.google.com/uc?export=download"
_DRIVE_CONFIRM = "https://drive.google.com/uc?export=download&confirm=t"

# Subscription file extensions we care about
_SUB_EXTENSIONS = {".txt", ".yaml", ".yml", ".conf", ".json"}


def extract_drive_id(url: str) -> str | None:
    """Extract Google Drive file ID from various URL formats.

    Supported:
      - https://drive.google.com/file/d/{ID}/view
      - https://drive.google.com/open?id={ID}
      - https://drive.google.com/uc?id={ID}
    """
    # /file/d/{ID}/view
    m = re.search(r'/d/([a-zA-Z0-9_-]{10,})', url)
    if m:
        return m.group(1)
    # ?id={ID}
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]{10,})', url)
    if m:
        return m.group(1)
    return None


async def download_file(
    file_id: str,
    dest: Path,
    timeout: int = 60,
) -> Path:
    """Download a file from Google Drive by file ID.

    Handles the virus-scan confirmation page for larger files.
    Returns the path to the downloaded file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=15, read=timeout),
        follow_redirects=True,
    ) as client:
        # First attempt: direct download
        resp = await client.get(_DRIVE_DIRECT, params={"id": file_id})

        # Check for virus-scan confirmation page
        if _needs_confirmation(resp):
            logger.info("Drive virus-scan confirmation needed for %s", file_id)
            resp = await client.get(
                _DRIVE_CONFIRM,
                params={"id": file_id, "export": "download", "confirm": "t"},
            )

        resp.raise_for_status()
        dest.write_bytes(resp.content)

    logger.info("Downloaded %s → %s (%d bytes)", file_id, dest.name, len(resp.content))
    return dest


async def download_and_extract_zip(
    file_id: str,
    dest_dir: Path,
    timeout: int = 120,
) -> list[Path]:
    """Download a zip file from Drive and extract subscription files.

    Returns list of extracted subscription file paths.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / f"{file_id}.zip"

    try:
        await download_file(file_id, zip_path, timeout=timeout)
    except Exception as e:
        logger.error("Failed to download Drive file %s: %s", file_id, e)
        return []

    try:
        extracted = _extract_subscription_files(zip_path, dest_dir)
        return extracted
    except zipfile.BadZipFile:
        logger.error("Downloaded file is not a valid zip: %s", zip_path)
        return []
    finally:
        # Clean up zip file
        zip_path.unlink(missing_ok=True)


def _extract_subscription_files(zip_path: Path, dest_dir: Path) -> list[Path]:
    """Extract subscription files (.txt/.yaml/.yml/.conf/.json) from a zip archive."""
    extracted: list[Path] = []

    with zipfile.ZipFile(zip_path, 'r') as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            ext = Path(info.filename).suffix.lower()
            if ext in _SUB_EXTENSIONS:
                # Extract to dest_dir with original filename (flatten nested paths)
                target = dest_dir / Path(info.filename).name
                with zf.open(info) as src, open(target, 'wb') as dst:
                    dst.write(src.read())
                extracted.append(target)
                logger.info("Extracted: %s (%d bytes)", target.name, info.file_size)

    return extracted


def _needs_confirmation(resp: httpx.Response) -> bool:
    """Check if the response is a virus-scan confirmation page."""
    if resp.status_code == 200:
        text = resp.text[:500].lower()
        # Google Drive confirmation page contains these markers
        return "virus scan" in text or "confirm=" in text or "download_warning" in text
    return False
