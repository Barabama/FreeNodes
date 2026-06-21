"""Tests for llm_router: WeightedSelector, HealthTracker, LLMRouter.

Run with: pytest tests/test_llm_router.py -v
"""
import json
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio

from src.llm_router import WeightedSelector, HealthTracker, LLMRouter
from src.config import ProviderConfig, Config, LLMConfig, CrawlConfig, SiteConfig

# ── Fixtures ──

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def full_config():
    from src.config import load_config
    return load_config(str(FIXTURE_DIR / "config_full.yaml"))


@pytest.fixture
def no_llm_config():
    from src.config import load_config
    return load_config(str(FIXTURE_DIR / "config_no_llm.yaml"))


# ═══════════════════════════════════════════════════════════════
# WeightedSelector
# ═══════════════════════════════════════════════════════════════

class TestWeightedSelector:

    def test_returns_none_for_empty_weights(self):
        selector = WeightedSelector()
        result = selector.pick({}, lambda n: True)
        assert result is None

    def test_returns_only_option(self):
        selector = WeightedSelector()
        result = selector.pick({"a": 100}, lambda n: True)
        assert result == "a"

    def test_returns_only_option_with_min_weight(self):
        selector = WeightedSelector()
        result = selector.pick({"a": 1}, lambda n: True)
        assert result == "a"

    def test_skips_unhealthy_providers(self):
        selector = WeightedSelector()
        healthy_set = {"a"}
        result = selector.pick(
            {"a": 50, "b": 50},
            lambda n: n in healthy_set,
        )
        assert result == "a"

    def test_returns_none_when_all_unhealthy(self):
        selector = WeightedSelector()
        result = selector.pick({"a": 50}, lambda n: False)
        assert result is None

    def test_skips_excluded_providers(self):
        selector = WeightedSelector()
        result = selector.pick(
            {"a": 50, "b": 50, "c": 50},
            lambda n: True,
            exclude={"a", "b"},
        )
        assert result == "c"

    def test_distribution_matches_weights(self):
        """Statistical: 10,000 picks should approximate the weight ratio."""
        selector = WeightedSelector()
        weights = {"a": 60, "b": 30, "c": 10}
        counts = {"a": 0, "b": 0, "c": 0}
        for _ in range(10000):
            pick = selector.pick(weights, lambda n: True)
            counts[pick] += 1
        total = sum(counts.values())
        assert abs(counts["a"] / total - 0.6) < 0.03
        assert abs(counts["b"] / total - 0.3) < 0.03
        assert abs(counts["c"] / total - 0.1) < 0.03

    def test_zero_weight_never_picked(self):
        selector = WeightedSelector()
        for _ in range(1000):
            pick = selector.pick({"a": 100, "b": 0}, lambda n: True)
            assert pick == "a"

    def test_exclude_all_returns_none(self):
        selector = WeightedSelector()
        result = selector.pick({"a": 100}, lambda n: True, exclude={"a"})
        assert result is None


# ═══════════════════════════════════════════════════════════════
# HealthTracker
# ═══════════════════════════════════════════════════════════════

class TestHealthTracker:

    def test_initial_state_is_healthy(self):
        tracker = HealthTracker()
        assert tracker.is_healthy("p1") is True

    def test_disabled_after_max_failures(self):
        tracker = HealthTracker(max_failures=3, cooldown_seconds=300)
        for _ in range(3):
            tracker.record_failure("p1")
        assert tracker.is_healthy("p1") is False

    def test_still_healthy_below_threshold(self):
        tracker = HealthTracker(max_failures=3, cooldown_seconds=300)
        tracker.record_failure("p1")
        tracker.record_failure("p1")
        assert tracker.is_healthy("p1") is True

    def test_success_resets_failure_count(self):
        tracker = HealthTracker(max_failures=3, cooldown_seconds=300)
        for _ in range(2):
            tracker.record_failure("p1")
        tracker.record_success("p1")
        for _ in range(2):
            tracker.record_failure("p1")
        assert tracker.is_healthy("p1") is True  # still 2, not 4

    def test_success_clears_disabled(self):
        tracker = HealthTracker(max_failures=2, cooldown_seconds=300)
        tracker.record_failure("p1")
        tracker.record_failure("p1")
        assert tracker.is_healthy("p1") is False
        tracker.record_success("p1")
        assert tracker.is_healthy("p1") is True

    def test_auto_recovery_after_cooldown(self):
        tracker = HealthTracker(max_failures=2, cooldown_seconds=0.01)
        tracker.record_failure("p1")
        tracker.record_failure("p1")
        assert tracker.is_healthy("p1") is False
        time.sleep(0.02)
        assert tracker.is_healthy("p1") is True

    def test_multiple_providers_independent(self):
        tracker = HealthTracker(max_failures=2, cooldown_seconds=300)
        tracker.record_failure("p1")
        tracker.record_failure("p1")
        assert tracker.is_healthy("p1") is False
        assert tracker.is_healthy("p2") is True  # unaffected

    def test_health_report(self):
        tracker = HealthTracker(max_failures=3, cooldown_seconds=300)
        tracker.record_failure("p1")
        report = tracker.health_report()
        assert report["p1"]["failures"] == 1
        assert report["p1"]["healthy"] is True


# ═══════════════════════════════════════════════════════════════
# LLMRouter (mocked _try_provider)
# ═══════════════════════════════════════════════════════════════

class FakeResponseMessage:
    """Mock for ChatCompletion response message."""
    def __init__(self, content: str | None, reasoning: str | None = None):
        self.content = content
        self.reasoning = reasoning


class FakeChoice:
    def __init__(self, content: str | None, reasoning: str | None = None):
        self.message = FakeResponseMessage(content, reasoning)


class FakeResponse:
    def __init__(self, content: str | None):
        self.choices = [FakeChoice(content)]


def _make_router(config: Config | None = None, providers: dict[str, list[str | None]] | None = None):
    """Build a router with mocked _try_provider returning canned responses.

    *providers* maps provider name to a list of return values (one per call).
    *None* means failure.
    """
    if config is None:
        config = Config(
            sites=[SiteConfig(name="test", start_url="https://example.com")],
            crawl=CrawlConfig(),
            output={"dir": "nodes"},
            llm=LLMConfig(
                providers=[
                    ProviderConfig(
                        name="mock-a", base_url="http://a.test/v1",
                        api_key_env="KEY_A", models=["m-a"], default_weight=60,
                    ),
                    ProviderConfig(
                        name="mock-b", base_url="http://b.test/v1",
                        api_key_env="KEY_B", models=["m-b"], default_weight=40,
                    ),
                ],
                task_routing={
                    "test_task": {"mock-a": 60, "mock-b": 40},
                },
            ),
        )
    router = LLMRouter(config, timeout_s=5)

    if providers is not None:
        iterator = iter([
            FakeResponse(content)
            for content in providers.get(list(providers.keys())[0], ["fallback"])
        ])

        def fake_try(cfg, prompt, max_tokens):
            try:
                resp = next(iterator)
                return resp.choices[0].message.content
            except StopIteration:
                return None

        router._try_provider = fake_try

    return router


class TestLLMRouter:

    async def test_ask_returns_empty_when_no_providers(self):
        """Router with empty provider list returns empty string."""
        config = Config(
            sites=[SiteConfig(name="t", start_url="http://x")],
            crawl=CrawlConfig(),
            output={"dir": "nodes"},
            llm=LLMConfig(),
        )
        router = LLMRouter(config)
        result = await router.ask("hi")
        assert result == ""

    async def test_ask_returns_text_on_first_success(self, monkeypatch):
        """When the first provider succeeds, return its text immediately."""
        monkeypatch.setattr(
            "src.llm_router.os.getenv",
            lambda key, default="": "some-key",
        )

        config = Config(
            sites=[SiteConfig(name="t", start_url="http://x")],
            crawl=CrawlConfig(),
            output={"dir": "nodes"},
            llm=LLMConfig(
                providers=[
                    ProviderConfig(name="p1", base_url="http://a/v1",
                                   api_key_env="KEY", models=["m"], default_weight=100),
                ],
                task_routing={"default": {"p1": 100}},
            ),
        )
        router = LLMRouter(config, timeout_s=5)

        async def fake_try(cfg, prompt, mt):
            return "ok-from-p1"

        router._try_provider = fake_try
        result = await router.ask("hi")
        assert result == "ok-from-p1"

    async def test_ask_falls_back_on_failure(self):
        """Both providers tried when first fails; second succeeds."""
        config = Config(
            sites=[SiteConfig(name="t", start_url="http://x")],
            crawl=CrawlConfig(),
            output={"dir": "nodes"},
            llm=LLMConfig(
                providers=[
                    ProviderConfig(name="p1", base_url="http://a/v1",
                                   api_key_env="K", models=["m"], default_weight=50),
                    ProviderConfig(name="p2", base_url="http://b/v1",
                                   api_key_env="K", models=["m"], default_weight=50),
                ],
                task_routing={"default": {"p1": 50, "p2": 50}},
            ),
        )
        router = LLMRouter(config, timeout_s=5)
        calls: list[str] = []

        async def fake_try(cfg, prompt, mt):
            calls.append(cfg.name)
            if cfg.name == "p1":
                return None  # p1 fails
            return "ok-from-p2"

        router._try_provider = fake_try
        result = await router.ask("hi")
        assert result == "ok-from-p2"

    async def test_ask_returns_empty_when_all_fail(self):
        """When every provider fails, return empty string (never raise)."""
        router = _make_router()
        async def always_fail(cfg, prompt, mt): return None
        router._try_provider = always_fail
        result = await router.ask("hi")
        assert result == ""

    # ── _response_text ──

    def test_response_text_normal(self):
        resp = FakeResponse("hello")
        text = LLMRouter._response_text(resp, is_reasoning=False)
        assert text == "hello"

    def test_response_text_reasoning_model(self):
        msg = FakeResponseMessage(content=None, reasoning="thinking... answer: 42")
        resp = type("R", (), {"choices": [type("C", (), {"message": msg})]})()
        text = LLMRouter._response_text(resp, is_reasoning=True)
        assert text == "thinking... answer: 42"

    def test_response_text_empty_when_both_none(self):
        msg = FakeResponseMessage(content=None, reasoning=None)
        resp = type("R", (), {"choices": [type("C", (), {"message": msg})]})()
        text = LLMRouter._response_text(resp, is_reasoning=False)
        assert text == ""

    def test_response_text_prefers_content_over_reasoning(self):
        msg = FakeResponseMessage(content="real answer", reasoning="thinking...")
        resp = type("R", (), {"choices": [type("C", (), {"message": msg})]})()
        text = LLMRouter._response_text(resp, is_reasoning=True)
        assert text == "real answer"

    # ── _parse_json ──

    def test_parse_json_valid(self):
        result = LLMRouter._parse_json('{"txt": ["a.txt"], "yaml": ["b.yaml"]}')
        assert result["txt"] == ["a.txt"]
        assert result["yaml"] == ["b.yaml"]

    def test_parse_json_with_fences(self):
        raw = '```json\n{"txt": ["a.txt"]}\n```'
        result = LLMRouter._parse_json(raw)
        assert result["txt"] == ["a.txt"]

    def test_parse_json_invalid_returns_empty(self):
        result = LLMRouter._parse_json("not json at all")
        assert result == {"txt": [], "yaml": [], "other": [], "inline": []}

    def test_parse_json_empty_string(self):
        result = LLMRouter._parse_json("")
        assert result == {"txt": [], "yaml": [], "other": [], "inline": []}

    # ── extract_links ──

    async def test_extract_links_calls_ask(self):
        """Ensure extract_links flows through ask()."""
        router = _make_router()
        called = False

        async def fake_ask(prompt, task_type="default", max_tokens=1024):
            nonlocal called
            called = True
            assert task_type == "extract_links"
            return '{"txt":["https://x.com/a.txt"],"yaml":[]}'

        router.ask = fake_ask
        result = await router.extract_links("some markdown")
        assert called
        assert result["txt"] == ["https://x.com/a.txt"]

    # ── generate_pattern ──

    async def test_generate_pattern_returns_none_on_empty(self):
        router = _make_router()
        async def empty_ask(p, task_type="default", max_tokens=256):
            return ""
        router.ask = empty_ask
        result = await router.generate_pattern(["http://x.com/a.yaml"], "<p>link</p>")
        assert result is None


# ═══════════════════════════════════════════════════════════════
# _extract_regex
# ═══════════════════════════════════════════════════════════════

class TestExtractRegex:

    def test_extracts_from_code_fence(self):
        text = "Here is the regex:\n```\nhttps://node\\.example\\.com/[^\\s]+\n```"
        assert LLMRouter._extract_regex(text) == r"https://node\.example\.com/[^\s]+"

    def test_extracts_from_code_fence_with_lang(self):
        text = "```regex\nhttps://x\\.com/[a-z]+\\.(txt|yaml)\n```"
        assert LLMRouter._extract_regex(text) == r"https://x\.com/[a-z]+\.(txt|yaml)"

    def test_extracts_from_analysis_line(self):
        """Handles reasoning model output with analysis text."""
        text = (
            "1. Analyze the Request:\n"
            "The user wants a regex matching these URLs.\n"
            "2. Pattern:\n"
            r"https://node\.example\.com/\d{4}/\d{2}/\d+-\d{8}\.(?:txt|yaml)"
        )
        result = LLMRouter._extract_regex(text)
        assert result is not None
        assert r"node\.example\.com" in result

    def test_extracts_from_last_line(self):
        text = "The regex is:\nhttps://x\\.com/[^\\s]+\\.(txt|yaml)\n"
        assert LLMRouter._extract_regex(text) == r"https://x\.com/[^\s]+\.(txt|yaml)"

    def test_returns_none_on_garbage(self):
        assert LLMRouter._extract_regex("I have no idea what regex to use") is None

    def test_extracts_regex_with_escaped_chars(self):
        text = "Consider the URL pattern...\nhttps://node\\.test\\.com/\\d+/file\\.(txt|yaml)"
        result = LLMRouter._extract_regex(text)
        assert result is not None
        assert r"node\.test\.com" in result
# ═══════════════════════════════════════════════════════════════

class TestConfigIntegration:

    def test_full_config_parses_three_providers(self, full_config):
        assert len(full_config.llm.providers) == 3
        names = [p.name for p in full_config.llm.providers]
        assert names == ["openrouter", "cerebras", "opencode"]

    def test_full_config_provider_fields(self, full_config):
        p = full_config.llm.providers[0]
        assert p.name == "openrouter"
        assert p.base_url == "https://openrouter.ai/api/v1"
        assert p.api_key_env == "OPENROUTER_API_KEY"
        assert p.models == ["openrouter/free"]
        assert p.is_reasoning_model is False
        assert p.default_weight == 50

    def test_cerebras_is_reasoning_model(self, full_config):
        p = full_config.llm.providers[1]
        assert p.name == "cerebras"
        assert p.is_reasoning_model is True

    def test_task_routing(self, full_config):
        assert full_config.llm.task_routing["extract_links"]["openrouter"] == 60
        assert full_config.llm.task_routing["extract_links"]["cerebras"] == 30
        assert full_config.llm.task_routing["generate_pattern"]["opencode"] == 0

    def test_no_llm_config_returns_empty(self, no_llm_config):
        assert no_llm_config.llm.providers == []
        assert no_llm_config.llm.task_routing == {}

    def test_router_from_full_config(self, full_config):
        router = LLMRouter(full_config)
        assert len(router._providers) == 3
        assert router._default_weights["openrouter"] == 50
        assert router._default_weights["cerebras"] == 30


# ═══════════════════════════════════════════════════════════════
# Verify no import from deleted src.llm
# ═══════════════════════════════════════════════════════════════

def test_no_old_llm_import():
    """Ensure src.llm was deleted and not referenced."""
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.llm")
