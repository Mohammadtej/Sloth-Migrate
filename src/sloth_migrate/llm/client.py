import re
import textwrap
from typing import Any
import httpx

from sloth_migrate.config import settings
from sloth_migrate.telemetry.sentry import trace_span


class GemmaClient:
    """Universal client for Gemma models (Google AI Studio, Ollama, vLLM)."""

    def __init__(self) -> None:
        self.base_url = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model
        self.api_key = settings.llm_api_key
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def generate_fix(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Sends code context and traceback to Gemma and returns the extracted clean code."""
        endpoint = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
        }

        with trace_span(
            name=f"Gemma Chat: {self.model}",
            op="ai.chat_completions",
            data={
                "ai.model_id": self.model,
                "ai.temperature": settings.llm_temperature,
                "ai.max_tokens": settings.llm_max_tokens,
            },
        ) as span:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(endpoint, headers=self.headers, json=payload)
                response.raise_for_status()
                data = response.json()
                raw_text = data["choices"][0]["message"]["content"].strip()

                if span and "usage" in data:
                    span.set_data("ai.total_tokens", data["usage"].get("total_tokens"))
                    span.set_data("ai.prompt_tokens", data["usage"].get("prompt_tokens"))
                    span.set_data("ai.completion_tokens", data["usage"].get("completion_tokens"))

        return self._extract_code_block(raw_text)

    def _extract_code_block(self, raw_response: str) -> str:
        code_match = re.search(r"```(?:python)?\s*\n(.*?)```", raw_response, re.DOTALL)
        extracted = code_match.group(1) if code_match else raw_response
        return textwrap.dedent(extracted).strip() + "\n"


gemma_client = GemmaClient()