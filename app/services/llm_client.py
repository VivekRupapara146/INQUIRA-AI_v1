"""
Provider-agnostic LLM client.

Why this exists: agent nodes should call `llm.generate_structured(...)` and
never know whether Gemini or OpenAI is underneath. This is the interface that
keeps agents decoupled from tool/provider implementation details (a pitfall
the assessment brief explicitly calls out under "Tight Coupling").
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


def _is_retryable(exc: BaseException) -> bool:
    """
    Retry on rate limits (429) and transient server errors (5xx) -- these
    are the failure classes that genuinely resolve themselves on retry.
    Don't retry on things like invalid API keys or malformed requests (4xx
    other than 429), since retrying those just wastes the quota further.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return status in (429, 500, 502, 503, 504)


_llm_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)


class LLMClient:
    def __init__(self):
        settings = get_settings()
        self.provider = settings.llm_provider

        if self.provider == "gemini":
            from google import genai

            self._client = genai.Client(api_key=settings.gemini_api_key)
            self._model_name = settings.gemini_model
        elif self.provider == "openai":
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
            self._model_name = settings.openai_model
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    async def generate_structured(self, prompt: str, schema: type[T]) -> T:
        """
        Ask the LLM to produce output conforming to `schema`, and return a
        validated instance. Raises pydantic.ValidationError if the model's
        output doesn't fit -- callers should catch and retry/log, never
        silently accept malformed output.
        """
        if self.provider == "gemini":
            return await self._generate_gemini(prompt, schema)
        return await self._generate_openai(prompt, schema)

    async def generate_text(self, prompt: str) -> str:
        """Free-form generation, used for the final synthesis/report prose."""
        if self.provider == "gemini":
            response = await self._call_gemini_raw(prompt)
            return response.text
        response = await self._call_openai_raw(
            [{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content

    # -- provider-specific structured output -------------------------------- #

    @_llm_retry
    async def _call_gemini_raw(self, prompt: str, config=None):
        return await self._client.aio.models.generate_content(
            model=self._model_name, contents=prompt, config=config
        )

    @_llm_retry
    async def _call_openai_raw(self, messages, **kwargs):
        return await self._client.chat.completions.create(
            model=self._model_name, messages=messages, **kwargs
        )

    async def _generate_gemini(self, prompt: str, schema: type[T]) -> T:
        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        )
        response = await self._call_gemini_raw(prompt, config=config)
        return schema.model_validate_json(response.text)

    async def _generate_openai(self, prompt: str, schema: type[T]) -> T:
        response = await self._call_openai_raw(
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return schema.model_validate_json(response.choices[0].message.content)
