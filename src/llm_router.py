"""LLM Router — multi-provider weighted routing with fallback and health tracking.

Priority: weighted random (not sequential), task-aware, auto-recovery.

Provider chain:
  OpenRouter (weight 50) → Cerebras (weight 30) → Opencode (weight 20)
"""
import os
import re
import json
import random
import time
from openai import OpenAI
from dotenv import load_dotenv

from src.config import Config, ProviderConfig

load_dotenv()


class WeightedSelector:
    """Pick a provider by weighted random selection, excluding unhealthy ones."""

    @staticmethod
    def pick(weights: dict[str, int], is_healthy: callable, exclude: set[str] | None = None) -> str | None:
        """Select a provider from *weights* where *is_healthy(name)* returns True.

        Providers in *exclude* are skipped (already tried this round).
        Returns *None* when no candidate remains.
        """
        exclude = exclude or set()
        candidates = {
            name: w for name, w in weights.items()
            if is_healthy(name) and name not in exclude
        }
        if not candidates:
            return None

        total = sum(candidates.values())
        if total == 0:
            return None

        r = random.uniform(0, total)
        cumulative = 0
        for name, w in candidates.items():
            cumulative += w
            if r <= cumulative:
                return name
        return None


class HealthTracker:
    """Track provider health; disable after consecutive failures, auto-recover."""

    def __init__(self, max_failures: int = 5, cooldown_seconds: int = 1800):
        self.max_failures = max_failures
        self.cooldown_seconds = cooldown_seconds
        self._failures: dict[str, int] = {}
        self._disabled_until: dict[str, float] = {}

    def record_success(self, provider: str):
        self._failures[provider] = 0
        self._disabled_until.pop(provider, None)

    def record_failure(self, provider: str):
        self._failures[provider] = self._failures.get(provider, 0) + 1
        if self._failures[provider] >= self.max_failures:
            self._disabled_until[provider] = time.time() + self.cooldown_seconds

    def is_healthy(self, provider: str) -> bool:
        if provider not in self._disabled_until:
            return True
        if time.time() >= self._disabled_until[provider]:
            del self._disabled_until[provider]
            return True
        return False

    def health_report(self) -> dict[str, dict]:
        """Return a snapshot of current failure counts and health status."""
        return {
            name: {"failures": count, "healthy": self.is_healthy(name)}
            for name, count in self._failures.items()
        }


class LLMRouter:
    """Unified LLM interface with weighted routing, fallback, and health tracking.

    Usage:
        config = load_config()
        router = LLMRouter(config)
        text = router.ask("extract links", task_type="extract_links")
        links = router.extract_links(page.markdown)
    """

    def __init__(self, config: Config, timeout_s: int = 20):
        self._timeout_s = timeout_s
        self._health = HealthTracker()
        self._selector = WeightedSelector()

        # Build lookup: name -> ProviderConfig
        self._providers: dict[str, ProviderConfig] = {
            p.name: p for p in config.llm.providers
        }
        self._default_weights: dict[str, int] = {
            p.name: p.default_weight for p in config.llm.providers
        }
        self._task_routing: dict[str, dict[str, int]] = config.llm.task_routing

    # ── Public API ──

    def ask(self, prompt: str, task_type: str = "default", max_tokens: int = 1024) -> str:
        """Send *prompt* through weighted routing.

        Picks a healthy provider by weight, calls it, falls back on failure.
        Returns empty string when all providers fail (never raises).
        """
        weights = self._task_routing.get(task_type, self._default_weights)
        tried: set[str] = set()

        for _ in range(len(self._providers)):
            name = self._selector.pick(weights, self._health.is_healthy, tried)
            if name is None:
                break
            tried.add(name)
            provider = self._providers.get(name)
            if provider is None:
                continue

            result = self._try_provider(provider, prompt, max_tokens)
            if result is not None:
                self._health.record_success(name)
                return result
            self._health.record_failure(name)

        return ""

    def extract_links(self, markdown: str) -> dict[str, list[str]]:
        """Extract subscription links (.txt / .yaml URLs) from page markdown."""
        prompt = (
            "Extract all subscription links (URLs ending in .txt or .yaml) "
            "from the following web page content.\n"
            "Return JSON: {\"txt\": [\"url1\", ...], \"yaml\": [\"url1\", ...]}\n"
            "Return nothing except the JSON. Empty arrays if none found.\n\n"
            f"Content:\n{markdown[:8000]}"
        )
        text = self.ask(prompt, task_type="extract_links", max_tokens=1024)
        return self._parse_json(text)

    def generate_pattern(self, known_links: list[str], html: str) -> str | None:
        """Ask LLM to produce a regex for the site's known subscription links."""
        prompt = (
            f"The following subscription links were found on this page:\n"
            f"{chr(10).join(known_links[:10])}\n\n"
            "Observe the URL pattern and write a single Python regex that "
            "matches every one of them (and their future variants on the same site).\n"
            "Requirements:\n"
            "- Must be generic enough to match other dates on the same site\n"
            "- Must be precise: no navigation links, ads, or JS URLs\n"
            "- Return ONLY the regex, no quotes, no explanation\n\n"
            "Regex:"
        )
        text = self.ask(prompt, task_type="generate_pattern", max_tokens=256)
        if not text:
            return None
        pattern = text.strip()
        if "```" in pattern:
            pattern = re.sub(r"```\w*|```", "", pattern).strip()
        return pattern if pattern else None

    @staticmethod
    def verify_pattern(pattern: str, known_links: list[str], html: str) -> bool:
        """Three-layer verification: syntax, recall, precision."""
        # Layer 1: syntax
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return False

        # Layer 2: recall — pattern must cover all known links
        matches = compiled.findall(html)
        match_urls: set[str] = set()
        if isinstance(matches, list):
            for m in matches:
                if isinstance(m, tuple):
                    m = m[0]
                if isinstance(m, str):
                    match_urls.add(re.sub(r'[),;.\'"]+$', "", m))
        for link in known_links:
            clean = re.sub(r'[),;.\'"]+$', "", link)
            if clean not in match_urls:
                return False

        # Layer 3: precision — no more than 20% false positives
        false_count = 0
        for m in matches:
            if isinstance(m, tuple):
                m = m[0]
            if isinstance(m, str):
                if not m.startswith("http"):
                    false_count += 1
                elif any(n in m.lower() for n in ("javascript:", "#", "xmlrpc", "favicon")):
                    false_count += 1
        if matches and false_count / len(matches) > 0.2:
            return False

        return True

    # ── Internals ──

    def _try_provider(self, cfg: ProviderConfig, prompt: str, max_tokens: int) -> str | None:
        """Try all models for *cfg* until one returns content. Returns None on total failure."""
        api_key = os.getenv(cfg.api_key_env, "")
        if not api_key:
            return None
        client = OpenAI(base_url=cfg.base_url, api_key=api_key, timeout=self._timeout_s)
        for model in cfg.models:
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=max_tokens,
                )
                text = self._response_text(resp, cfg.is_reasoning_model)
                if text:
                    return text
            except Exception:
                continue
        return None

    @staticmethod
    def _response_text(resp, is_reasoning: bool) -> str:
        """Extract text from chat completion, handling reasoning models (Cerebras)."""
        msg = resp.choices[0].message
        if msg.content:
            return msg.content
        if is_reasoning and msg.reasoning:
            return msg.reasoning
        return ""

    @staticmethod
    def _parse_json(raw: str) -> dict[str, list[str]]:
        """Parse LLM JSON response. Strips markdown fences if present."""
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"txt": [], "yaml": []}
