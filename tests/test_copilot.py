"""The operations copilot.

The safety-critical property is that the copilot can only read. It may name a
runbook for an operator to review, but no tool it can call executes anything.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from config.settings import Settings, get_settings
from src.infrastructure.interfaces import ApplicationRecord, HealthProbeSnapshot
from src.llm.copilot import Copilot, SessionStore, _coerce_arguments
from src.llm.tools import CopilotTools, percentile
from src.main import app as fastapi_app


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'copilot.db'}")
    get_settings.cache_clear()
    created = Settings(database_url=f"sqlite:///{tmp_path / 'copilot.db'}")
    yield created
    get_settings.cache_clear()


async def _seed(settings: Settings) -> None:
    from src.infrastructure.factory import get_application_repository

    repo = get_application_repository(settings)
    await repo.save_application(
        ApplicationRecord(
            app_id="checkout-api",
            name="Checkout API",
            environment="production",
            health_url="https://checkout.example/healthz",
            health_status="degraded",
            current_latency_ms=1240.0,
            uptime_24h_percent=97.5,
        )
    )
    now = datetime.now(UTC)
    for index, latency in enumerate([150.0, 180.0, 1200.0, 1400.0, 1500.0]):
        await repo.save_probe_snapshot(
            HealthProbeSnapshot(
                probe_id=f"p-{index}",
                app_id="checkout-api",
                timestamp=now - timedelta(minutes=5 - index),
                http_status=200 if latency < 1000 else 503,
                latency_ms=latency,
                is_success=latency < 1000,
            )
        )


# --- tools ------------------------------------------------------------------


def test_percentile_is_shared_by_route_and_tool():
    """The dashboard and an AI answer must never disagree about the same data.

    These were two implementations (ceil-based and round-based) that diverged on
    most sample sizes, so the route now delegates to the shared helper.
    """
    from src.api.routes_metrics import _compute_p95

    assert percentile([], 0.95) == 0.0
    assert percentile([10.0], 0.95) == 10.0
    assert percentile([float(n) for n in range(1, 101)], 0.95) == 95.0

    for size in range(1, 120):
        data = [float((n * 37) % 1000) for n in range(size)]
        assert _compute_p95(data) == percentile(data, 0.95), size


@pytest.mark.asyncio
async def test_tools_report_real_health_and_metrics(settings):
    await _seed(settings)
    tools = CopilotTools(settings)

    health = await tools.get_application_health("checkout-api")
    assert health["health_status"] == "degraded"
    assert health["current_latency_ms"] == 1240.0

    rollup = await tools.get_metrics_rollup("checkout-api", hours=1)
    assert rollup["samples"] == 5
    assert rollup["failed_probes"] == 3
    assert rollup["p95_latency_ms"] > 1000


@pytest.mark.asyncio
async def test_unknown_application_returns_an_error_not_an_exception(settings):
    result = await CopilotTools(settings).get_application_health("ghost")
    assert "error" in result


@pytest.mark.asyncio
async def test_metrics_rollup_handles_an_empty_window(settings):
    await _seed(settings)
    result = await CopilotTools(settings).get_metrics_rollup("ghost", hours=1)
    assert result["samples"] == 0


def test_tool_catalog_is_strictly_read_only(settings):
    """No tool may reach the executor; remediation stays behind human approval."""
    catalog = CopilotTools(settings).catalog()
    assert catalog

    banned = ("execute", "approve", "remediate", "run_", "delete", "restart", "scale")
    for name in catalog:
        assert not any(token in name for token in banned), name

    import src.llm.tools as tools_module

    source = open(tools_module.__file__, encoding="utf-8").read()
    # A tool catalog that imports the executor is one refactor away from danger.
    assert "src.executor" not in source
    assert "subprocess" not in source


def test_every_tool_schema_is_well_formed(settings):
    for name, spec in CopilotTools(settings).catalog().items():
        schema = spec.to_openai_schema()
        assert schema["function"]["name"] == name
        assert schema["function"]["description"]
        assert schema["function"]["parameters"]["type"] == "object"


# --- argument coercion ------------------------------------------------------


def test_arguments_accept_dicts_json_and_garbage():
    assert _coerce_arguments({"app_id": "a"}) == {"app_id": "a"}
    assert _coerce_arguments('{"app_id": "a"}') == {"app_id": "a"}
    assert _coerce_arguments("not json") == {}
    assert _coerce_arguments(None) == {}
    assert _coerce_arguments("[1,2]") == {}


# --- grounded fallback ------------------------------------------------------


@pytest.mark.asyncio
async def test_grounded_mode_answers_without_an_llm(settings, monkeypatch):
    """With no API key the copilot must still answer from real data."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    await _seed(settings)

    answer = await Copilot(
        settings=Settings(database_url=settings.database_url, gemini_api_key="")
    ).ask("Why is checkout-api slow?")

    assert answer.degraded is True
    assert answer.model == "grounded"
    assert "Checkout API" in answer.answer
    # Must cite the real numbers rather than describing them vaguely.
    assert "97" in answer.answer or "p95" in answer.answer.lower()
    assert any(record.name == "get_metrics_rollup" for record in answer.tools_used)
    assert answer.citations


@pytest.mark.asyncio
async def test_grounded_mode_summarises_the_estate_when_no_app_is_named(settings):
    await _seed(settings)
    answer = await Copilot(
        settings=Settings(database_url=settings.database_url, gemini_api_key="")
    ).ask("Is everything healthy?")

    assert answer.degraded is True
    assert "application" in answer.answer.lower()
    assert any(record.name == "list_applications" for record in answer.tools_used)


# --- LLM tool-calling loop --------------------------------------------------


class _FakeClient:
    """Stands in for LLMClient, scripting a sequence of assistant messages."""

    model = "fake/model"

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls: list[dict] = []

    async def chat(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        return self._replies.pop(0)


def _tool_call(name, arguments):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": f"call-{name}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


@pytest.mark.asyncio
async def test_llm_path_dispatches_tools_then_answers(settings):
    await _seed(settings)
    client = _FakeClient(
        [
            _tool_call("get_application_health", {"app_id": "checkout-api"}),
            {"role": "assistant", "content": "Checkout API is degraded at 1240ms."},
        ]
    )
    copilot = Copilot(
        settings=Settings(database_url=settings.database_url, gemini_api_key="k"),
        client=client,
    )

    answer = await copilot.ask("How is checkout-api?")
    assert answer.degraded is False
    assert answer.answer == "Checkout API is degraded at 1240ms."
    assert [r.name for r in answer.tools_used] == ["get_application_health"]
    assert answer.citations[0]["tool"] == "get_application_health"
    # The tool result must be fed back to the model.
    assert any(m.get("role") == "tool" for m in client.calls[1]["messages"])


@pytest.mark.asyncio
async def test_hallucinated_tool_name_is_rejected(settings):
    """An unknown name must never reach dispatch."""
    await _seed(settings)
    client = _FakeClient(
        [
            _tool_call("execute_arbitrary_command", {"cmd": "rm -rf /"}),
            {"role": "assistant", "content": "I cannot do that."},
        ]
    )
    copilot = Copilot(
        settings=Settings(database_url=settings.database_url, gemini_api_key="k"),
        client=client,
    )

    answer = await copilot.ask("Delete everything")
    assert answer.tools_used[0].ok is False
    tool_message = next(m for m in client.calls[1]["messages"] if m.get("role") == "tool")
    assert "No tool named" in tool_message["content"]


@pytest.mark.asyncio
async def test_unknown_arguments_are_filtered_before_dispatch(settings):
    await _seed(settings)
    client = _FakeClient(
        [
            _tool_call(
                "get_application_health",
                {"app_id": "checkout-api", "sneaky_kwarg": "boom"},
            ),
            {"role": "assistant", "content": "Fine."},
        ]
    )
    copilot = Copilot(
        settings=Settings(database_url=settings.database_url, gemini_api_key="k"),
        client=client,
    )
    answer = await copilot.ask("status?")
    assert answer.tools_used[0].ok is True


@pytest.mark.asyncio
async def test_tool_iteration_cap_is_enforced(settings):
    """A looping model must be cut off rather than calling tools forever."""
    await _seed(settings)
    replies = [_tool_call("list_applications", {}) for _ in range(3)]
    replies.append({"role": "assistant", "content": "Summary from what I gathered."})
    client = _FakeClient(replies)
    copilot = Copilot(
        settings=Settings(
            database_url=settings.database_url,
            gemini_api_key="k",
            copilot_max_tool_iterations=3,
        ),
        client=client,
    )

    answer = await copilot.ask("loop please")
    assert answer.answer == "Summary from what I gathered."
    assert len(answer.tools_used) == 3


@pytest.mark.asyncio
async def test_provider_failure_falls_back_to_grounded_mode(settings):
    await _seed(settings)

    class _Broken:
        model = "broken"

        async def chat(self, messages, tools=None):
            raise RuntimeError("provider does not support tool calling")

    copilot = Copilot(
        settings=Settings(database_url=settings.database_url, gemini_api_key="k"),
        client=_Broken(),
    )
    answer = await copilot.ask("Why is checkout-api slow?")
    assert answer.degraded is True
    assert answer.model == "grounded"


# --- sessions ---------------------------------------------------------------


def test_session_history_is_bounded():
    store = SessionStore(Settings(copilot_max_history_turns=2))
    for index in range(10):
        store.append("s1", "user", f"q{index}")
    assert len(store.history("s1")) <= 4


def test_sessions_are_isolated():
    store = SessionStore(Settings())
    store.append("a", "user", "question a")
    store.append("b", "user", "question b")
    assert store.history("a") != store.history("b")


# --- HTTP -------------------------------------------------------------------


def test_chat_endpoint_returns_an_answer_and_breadcrumbs(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(fastapi_app) as client:
            resp = client.post("/api/v1/copilot/chat", json={"question": "Is everything healthy?"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"]
        assert body["session_id"]
        assert body["degraded"] is True
        assert isinstance(body["tools_used"], list)
    finally:
        get_settings.cache_clear()


def test_chat_endpoint_rejects_an_empty_question():
    with TestClient(fastapi_app) as client:
        assert client.post("/api/v1/copilot/chat", json={"question": ""}).status_code == 422


def test_suggestions_are_served_so_the_ui_need_not_hardcode_them():
    with TestClient(fastapi_app) as client:
        body = client.get("/api/v1/copilot/suggestions").json()
    assert isinstance(body, list)
    assert len(body) >= 3
