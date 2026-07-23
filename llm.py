"""OpenRouter chat-completions client for the SaaSShorts text calls.

Replaces the direct google-genai calls in saasshorts.py (research / analyze /
scripts). Other features (clip pipeline, editor, thumbnails) still talk to
Gemini directly and are unaffected.

Retry semantics follow the hard-won rules from main.py's Gemini stage: an
LLM answering 200 with an empty body must be retried, not crash the job.
"""
import json
import os
import re
import time

import httpx

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_TEXT_MODEL = "google/gemini-3.1-flash-lite"

_BACKOFFS = (5, 10, 20)


class LLMError(RuntimeError):
    pass


def resolve_text_model(header_value: str | None = None) -> str:
    """Per-request model override (X-OR-Text-Model) → env → default."""
    return header_value or os.environ.get("OR_TEXT_MODEL") or DEFAULT_TEXT_MODEL


def _salvage_json(content: str):
    """Parse a JSON object/array out of an LLM reply.

    Mirrors the tolerant parsing saasshorts.py used for Gemini: strip
    markdown fences, then fall back to the outermost {...} or [...] slice.
    """
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Whichever bracket opens first wins — an array reply may contain objects.
    candidates = []
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end != -1 and end > start:
            candidates.append((start, text[start : end + 1]))
    if candidates:
        return json.loads(min(candidates)[1])
    raise json.JSONDecodeError("no JSON object/array found", text[:200], 0)


def chat_json(
    prompt: str,
    *,
    api_key: str,
    model: str,
    plugins: list | None = None,
    max_output_tokens: int | None = None,
    retries: int = 3,
    timeout: float = 300.0,
    transport: httpx.BaseTransport | None = None,
) -> tuple:
    """One JSON-producing chat call. Returns ``(data, meta)``.

    meta = {"annotations": [...], "cost": float} — annotations carry the web
    plugin's url_citation entries when ``plugins`` includes the web plugin.
    Raises LLMError after ``retries`` failed attempts (HTTP errors, empty
    bodies and unparseable replies all count as failures).
    """
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "usage": {"include": True},
    }
    if plugins:
        body["plugins"] = plugins
    if max_output_tokens:
        body["max_tokens"] = max_output_tokens

    last_err = None
    for attempt in range(retries):
        try:
            with httpx.Client(transport=transport, timeout=timeout) as client:
                resp = client.post(
                    OPENROUTER_CHAT_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=body,
                )
            if resp.status_code != 200:
                raise LLMError(f"openrouter {resp.status_code}: {resp.text[:500]}")
            payload = resp.json()
            message = payload["choices"][0]["message"]
            content = (message.get("content") or "").strip()
            if not content:
                raise LLMError("empty completion body")
            data = _salvage_json(content)
            usage = payload.get("usage") or {}
            meta = {
                "annotations": message.get("annotations") or [],
                "cost": float(usage.get("cost") or 0.0),
            }
            return data, meta
        except (httpx.HTTPError, LLMError, json.JSONDecodeError, KeyError, IndexError) as exc:
            last_err = exc
            if attempt < retries - 1:
                time.sleep(_BACKOFFS[min(attempt, len(_BACKOFFS) - 1)])
    raise LLMError(f"openrouter call failed after {retries} attempts: {last_err}")
