"""LiteLLM client for Gemini (free tier) and Ollama (local / self-hosted).

Provider choice is pure configuration: ``LLM_PROVIDER=gemini`` today,
``LLM_PROVIDER=ollama`` once inference runs on our own server. Nothing outside
this module knows which one is active.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque

import litellm
from pydantic import ValidationError

from config.settings import LLMProvider, Settings, get_settings
from src.llm.prompts import REPAIR_PROMPT, SYSTEM_PROMPT
from src.llm.schemas import RootCauseAnalysis

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True

_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMError(RuntimeError):
    """The model could not produce a valid analysis."""


class RateLimiter:
    """Sliding-window limiter protecting the free-tier RPM budget."""

    def __init__(self, max_per_minute: int) -> None:
        self._max = max(1, max_per_minute)
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60:
                    self._calls.popleft()
                if len(self._calls) < self._max:
                    self._calls.append(now)
                    return
                wait = 60 - (now - self._calls[0])
                logger.info("free-tier rate limit reached — waiting %.1fs", wait)
                await asyncio.sleep(wait)


def _extract_json(raw: str) -> str:
    """Strip markdown fences and surrounding prose from a model response."""
    text = raw.strip()
    if match := _FENCE_PATTERN.search(text):
        text = match.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]
    return text


class LLMClient:
    """Asks the configured model for a validated ``RootCauseAnalysis``."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._limiter = RateLimiter(self.settings.llm_max_rpm)

    @property
    def model(self) -> str:
        return self.settings.model_name

    def _completion_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "model": self.model,
            "temperature": 0.2,
            "timeout": self.settings.llm_timeout_seconds,
            "response_format": {"type": "json_object"},
        }
        if self.settings.llm_provider is LLMProvider.GEMINI:
            kwargs["api_key"] = self.settings.gemini_api_key
        else:
            kwargs["api_base"] = self.settings.ollama_base_url
        return kwargs

    async def _call(self, messages: list[dict[str, str]]) -> str:
        await self._limiter.acquire()
        response = await litellm.acompletion(messages=messages, **self._completion_kwargs())
        return response.choices[0].message.content or ""

    async def analyze(self, user_prompt: str) -> RootCauseAnalysis:
        """Run the analysis, repairing one malformed response before giving up.

        Free-tier models regularly emit fenced or truncated JSON, so a single
        schema-feedback retry is the difference between a usable endpoint and a
        flaky one.
        """
        if reason := self.settings.missing_llm_credentials():
            raise LLMError(reason)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            raw = await self._call(messages)
        except Exception as exc:  # noqa: BLE001 - provider errors vary wildly
            raise LLMError(f"{self.model} request failed: {exc}") from exc

        try:
            return RootCauseAnalysis.model_validate_json(_extract_json(raw))
        except (ValidationError, ValueError) as first_error:
            logger.warning("invalid analysis JSON from %s — retrying once", self.model)
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": REPAIR_PROMPT.format(error=str(first_error)[:1500])},
            ]
            try:
                repaired = await self._call(messages)
                return RootCauseAnalysis.model_validate_json(_extract_json(repaired))
            except Exception as exc:  # noqa: BLE001
                raise LLMError(f"{self.model} returned unusable JSON: {exc}") from exc

    async def health(self) -> dict[str, object]:
        """Cheap connectivity probe used by ``/readyz`` style checks."""
        if reason := self.settings.missing_llm_credentials():
            return {"ok": False, "model": self.model, "error": reason}
        try:
            await self._limiter.acquire()
            await litellm.acompletion(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
                timeout=15,
                **(
                    {"api_key": self.settings.gemini_api_key}
                    if self.settings.llm_provider is LLMProvider.GEMINI
                    else {"api_base": self.settings.ollama_base_url}
                ),
            )
            return {"ok": True, "model": self.model}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "model": self.model, "error": str(exc)[:200]}


def heuristic_analysis(clusters: list[dict[str, object]], service: str) -> RootCauseAnalysis:
    """Deterministic fallback when the LLM is unavailable.

    Keeps the endpoint useful (and the demo alive) without a model: the noisiest
    high-severity cluster becomes the probable cause, at low confidence.
    """
    from src.llm.schemas import Severity, SuggestedFix

    ranked = [c for c in clusters if str(c.get("level")) in {"ERROR", "CRITICAL", "FATAL"}]
    top = (ranked or clusters or [{}])[0]
    template = str(top.get("template", "no log patterns found"))
    occurrences = int(top.get("occurrences", 0) or 0)

    return RootCauseAnalysis(
        title=f"Unreviewed error pattern in {service}",
        summary=(
            f"LLM analysis was unavailable, so this report is heuristic. The dominant "
            f"pattern occurred {occurrences} times in {service}."
        ),
        probable_cause=f"Repeated log pattern: {template}",
        confidence=0.15,
        severity=Severity.HIGH if ranked else Severity.LOW,
        affected_services=[service],
        evidence=[str(c.get("template", "")) for c in clusters[:5]],
        suggested_fixes=[
            SuggestedFix(
                title="Review the dominant log pattern manually",
                description="No model was reachable. Inspect the clustered templates above.",
                risk=Severity.LOW,
            )
        ],
    )
