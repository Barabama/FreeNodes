#!/usr/bin/env python
"""LLM 供应商验证 — 连通性 + 中文提取 + JSON mode + 速率试探。

Provider: OpenRouter (primary), Cerebras (backup1), Opencode (backup2)
"""
import os, json, time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": os.getenv("OPENROUTER_API_KEY", ""),
        "models": [
            "openrouter/free",
            "qwen/qwen3-next-80b-a3b-instruct:free",
        ],
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "api_key": os.getenv("CEREBRAS_API_KEY", ""),
        "models": [
            "zai-glm-4.7",
            "gpt-oss-120b",
        ],
    },
    "opencode": {
        "base_url": "https://opencode.ai/zen/v1",
        "api_key": os.getenv("OPENCODE_API_KEY", ""),
        "models": [
            "deepseek-v4-flash-free",
            "qwen3.6-plus-free",
        ],
    },
}


def test_connectivity(name, cfg, model):
    """连通性 + 延迟."""
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=20)
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=5,
        )
        ms = round((time.time() - t0) * 1000)
        content = resp.choices[0].message.content
        return {"status": "PASS" if content else "EMPTY", "ms": ms, "actual": resp.model}
    except Exception as e:
        return {"status": "FAIL", "error": str(e)[:120]}


def test_extraction(name, cfg, model):
    """中文提取 — 模拟真实爬虫场景."""
    test_page = (
        "本期免费节点更新 2026-06-18\n"
        "clash订阅链接: https://node.freeclashnode.com/uploads/2026/06/0-20260618.yaml\n"
        "v2ray订阅链接: https://node.freeclashnode.com/uploads/2026/06/0-20260618.txt\n"
        "备用: https://node.freeclashnode.com/uploads/2026/06/1-20260618.txt\n"
    )
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=20)
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": f"提取所有 .txt 和 .yaml 结尾的URL，只返回JSON数组: {test_page}"}
            ],
            temperature=0.1,
            max_tokens=256,
        )
        ms = round((time.time() - t0) * 1000)
        content = resp.choices[0].message.content or ""
        try:
            json.loads(content)
            valid = True
        except json.JSONDecodeError:
            valid = False
        return {"status": "PASS" if valid else "BAD_JSON", "ms": ms, "raw": content[:120]}
    except Exception as e:
        return {"status": "FAIL", "error": str(e)[:120]}


def test_json_mode(name, cfg, model):
    """JSON mode 兼容性."""
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=20)
    results = {}
    for label, use_api_mode in [("api_json_mode", True), ("prompt_only", False)]:
        try:
            kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": '提取日期，返回JSON: 6月18日更新，2026年节点'}],
                "temperature": 0.1,
                "max_tokens": 100,
            }
            if use_api_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content or ""
            json.loads(content)
            results[label] = "OK"
        except Exception as e:
            results[label] = f"FAIL: {str(e)[:60]}"
    return results


def test_rate(name, cfg, model):
    """速率试探 — 连续发送看何时限流."""
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=10)
    ok = 0
    for i in range(10):
        try:
            client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": "hi"}], max_tokens=5
            )
            ok += 1
        except Exception:
            break
        time.sleep(0.3)
    return {"ok_before_429": ok, "total_tried": 10}


if __name__ == "__main__":
    print(f"{'PROVIDER':12s} {'MODEL':40s} {'CONNECT':8s} {'EXTRACT':8s} {'JSON_MD':8s} {'RATE':8s}")
    print("-" * 100)

    for name, cfg in PROVIDERS.items():
        if not cfg["api_key"] and name != "opencode":
            print(f"{name:12s} {'(no api key)':40s} SKIP")
            continue

        for model in cfg["models"]:
            c = test_connectivity(name, cfg, model)
            if c["status"] != "PASS":
                print(f"{name:12s} {model:40s} {c['status']:8s} - {c.get('error','')[:40]}")
                continue

            e = test_extraction(name, cfg, model)
            j = test_json_mode(name, cfg, model)
            r = test_rate(name, cfg, model)

            json_mode_str = j.get("api_json_mode", "?")[:8]
            rate_str = f"{r['ok_before_429']}/10"

            print(f"{name:12s} {model:40s} {c['status']:8s} {e['status']:8s} {json_mode_str:8s} {rate_str:8s}")

    print("\nDone.")
