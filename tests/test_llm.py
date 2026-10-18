"""Tests for the LLM client layer (ported alongside the Week 8 code).

Seam: public client behavior only. Scripted and mock-transport stand-ins are
used; no test touches a real network.
"""

import json

import httpx
import pytest
from pydantic import BaseModel

from riskservice.llm import (
    AgentOutputError,
    LLMClient,
    LLMResponse,
    OllamaClient,
    ScriptedClient,
    UsageRecordingClient,
    complete_parsed,
    parse_json_model,
    strip_json_fences,
    strip_think,
)


class _FakeLLM(LLMClient):
    """Scripted stand-in returning queued replies; records prompts."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, system: str, user: str) -> LLMResponse:
        self.prompts.append(system + "\n" + user)
        return LLMResponse(
            text=self.replies.pop(0), input_tokens=10, output_tokens=5, model="fake"
        )


class _Box(BaseModel):
    value: int


def test_scripted_client_routes_by_first_matching_marker():
    client = ScriptedClient({"risk scoring agent": "a-reply", "other": "b-reply"})
    reply = client.complete("You are the risk scoring agent.", "case data")
    assert reply.text == "a-reply"
    assert reply.model == "scripted"
    assert reply.input_tokens == 120


def test_scripted_client_without_matching_marker_raises_key_error():
    client = ScriptedClient({"risk scoring agent": "a-reply"})
    with pytest.raises(KeyError):
        client.complete("You are the recommendation agent.", "case data")


def test_usage_recording_client_records_drains_and_clears():
    inner = ScriptedClient({"k": "reply"})
    recording = UsageRecordingClient(inner)
    assert recording.drain() == []
    recording.complete("k", "x")
    recording.complete("k", "y")
    assert len(recording.drain()) == 2
    assert recording.drain() == []
    recording.complete("k", "z")
    recording.clear()
    assert recording.drain() == []


def test_strip_json_fences_removes_fences_and_handles_empty():
    assert strip_json_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_json_fences("```\nplain\n```") == "plain"
    assert strip_json_fences("   ") == ""
    assert strip_json_fences('{"a": 1}') == '{"a": 1}'


def test_parse_json_model_repairs_one_invalid_reply():
    good = json.dumps({"value": 7})
    llm = _FakeLLM([good])
    result = parse_json_model(llm, "sys", "user", "not json at all", _Box)
    assert result.value == 7
    # the only LLM call is the repair: it repeats the user text and the error
    assert "validation error was" in llm.prompts[0].lower()


def test_parse_json_model_raises_after_failed_repair():
    llm = _FakeLLM(["still not json"])
    with pytest.raises(AgentOutputError):
        parse_json_model(llm, "sys", "user", "not json at all", _Box)


def test_complete_parsed_happy_path():
    llm = _FakeLLM([json.dumps({"value": 3})])
    result = complete_parsed(llm, "sys", "user", _Box)
    assert result.value == 3


def test_strip_think_removes_blocks_and_stray_closer():
    assert strip_think("<think>hidden</think>answer") == "answer"
    assert strip_think("a<think>x</think>b<think>y</think>c") == "abc"
    assert strip_think("</think>trailing") == "trailing"
    assert strip_think("clean") == "clean"


def _ollama_mock_transport(handler) -> OllamaClient:
    return OllamaClient(
        host="http://mock", model="fake:1b", transport=httpx.MockTransport(handler)
    )


def test_ollama_client_complete_maps_reply_and_tokens():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "fake:1b"
        assert payload["think"] is False
        assert payload["messages"][0]["role"] == "system"
        return httpx.Response(
            200,
            json={
                "message": {"content": "<think>x</think>{\"score\": 1}"},
                "prompt_eval_count": 21,
                "eval_count": 7,
                "model": "fake:1b",
            },
        )

    client = _ollama_mock_transport(handler)
    reply = client.complete("sys prompt", "user prompt")
    assert reply.text == '{"score": 1}'
    assert reply.input_tokens == 21
    assert reply.output_tokens == 7
    assert reply.model == "fake:1b"


def test_ollama_client_complete_falls_back_to_configured_model_name():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"message": {"content": "ok"}, "prompt_eval_count": 1, "eval_count": 1}
        )

    reply = _ollama_mock_transport(handler).complete("s", "u")
    assert reply.model == "fake:1b"


def test_ollama_client_health_true_on_200_and_false_on_transport_error():
    ok = _ollama_mock_transport(lambda request: httpx.Response(200, json={"models": []}))
    assert ok.health() is True

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    down = _ollama_mock_transport(boom)
    assert down.health() is False


def test_ollama_client_resolves_host_and_model_from_env(monkeypatch):
    monkeypatch.delenv("RISKSERVICE_OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("RISKSERVICE_MODEL", raising=False)
    fallback = OllamaClient()
    assert fallback.host == "http://127.0.0.1:11434"
    assert fallback.model == "qwen3:8b"

    monkeypatch.setenv("RISKSERVICE_OLLAMA_HOST", "http://from-riskservice-env:9999")
    monkeypatch.setenv("OLLAMA_HOST", "http://from-ollama-env:9998")
    monkeypatch.setenv("RISKSERVICE_MODEL", "from-env:0b")
    preferred = OllamaClient()
    assert preferred.host == "http://from-riskservice-env:9999"
    assert preferred.model == "from-env:0b"

    monkeypatch.delenv("RISKSERVICE_OLLAMA_HOST")
    monkeypatch.delenv("RISKSERVICE_MODEL")
    falls_back = OllamaClient()
    assert falls_back.host == "http://from-ollama-env:9998"
    assert falls_back.model == "qwen3:8b"
