import json

import pytest
from pydantic import ValidationError

from config.settings import LLMProvider, Settings
from src.llm.client import LLMClient, LLMError, _extract_json, heuristic_analysis
from src.llm.schemas import RootCauseAnalysis, Severity

VALID_ANALYSIS = {
    "title": "Checkout pods OOMKilled",
    "summary": "Checkout pods exceeded their memory limit repeatedly.",
    "probable_cause": "Memory limit of 512Mi is below the new working set.",
    "confidence": 0.82,
    "severity": "high",
    "affected_services": ["checkout"],
    "evidence": ["ERROR OOMKilled pod <*> memory limit exceeded"],
    "suggested_fixes": [
        {
            "title": "Raise the memory limit",
            "description": "Bump the limit to 1Gi and observe.",
            "command": "kubectl set resources deploy/checkout --limits=memory=1Gi",
            "risk": "medium",
        }
    ],
}


def _settings() -> Settings:
    return Settings(llm_provider=LLMProvider.GEMINI, gemini_api_key="test-key", llm_max_rpm=1000)


class FakeCompletion:
    """Stands in for litellm.acompletion, replaying scripted responses."""

    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    async def __call__(self, messages, **kwargs):
        self.calls.append(messages)
        content = self.responses.pop(0) if self.responses else "{}"
        if isinstance(content, Exception):
            raise content

        class _Message:
            def __init__(self, c):
                self.content = c

        class _Choice:
            def __init__(self, c):
                self.message = _Message(c)

        class _Response:
            def __init__(self, c):
                self.choices = [_Choice(c)]

        return _Response(content)


def test_schema_accepts_valid_payload():
    analysis = RootCauseAnalysis.model_validate(VALID_ANALYSIS)
    assert analysis.severity is Severity.HIGH
    assert analysis.suggested_fixes[0].risk is Severity.MEDIUM


def test_confidence_must_be_a_probability():
    with pytest.raises(ValidationError):
        RootCauseAnalysis.model_validate({**VALID_ANALYSIS, "confidence": 1.7})


def test_unknown_severity_is_rejected():
    with pytest.raises(ValidationError):
        RootCauseAnalysis.model_validate({**VALID_ANALYSIS, "severity": "apocalyptic"})


def test_extract_json_strips_markdown_fences():
    raw = f"Here you go:\n```json\n{json.dumps(VALID_ANALYSIS)}\n```\nHope that helps!"
    assert RootCauseAnalysis.model_validate_json(_extract_json(raw)).confidence == 0.82


@pytest.mark.asyncio
async def test_client_returns_validated_analysis(monkeypatch):
    fake = FakeCompletion(json.dumps(VALID_ANALYSIS))
    monkeypatch.setattr("src.llm.client.litellm.acompletion", fake)
    analysis = await LLMClient(_settings()).analyze("prompt")
    assert analysis.title == "Checkout pods OOMKilled"
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_client_repairs_malformed_json_once(monkeypatch):
    fake = FakeCompletion("not json at all", json.dumps(VALID_ANALYSIS))
    monkeypatch.setattr("src.llm.client.litellm.acompletion", fake)
    analysis = await LLMClient(_settings()).analyze("prompt")
    assert analysis.confidence == 0.82
    assert len(fake.calls) == 2, "expected exactly one repair attempt"


@pytest.mark.asyncio
async def test_client_raises_after_failed_repair(monkeypatch):
    fake = FakeCompletion("garbage", "still garbage")
    monkeypatch.setattr("src.llm.client.litellm.acompletion", fake)
    with pytest.raises(LLMError):
        await LLMClient(_settings()).analyze("prompt")


@pytest.mark.asyncio
async def test_missing_api_key_is_reported_without_calling_the_model():
    settings = Settings(llm_provider=LLMProvider.GEMINI, gemini_api_key="")
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        await LLMClient(settings).analyze("prompt")


def test_heuristic_fallback_prefers_error_clusters():
    clusters = [
        {"template": "INFO heartbeat", "occurrences": 900, "level": "INFO", "sample": ""},
        {"template": "ERROR OOMKilled", "occurrences": 4, "level": "ERROR", "sample": ""},
    ]
    analysis = heuristic_analysis(clusters, "checkout")
    assert "OOMKilled" in analysis.probable_cause
    assert analysis.confidence < 0.4
