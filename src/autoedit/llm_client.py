from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from autoedit.config import Settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Client for calling Ollama LLM API."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.base_url = self.settings.ollama_base_url.rstrip("/")
        self.model = self.settings.llm_model
        # Long read timeout for large prompts, but fail fast if Ollama is
        # unreachable so callers hit their deterministic fallbacks in
        # seconds instead of blocking the pipeline for 2 minutes per call.
        self.timeout = httpx.Timeout(120.0, connect=5.0)

    def _build_messages(self, system: str, user: str) -> list[dict[str, str]]:
        """Build messages array for Ollama chat API."""
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    async def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.1,
        format_json: bool = True,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
        think: bool | None = None,
        keep_alive: int | str | None = None,
    ) -> dict[str, Any]:
        """
        Call Ollama /api/chat endpoint.

        Returns parsed JSON if format_json=True, otherwise raw text.
        """
        messages = self._build_messages(system, user)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        if json_schema is not None:
            payload["format"] = json_schema
        elif format_json:
            payload["format"] = "json"
        if think is not None:
            payload["think"] = think
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                message = data.get("message", {})
                content = message.get("content", "")
                if think is False and (
                    str(message.get("thinking", "")).strip()
                    or "<think" in content.lower()
                    or "</think>" in content.lower()
                ):
                    raise RuntimeError("LLM returned a thinking trace in non-thinking mode")
                if format_json:
                    return json.loads(content)
                return {"text": content}
            except httpx.HTTPStatusError as e:
                logger.error(f"Ollama API error: {e.response.status_code} - {e.response.text}")
                raise RuntimeError(f"LLM API error: {e.response.status_code}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM JSON response: {e}")
                raise RuntimeError(f"LLM returned invalid JSON: {e}")
            except Exception as e:
                logger.error(f"LLM request failed: {e}")
                raise RuntimeError(f"LLM request failed: {e}")

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.1,
        format_json: bool = True,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """
        Call Ollama /api/generate endpoint (legacy, single prompt).
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        if format_json:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("response", "")
                if format_json:
                    return json.loads(content)
                return {"text": content}
            except httpx.HTTPStatusError as e:
                logger.error(f"Ollama API error: {e.response.status_code} - {e.response.text}")
                raise RuntimeError(f"LLM API error: {e.response.status_code}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM JSON response: {e}")
                raise RuntimeError(f"LLM returned invalid JSON: {e}")
            except Exception as e:
                logger.error(f"LLM request failed: {e}")
                raise RuntimeError(f"LLM request failed: {e}")

    async def health_check(self) -> bool:
        """Check if Ollama is reachable and model is available."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                data = response.json()
                models = [m["name"] for m in data.get("models", [])]
                return self.model in models or any(self.model in m for m in models)
        except Exception as e:
            logger.warning(f"LLM health check failed: {e}")
            return False


# Global client instance (lazy initialization)
_llm_client: LLMClient | None = None


def get_llm_client(settings: Settings | None = None) -> LLMClient:
    """Get or create the global LLM client."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient(settings)
    return _llm_client


def reset_llm_client() -> None:
    """Reset the global client (useful for testing)."""
    global _llm_client
    _llm_client = None