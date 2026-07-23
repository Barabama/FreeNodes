# Code Review — README corruption + recent regression sweep

> **Date:** 2026-07-23
> **Context:** User reported README.md was missing site info after recent pushes. Investigation revealed `config.yaml` was overwritten with test data (site-a/site-b/site-c), causing `readme_updater.py` to generate a bogus table.

---

## 🔴 Regression: README.md test data leak

### Root Cause

`config.yaml` was silently overwritten with test fixture data (`site-a`, `site-b`, `site-c`). This happened because `save_config()` writes all sites from the in-memory `Config` object to disk — if some code path loads a test config and calls `save_config`, the production `config.yaml` gets corrupted.

### Leak path

```
  `pytest` creates Config(sites=[SiteConfig(name="site-a"), ...])
    → calls load_config("fixtures/test_config_minimal.yaml")
    → some code path calls save_config()
    → overwrites config.yaml with test data
```

The fix was to regenerate README manually. But the deeper problem — `save_config()` mutating `config.yaml` when a test config is loaded — still exists.

### Fix needed

1. **Done:** Regenerated README via `python -c "write_readme(load_config())"`
2. **Needed:** `save_config()` should validate the config path isn't the default `.yaml` when called from tests, OR test fixtures should use a non-default path.

---

## 🟢 Code Review Checklist

| # | File | Issue | Severity |
|---|------|-------|----------|
| 1 | `config.yaml` | `save_config()` leak overwrote prod config with test fixtures | 🔴 |
| 2 | `readme_updater.py` | No guard against empty/placeholder site names | 🟡 |
| 3 | `main.py` | `save_config()` called unconditionally (even if config didn't change) | 🟡 |
| 4 | CL init check | No test verifies `save_config()` preserves config.yaml | 🟢 |

---

## Tests

```
175 passed — 0 failed
```
