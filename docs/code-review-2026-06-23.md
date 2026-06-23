# Code Review — Full Project Review (Post-P6)

> **Date:** 2026-06-23
> **Scope:** All source files + tests after P6 completion + code-review fixes
> **Tests:** 175 passed
> **Method:** Read every source file, trace cross-file dependencies, check against CLAUDE.md rules

---

## Summary

| Severity | Count | Status |
|----------|-------|--------|
| 🔴 Bug | 3 | Need fix |
| 🟡 Style/DRY | 4 | Should fix |
| 🟢 Suggestion | 3 | Optional |

---

## 🔴 Bugs (3)

### B1: `save_config` doesn't persist `pwd_hint` / `yt_hint` / `type`

**File:** `src/config.py:71-78`

`SiteConfig` has `type`, `pwd_hint`, `yt_hint` fields, but `save_config` only writes `name`, `start_url`, `type`, `description` to YAML. After self-heal, the `pwd_hint` and `yt_hint` fields added by the user in `config.yaml` would be lost on save.

```python
# Missing from save_config entry dict:
# "pwd_hint": s.pwd_hint,
# "yt_hint": s.yt_hint,
```

**Fix:** Add these fields to the entry dict in `save_config`.

---

### B2: `main.py` line 47 — `sys.exit(0)` makes exit code meaningless

```python
sys.exit(0)  # always success, even if all sites crashed
```

The comment says "errors are visible in the summary log" but `sys.exit(0)` means GitHub Actions will never know the run partially failed. If the network is down for 2 hours and all 9 sites fail, the workflow still shows green.

**Fix:** Exit 1 only when ALL sites failed (not when some sites have errors, since CDN 403 is expected).

---

### B3: `merger.py` `_dedup_proxies` mutates input dicts

**File:** `src/merger.py:243`

```python
p["name"] = name  # mutates the original dict from all_proxies
```

If the same proxy dict is referenced elsewhere (e.g., YAML loaded from a file that's still in memory), the mutation leaks. In practice this works because `yaml.safe_load_all` creates fresh dicts, but it's fragile.

**Fix:** Copy the dict before mutating: `p = {**p, "name": name}`.

---

## 🟡 Style / DRY Issues (4)

### S1: `readme_updater.py` — unused variables `merged_txt`, `merged_yaml`, `provider_yaml`

**Lines 42-44:**

```python
merged_txt = Path("nodes/merged.txt")      # never used
merged_yaml = Path("nodes/merged.yaml")    # never used
provider_yaml = Path("nodes/provider.yaml") # never used
```

Dead code. These were likely intended for a merged row but the actual merged row uses a separate loop at lines 69-84.

**Fix:** Delete lines 42-44.

---

### S2: `site_processor.py` — duplicate `import` inside methods

The `_try_youtube_password_flow` and `_run_cloud_drive` methods import `from src.youtube import ...` and `from src.drive import ...` at runtime. This is a pattern to avoid circular imports, but it's repeated 3 times. Could be a single lazy import helper.

**Severity:** Low — works correctly, just not DRY.

---

### S3: `decryptor.py` — `_has_subscription_content` is defined in both `decryptor.py` and `paste.py`

Both files have identical copies of this function:

```python
# decryptor.py line 172
def _has_subscription_content(text: str, html: str) -> bool: ...

# paste.py line 119
def _has_subscription_content(text: str, html: str) -> bool: ...
```

**Fix:** Move to a shared utility (e.g., `src/utils.py`) or keep in `decryptor.py` and import from `paste.py`.

---

### S4: `merger.py` — `_base_clash_config` default values duplicated from real Clash config

The hardcoded DNS servers (`223.5.5.5`, `114.114.114.114`) and port `7890` are Chinese-centric defaults. Not a bug, but worth noting for international users.

---

## 🟢 Suggestions (3)

### G1: `crawler.py` — new `AsyncWebCrawler()` per call

Each `fetch_page` creates a new `AsyncWebCrawler()` instance. This works but is slower than reusing one instance across multiple fetches (Playwright browser startup overhead).

**Trade-off:** Reusing requires managing instance lifecycle. Current approach is simpler and reliable.

---

### G2: `youtube.py` — `_extract_video_id` returns `None` for `youtu.be` with path params

URLs like `https://youtu.be/abc123?si=xyz` would match but `abc123?si=xyz` is 18 chars, failing the `{11}` length check. The regex `(?:youtu\.be/)([a-zA-Z0-9_-]{11})` correctly stops at `?` because `?` is not in the char class. This is fine.

---

### G3: `config.yaml` — Cerebras models may be stale

Cerebras is known to change free models without notice. The config lists `zai-glm-4.7` and `gpt-oss-120b` which were verified working, but may break in days. Consider a note in config.yaml or a health check that warns on 404.

---

## Code Style Compliance (CLAUDE.md)

| Rule | Status | Notes |
|------|--------|-------|
| `str \| None` not `Optional` | ✅ | All files compliant |
| `list[dict]` not `List[Dict]` | ✅ | All files compliant |
| English code + comments | ✅ | Chinese kept in REGION_KEYWORDS, README output, decryptor keywords (correct) |
| Tests per module | ✅ | 8 test files, 175 tests |
| No `Optional` import | ✅ | No `from typing import Optional` anywhere |
