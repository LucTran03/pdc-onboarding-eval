"""Gọi Gemini trên Vertex AI của công ty. Không dùng key Gemini cá nhân (dữ liệu trẻ em)."""
from __future__ import annotations

import json
import os
import time

from . import config


class LLMError(RuntimeError):
    pass


_CLIENT = None


def _client():
    """Giữ một client cho cả tiến trình (client tạm bị thu hồi sẽ đóng kết nối giữa chừng)."""
    global _CLIENT
    if _CLIENT is None:
        os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
        if config.GCP_KEY_PATH:  # không có thì dùng Application Default Credentials của máy
            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", config.GCP_KEY_PATH)
        from google import genai  # import muộn để test không cần gói / credential

        _CLIENT = genai.Client(vertexai=True, project=config.GCP_PROJECT, location=config.GCP_LOCATION)
    return _CLIENT


def check_model(model: str) -> str:
    """Chỉ đọc metadata model (miễn phí) — kiểm org policy / quyền trước khi chạy."""
    info = _client().models.get(model=model)
    return f"{model}: OK ({getattr(info, 'name', '')}, input {getattr(info, 'input_token_limit', '?')} token)"


def count_tokens(model: str, system: str, user: str) -> int | None:
    try:
        res = _client().models.count_tokens(model=model, contents=system + "\n\n" + user)
        return int(res.total_tokens)
    except Exception:  # noqa: BLE001 — đếm token chỉ để cảnh báo, không chặn
        return None


def estimate_cost(model: str, usage: dict) -> float | None:
    price = config.PRICING.get(model)
    if not price:
        return None
    inp = usage.get("prompt_tokens") or 0
    out = (usage.get("output_tokens") or 0) + (usage.get("thinking_tokens") or 0)
    return round(inp / 1e6 * price["input"] + out / 1e6 * price["output"], 4)


def call(system: str, user: str, schema: dict, model: str = config.DEFAULT_MODEL,
         thinking_budget: int = config.DEFAULT_THINKING_BUDGET,
         max_output_tokens: int = config.DEFAULT_MAX_OUTPUT_TOKENS, retries: int = 3,
         temperature: float = 0.0, seed: int | None = None) -> dict:
    """Trả {'text', 'data', 'usage', 'model_version', 'latency_sec', 'finish_reason', ...}."""
    from google.genai import types

    client = _client()
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        seed=seed,
        response_mime_type="application/json",
        response_json_schema=schema,
        max_output_tokens=max_output_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
    )
    last_err = None
    for attempt in range(1, retries + 1):
        t0 = time.time()
        try:
            resp = client.models.generate_content(model=model, contents=user, config=cfg)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            msg = str(exc)
            transient = any(code in msg for code in ("429", "500", "502", "503", "504", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE"))
            if attempt < retries and transient:
                time.sleep(10 * attempt)
                continue
            raise LLMError(f"Vertex lỗi ({type(exc).__name__}): {msg[:500]}") from exc
        latency = round(time.time() - t0, 1)
        um = getattr(resp, "usage_metadata", None)
        usage = {
            "prompt_tokens": getattr(um, "prompt_token_count", None),
            "output_tokens": getattr(um, "candidates_token_count", None),
            "thinking_tokens": getattr(um, "thoughts_token_count", None),
            "total_tokens": getattr(um, "total_token_count", None),
        }
        finish = None
        if getattr(resp, "candidates", None):
            finish = str(getattr(resp.candidates[0], "finish_reason", None))
        text = resp.text or ""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            last_err = exc
            if attempt < retries and "MAX_TOKENS" not in str(finish):
                continue
            raise LLMError(f"Model không trả JSON hợp lệ (finish={finish}, {len(text)} ký tự)") from exc
        return {
            "text": text,
            "data": data,
            "usage": usage,
            "model": model,
            "model_version": getattr(resp, "model_version", None),
            "latency_sec": latency,
            "finish_reason": finish,
            "temperature": temperature,
            "seed": seed,
            "cost_usd_est": estimate_cost(model, usage),
        }
    raise LLMError(f"Hết {retries} lần thử: {last_err}")
