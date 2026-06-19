"""LLM 客户端 — 多供应商 fallback 链.

优先级: OpenRouter → Cerebras → Opencode
"""
import os
import re
import json
from dotenv import load_dotenv
from openai import OpenAI, APITimeoutError

load_dotenv()


class LLM:
    """多供应商 LLM 客户端，带 fallback 链.

    每个供应商可能包含多个模型（按序重试）。
    Cerebras zai-glm-4.7 是推理模型，输出在 reasoning 字段。
    OpenRouter 不支持 response_format，用纯 prompt 引导 JSON。
    """

    PROVIDERS: list[dict] = [
        {
            "name": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            "models": ["openrouter/free"],
            "supports_json_mode": False,   # openrouter/free 不支持 API 级 JSON mode
        },
        {
            "name": "cerebras",
            "base_url": "https://api.cerebras.ai/v1",
            "api_key_env": "CEREBRAS_API_KEY",
            "models": ["zai-glm-4.7", "gpt-oss-120b"],
            "is_reasoning_model": True,    # zai-glm-4.7 输出在 reasoning 字段
        },
        {
            "name": "opencode",
            "base_url": "https://opencode.ai/zen/v1",
            "api_key_env": "OPENCODE_API_KEY",
            "models": ["deepseek-v4-flash-free", "qwen3.6-plus-free"],
        },
    ]

    def __init__(self, timeout_s: int = 20):
        self.timeout_s = timeout_s
        # Default client = OpenRouter (for backward compat / direct use)
        p0 = self.PROVIDERS[0]
        self.client = OpenAI(
            base_url=p0["base_url"],
            api_key=os.getenv(p0["api_key_env"], ""),
            timeout=timeout_s,
        )

    # ── 核心调用（fallback 链） ──

    def _try_provider(self, provider: dict, prompt: str, max_tokens: int = 1024) -> str | None:
        """尝试单个供应商的所有模型，失败返回 None（不抛异常）。"""
        api_key = os.getenv(provider["api_key_env"], "")
        if not api_key:
            return None

        for model in provider["models"]:
            try:
                client = OpenAI(
                    base_url=provider["base_url"],
                    api_key=api_key,
                    timeout=self.timeout_s,
                )
                kwargs: dict = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": max_tokens,
                }
                resp = client.chat.completions.create(**kwargs)
                text = self._get_content(resp, provider.get("is_reasoning_model", False))
                if text:
                    return text
            except Exception:
                continue  # 试下一个模型/供应商

        return None

    def _get_content(self, resp, is_reasoning: bool = False) -> str:
        """从响应中提取文本，兼容推理模型（content=None 但 reasoning 有值）。"""
        msg = resp.choices[0].message
        if msg.content:
            return msg.content
        if is_reasoning and msg.reasoning:
            return msg.reasoning
        return ""

    def ask(self, prompt: str, max_tokens: int = 1024) -> str:
        """依次尝试所有供应商，全部失败才抛异常。"""
        for provider in self.PROVIDERS:
            result = self._try_provider(provider, prompt, max_tokens)
            if result is not None:
                return result
        raise RuntimeError(f"All LLM providers failed. prompt={prompt[:60]}...")

    # ── Level 0: 纯提取 ──

    def extract_links(self, markdown: str) -> dict[str, list[str]]:
        """从 markdown 中提取 .txt / .yaml 订阅链接.

        Returns: {"txt": [...], "yaml": [...]}
        """
        prompt = (
            "从以下网页内容提取所有订阅链接（仅 .txt 和 .yaml 结尾的URL）。\n"
            "返回 JSON: {\"txt\": [\"url1\",...], \"yaml\": [\"url1\",...]}\n"
            "不返回任何 JSON 以外的内容。没有找到就返回空数组。\n\n"
            f"内容:\n{markdown[:8000]}"
        )

        try:
            text = self.ask(prompt, max_tokens=1024)
            return self._parse_json(text)
        except RuntimeError:
            return {"txt": [], "yaml": []}

    # ── Level 1: 正则生成 ──

    def generate_pattern(self, known_links: list[str], html: str) -> str | None:
        """让 LLM 根据已知链接生成提取正则，供校验.

        Returns: regex 字符串，失败返回 None
        """
        prompt = (
            f"以下是从网页中找到的订阅链接：\n"
            f"{chr(10).join(known_links[:10])}\n\n"
            "请观察这些 URL 的共同规律，写一个 Python 正则表达式来匹配它们。\n"
            "要求：\n"
            "- 正则必须足够通用，能匹配同一网站其他日期的类似链接\n"
            "- 正则必须足够精确，不会匹配到页面中的广告、导航、JS 等无关内容\n"
            "- 只返回正则表达式本身，不要用引号包裹，不要解释\n\n"
            "正则:"
        )

        try:
            text = self.ask(prompt, max_tokens=256)
        except RuntimeError:
            return None

        if not text:
            return None
        pattern = text.strip()
        if "```" in pattern:
            pattern = re.sub(r"```\w*|```", "", pattern).strip()
        return pattern if pattern else None

    # ── 三层校验 ──

    @staticmethod
    def verify_pattern(pattern: str, known_links: list[str], html: str) -> bool:
        """三层校验正则表达式是否可靠。"""
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return False

        matches = compiled.findall(html)
        match_urls: set[str] = set()
        if isinstance(matches, list):
            for m in matches:
                if isinstance(m, tuple):
                    m = m[0]
                if isinstance(m, str):
                    match_urls.add(re.sub(r'[),;.\'"]+$', '', m))
        for link in known_links:
            clean = re.sub(r'[),;.\'"]+$', '', link)
            if clean not in match_urls:
                return False

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

    # ── 内部方法 ──

    def _parse_json(self, raw: str) -> dict[str, list[str]]:
        """从 LLM 响应中解析 JSON。"""
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"txt": [], "yaml": []}
