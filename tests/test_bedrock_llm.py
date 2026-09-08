import json

import pytest

from config.settings import LLMProvider, Settings
from src.llm.client import LLMClient
from src.llm.schemas import Severity
from tests.test_llm_schemas import VALID_ANALYSIS, FakeCompletion


def test_bedrock_model_name_and_kwargs():
    settings = Settings(
        llm_provider=LLMProvider.BEDROCK,
        aws_region="us-west-2",
        bedrock_model_id="anthropic.claude-3-5-sonnet-20240620-v1:0",
    )
    client = LLMClient(settings=settings)

    assert client.model == "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0"
    kwargs = client._completion_kwargs()
    assert kwargs["model"] == "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0"
    assert kwargs["aws_region_name"] == "us-west-2"
    assert kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_bedrock_client_analyze_success(monkeypatch):
    settings = Settings(
        llm_provider=LLMProvider.BEDROCK,
        aws_region="us-east-1",
        bedrock_model_id="amazon.nova-micro-v1:0",
    )
    client = LLMClient(settings=settings)

    monkeypatch.setattr(
        "src.llm.client.litellm.acompletion",
        FakeCompletion(json.dumps(VALID_ANALYSIS)),
    )

    analysis = await client.analyze("dummy user prompt")
    assert analysis.title == "Checkout pods OOMKilled"
    assert analysis.severity == Severity.HIGH
    assert analysis.confidence == 0.82
    assert len(analysis.suggested_fixes) == 1
