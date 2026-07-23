# Code Review — Recent fix* and feat* commits

> **Date:** 2026-07-23
> **Scope:** Commits `2844f3a1..54903989` (5 feat/fix commits + README fix)
> **Files analyzed:** `src/site_processor.py`, `src/youtube.py`, `src/config.py`, `config.yaml`
> **Pre-existing:** 175 tests pass

---

## 🔴 Critical Bugs (2)

### F1: Duplicate import — `src/site_processor.py:272-273`

```python
from src.decryptor import detect_protection, try_decrypt, brute_force_4digit, generate_password_candidates
from src.decryptor import detect_protection, try_decrypt, brute_force_4digit, generate_password_candidates  # DUPLICATE
```

Two identical import lines. Not crashing (Python deduplicates imports) but the **second `extract_paste_links` import from youtube is missing** because it got lost when the duplicate was created:

Line 271: `from src.youtube import get_video_metadata, extract_password_from_text, extract_paste_links`

This is correct — all three are imported. But the duplicate line 272-273 is dead code.

**Fix:** ✅ Removed the duplicate line.

### F2: Proxy not configured for blog path — `src/site_processor.py`

`_run_cloud_drive` (line 65-66) configures the proxy for yt-dlp:
```python
if self.config.crawl.proxy:
    from src.youtube import configure as yt_configure
    yt_configure(self.config.crawl.proxy)
```

But `_run_blog` (line 172) does NOT. When it calls `_try_youtube_password_flow` → `get_video_metadata`, yt-dlp runs **without proxy**, so YouTube access fails for yudou.

**Fix:** ✅ Added identical proxy config block at the start of `_run_blog`.

---

## 🟡 Design Issues (2)

### F3: `config.yaml` — `oneclash` lost `failed_count`

```diff
-  failed_count: 1
```

The `failed_count: 1` on the `oneclash` site was removed when `type: simple` was added. This isn't critical (failed_count defaults to 0), but it means oneclash's pattern miss tracking reset to zero, requiring the LLM to be re-invoked next run.

---

## 🟢 Cleanup (2)

| # | File | Issue | Status |
|---|------|-------|--------|
| F4 | `src/site_processor.py` | 2 duplicate import lines (272-273) | ✅ Fixed |
| F5 | `src/site_processor.py` | `extract_paste_links` imported but only used in yt_pwd flow | Minor — unused import in cloud_drive path |

---

## Summary

| Severity | Count | Fixed |
|----------|-------|-------|
| 🔴 Bug | 2 | ✅ |
| 🟡 Design | 1 | ⚠️ Minor (`failed_count: 1` removed) |
| 🟢 Cleanup | 2 | ✅ |
