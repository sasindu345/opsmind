"""Per-provider LLM credential validation.

``missing_llm_credentials`` previously validated only the Gemini branch, so
``/readyz`` reported Bedrock and Ollama as configured when they were not.
"""

from __future__ import annotations

from config.settings import Settings


def test_gemini_requires_an_api_key():
    assert Settings(llm_provider="gemini", gemini_api_key="").missing_llm_credentials() is not None
    assert Settings(llm_provider="gemini", gemini_api_key="k").missing_llm_credentials() is None


def test_ollama_requires_a_base_url_and_model():
    assert Settings(llm_provider="ollama").missing_llm_credentials() is None
    assert Settings(llm_provider="ollama", ollama_base_url="").missing_llm_credentials() is not None
    assert Settings(llm_provider="ollama", ollama_model="").missing_llm_credentials() is not None


def test_bedrock_requires_a_model_id():
    reason = Settings(llm_provider="bedrock", bedrock_model_id="").missing_llm_credentials()
    assert reason is not None
    assert "BEDROCK_MODEL_ID" in reason


def test_bedrock_requires_a_region():
    reason = Settings(llm_provider="bedrock", aws_region="").missing_llm_credentials()
    assert reason is not None
    assert "AWS_REGION" in reason


def test_bedrock_reports_unresolvable_credentials(monkeypatch):
    """A configured model is not enough; Bedrock also needs resolvable credentials."""
    import boto3

    monkeypatch.setattr(boto3.Session, "get_credentials", lambda self: None)
    reason = Settings(llm_provider="bedrock").missing_llm_credentials()
    assert reason is not None
    assert "credentials" in reason.lower()


def test_bedrock_passes_when_credentials_resolve(monkeypatch):
    import boto3

    monkeypatch.setattr(boto3.Session, "get_credentials", lambda self: object())
    assert Settings(llm_provider="bedrock").missing_llm_credentials() is None


def test_auth_required_tracks_the_api_key():
    assert Settings().auth_required is False
    assert Settings(api_key="secret").auth_required is True


def test_is_aws_tracks_deployment_mode():
    assert Settings(deployment_mode="local").is_aws is False
    assert Settings(deployment_mode="aws").is_aws is True
