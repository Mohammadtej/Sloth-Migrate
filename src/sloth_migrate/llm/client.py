import re
from typing import Any
import httpx
from sloth_migrate.config import settings
import textwrap


class GemmaClient:
    """Universal client for Gemma models (Google AI Studio, Ollama, vLLM, or DO Droplet)."""

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

        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(endpoint, headers=self.headers, json=payload)
            response.raise_for_status()
            data = response.json()
            raw_text = data["choices"][0]["message"]["content"].strip()

        return self._extract_code_block(raw_text)

def _extract_code_block(self, raw_response: str) -> str:
    """Extracts code enclosed in triple backticks and removes extraneous outer indentation."""
    code_match = re.search(r"```(?:python)?\s*\n(.*?)```", raw_response, re.DOTALL)
    extracted = code_match.group(1) if code_match else raw_response
    # Removes any universal leading whitespace added by markdown rendering
    return textwrap.dedent(extracted).strip() + "\n"


gemma_client = GemmaClient()