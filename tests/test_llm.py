"""OpenRouter client: parsing tolerance and retry behaviour.

Mirrors the Gemini lessons in test_gemini_retry.py: a 200 with an empty body
must be retried inside the loop, and fenced/prefixed JSON must still parse.
"""
import json

import httpx
import pytest

import llm


def _ok(content, cost=0.001, annotations=None):
    message = {"content": content}
    if annotations is not None:
        message["annotations"] = annotations
    return httpx.Response(200, json={
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": cost},
    })


def test_parses_clean_json_and_usage_cost():
    def handler(request):
        body = json.loads(request.content)
        assert body["usage"] == {"include": True}
        return _ok('{"a": 1}')

    data, meta = llm.chat_json("p", api_key="k", model="m",
                               transport=httpx.MockTransport(handler))
    assert data == {"a": 1}
    assert meta["cost"] == 0.001


def test_strips_fences_and_salvages_prefixed_json():
    def handler(request):
        return _ok('Sure! Here is the result:\n```json\n{"b": 2}\n```\nHope it helps.')

    data, _ = llm.chat_json("p", api_key="k", model="m",
                            transport=httpx.MockTransport(handler))
    assert data == {"b": 2}


def test_salvages_array_responses():
    def handler(request):
        return _ok('here you go [\n{"s": 1}\n]')

    data, _ = llm.chat_json("p", api_key="k", model="m",
                            transport=httpx.MockTransport(handler))
    assert data == [{"s": 1}]


def test_web_plugin_annotations_returned(monkeypatch):
    ann = [{"type": "url_citation",
            "url_citation": {"url": "https://g2.com/x", "title": "G2 review"}}]

    def handler(request):
        body = json.loads(request.content)
        assert body["plugins"] == [{"id": "web"}]
        return _ok('{"ok": true}', annotations=ann)

    data, meta = llm.chat_json("p", api_key="k", model="m",
                               plugins=[{"id": "web"}],
                               transport=httpx.MockTransport(handler))
    assert meta["annotations"] == ann


def test_empty_body_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return _ok("")
        return _ok('{"ok": true}')

    data, _ = llm.chat_json("p", api_key="k", model="m",
                            transport=httpx.MockTransport(handler))
    assert data == {"ok": True}
    assert calls["n"] == 3


def test_raises_after_exhausted_retries(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)

    def handler(request):
        return httpx.Response(503, json={"error": {"message": "overloaded"}})

    with pytest.raises(llm.LLMError, match="after 3 attempts"):
        llm.chat_json("p", api_key="k", model="m",
                      transport=httpx.MockTransport(handler))


def test_resolve_text_model_priority(monkeypatch):
    monkeypatch.delenv("OR_TEXT_MODEL", raising=False)
    assert llm.resolve_text_model(None) == llm.DEFAULT_TEXT_MODEL
    monkeypatch.setenv("OR_TEXT_MODEL", "env/model")
    assert llm.resolve_text_model(None) == "env/model"
    assert llm.resolve_text_model("hdr/model") == "hdr/model"
