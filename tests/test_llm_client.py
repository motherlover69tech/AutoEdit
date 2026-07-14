from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from autoedit.config import Settings
from autoedit.llm_client import LLMClient


def _async_client_returning(response: Mock):
    client = Mock()
    client.post = AsyncMock(return_value=response)
    context = Mock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return context, client


def test_chat_sends_non_thinking_schema_request_and_parses_json():
    response = Mock()
    response.json.return_value = {"message": {"content": '{"items": []}'}}
    schema = {
        "type": "object",
        "properties": {"items": {"type": "array"}},
        "required": ["items"],
        "additionalProperties": False,
    }
    context, transport = _async_client_returning(response)
    client = LLMClient(
        Settings(
            OLLAMA_BASE_URL="http://ollama.test:11434",
            LLM_MODEL="local-model",
        )
    )

    with patch("autoedit.llm_client.httpx.AsyncClient", return_value=context):
        result = asyncio.run(
            client.chat(
                "Use only source evidence",
                "Return items",
                format_json=True,
                json_schema=schema,
                think=False,
                keep_alive=0,
            )
        )

    assert result == {"items": []}
    response.raise_for_status.assert_called_once_with()
    transport.post.assert_awaited_once_with(
        "http://ollama.test:11434/api/chat",
        json={
            "model": "local-model",
            "messages": [
                {"role": "system", "content": "Use only source evidence"},
                {"role": "user", "content": "Return items"},
            ],
            "stream": False,
            "options": {"temperature": 0.1},
            "format": schema,
            "think": False,
            "keep_alive": 0,
        },
    )


def test_chat_rejects_thinking_trace_when_disabled():
    response = Mock()
    response.json.return_value = {
        "message": {"content": '{"items": []}', "thinking": "private reasoning"}
    }
    context, _transport = _async_client_returning(response)
    client = LLMClient(Settings(OLLAMA_BASE_URL="http://ollama.test/", LLM_MODEL="m"))

    with patch("autoedit.llm_client.httpx.AsyncClient", return_value=context):
        with pytest.raises(RuntimeError, match="thinking trace"):
            asyncio.run(client.chat("system", "hello", think=False))


def test_chat_omits_optional_runtime_controls_when_unspecified():
    response = Mock()
    response.json.return_value = {"message": {"content": "plain text"}}
    context, transport = _async_client_returning(response)
    client = LLMClient(
        Settings(OLLAMA_BASE_URL="http://ollama.test/", LLM_MODEL="m")
    )

    with patch("autoedit.llm_client.httpx.AsyncClient", return_value=context):
        result = asyncio.run(client.chat("system", "hello", format_json=False))

    assert result == {"text": "plain text"}
    payload = transport.post.await_args.kwargs["json"]
    assert payload == {
        "model": "m",
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
        ],
        "stream": False,
        "options": {"temperature": 0.1},
    }
