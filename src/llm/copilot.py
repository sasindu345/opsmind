"""Conversational operations copilot.

Answers questions about monitored applications by calling read-only tools and
citing what they returned. When no LLM is configured, or the provider cannot do
tool calling, it falls back to a deterministic grounded mode built from the same
tools, matching how the triage pipeline degrades to heuristics.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from config.settings import Settings, get_settings
from src.llm.client import LLMClient, LLMError
from src.llm.tools import CopilotTools, ToolSpec

logger = logging.getLogger("opsmind.copilot")

COPILOT_SYSTEM_PROMPT = """You are OpsMind Copilot, assisting an engineer with a monitored estate.

You answer only from data returned by your tools. Call tools to gather evidence before concluding.

Rules:
- Never invent an application name, latency, commit SHA, incident id or log line. If a tool returns
  nothing, say the data is not available.
- Quote concrete numbers you retrieved, such as a p95 latency or an availability percentage.
- Be concise: a short, direct answer, then the evidence that supports it.
- You may recommend an allowlisted runbook by name, but you cannot execute anything. Say that an
  operator must review and approve any action.
- Prefer plain language over jargon. The reader may not be the person who built the system.
"""


@dataclass
class ToolCallRecord:
    """One tool invocation, surfaced to the UI as a breadcrumb."""

    name: str
    arguments: dict[str, Any]
    ok: bool = True


@dataclass
class CopilotAnswer:
    """The copilot's reply plus how it got there."""

    session_id: str
    answer: str
    tools_used: list[ToolCallRecord] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    degraded: bool = False
    model: str = ""


class SessionStore:
    """Bounded in-memory conversation history.

    Not persisted on purpose: answers are regenerated from live evidence, and
    nothing downstream reads past turns.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._sessions: dict[str, deque[dict[str, str]]] = {}
        self._touched: dict[str, float] = {}

    def _evict_expired(self) -> None:
        ttl = self.settings.copilot_session_ttl_seconds
        now = time.monotonic()
        for session_id in [sid for sid, seen in self._touched.items() if now - seen > ttl]:
            self._sessions.pop(session_id, None)
            self._touched.pop(session_id, None)

    def history(self, session_id: str) -> list[dict[str, str]]:
        self._evict_expired()
        return list(self._sessions.get(session_id, []))

    def append(self, session_id: str, role: str, content: str) -> None:
        self._evict_expired()
        turns = self.settings.copilot_max_history_turns * 2
        bucket = self._sessions.setdefault(session_id, deque(maxlen=turns))
        bucket.append({"role": role, "content": content})
        self._touched[session_id] = time.monotonic()


_SESSIONS: SessionStore | None = None


def get_session_store(settings: Settings | None = None) -> SessionStore:
    global _SESSIONS
    if _SESSIONS is None:
        _SESSIONS = SessionStore(settings)
    return _SESSIONS


def _coerce_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


async def _dispatch(spec: ToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
    allowed = set(spec.parameters.get("properties", {}))
    filtered = {key: value for key, value in arguments.items() if key in allowed}
    return await spec.handler(**filtered)


class Copilot:
    """Runs one question to an evidence-backed answer."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: LLMClient | None = None,
        tools: CopilotTools | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._tools = tools or CopilotTools(self.settings)
        self._catalog = self._tools.catalog()

    @property
    def client(self) -> LLMClient:
        if self._client is None:
            self._client = LLMClient(self.settings)
        return self._client

    async def ask(self, question: str, session_id: str | None = None) -> CopilotAnswer:
        """Answer a question, falling back to grounded mode without an LLM."""
        session = session_id or uuid.uuid4().hex
        store = get_session_store(self.settings)

        if self.settings.missing_llm_credentials() is not None:
            answer = await self._grounded_answer(question, session)
            store.append(session, "user", question)
            store.append(session, "assistant", answer.answer)
            return answer

        try:
            answer = await self._llm_answer(question, session, store.history(session))
        except (LLMError, Exception) as exc:  # noqa: BLE001 - provider errors vary
            logger.warning("copilot LLM path failed (%s), using grounded mode", exc)
            answer = await self._grounded_answer(question, session)

        store.append(session, "user", question)
        store.append(session, "assistant", answer.answer)
        return answer

    async def _llm_answer(
        self,
        question: str,
        session: str,
        history: list[dict[str, str]],
    ) -> CopilotAnswer:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": COPILOT_SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": question},
        ]
        schemas = [spec.to_openai_schema() for spec in self._catalog.values()]
        used: list[ToolCallRecord] = []
        citations: list[dict[str, Any]] = []

        for _ in range(self.settings.copilot_max_tool_iterations):
            message = await self.client.chat(messages, tools=schemas)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return CopilotAnswer(
                    session_id=session,
                    answer=(message.get("content") or "").strip(),
                    tools_used=used,
                    citations=citations,
                    model=self.client.model,
                )

            messages.append(message)
            for call in tool_calls:
                function = call.get("function", {}) or {}
                name = function.get("name", "")
                arguments = _coerce_arguments(function.get("arguments"))
                spec = self._catalog.get(name)

                # Every name is checked against the catalog before dispatch, so
                # a hallucinated tool can never reach arbitrary code.
                if spec is None:
                    logger.warning("copilot requested unknown tool %r", name)
                    used.append(
                        ToolCallRecord(name=name or "unknown", arguments=arguments, ok=False)
                    )
                    result: dict[str, Any] = {"error": f"No tool named '{name}'."}
                else:
                    try:
                        result = await _dispatch(spec, arguments)
                        used.append(ToolCallRecord(name=name, arguments=arguments))
                        citations.append({"tool": name, "arguments": arguments, "data": result})
                    except Exception as exc:  # noqa: BLE001 - tool failure must not abort
                        logger.exception("copilot tool %s failed", name)
                        used.append(ToolCallRecord(name=name, arguments=arguments, ok=False))
                        result = {"error": str(exc)}

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", name),
                        "name": name,
                        "content": json.dumps(result, default=str),
                    }
                )

        # Iteration cap reached: answer from what was gathered rather than looping.
        logger.info("copilot hit the tool iteration cap")
        final = await self.client.chat(messages, tools=None)
        return CopilotAnswer(
            session_id=session,
            answer=(final.get("content") or "").strip(),
            tools_used=used,
            citations=citations,
            model=self.client.model,
        )

    async def _grounded_answer(self, question: str, session: str) -> CopilotAnswer:
        """Deterministic evidence summary used when no LLM is available."""
        lowered = question.lower()
        used: list[ToolCallRecord] = []
        citations: list[dict[str, Any]] = []

        async def run(name: str, **arguments: Any) -> dict[str, Any]:
            spec = self._catalog[name]
            data = await _dispatch(spec, arguments)
            used.append(ToolCallRecord(name=name, arguments=arguments))
            citations.append({"tool": name, "arguments": arguments, "data": data})
            return data

        apps = await run("list_applications")
        records = apps.get("applications", [])
        target = next(
            (
                record
                for record in records
                if record["app_id"].lower() in lowered or record["name"].lower() in lowered
            ),
            None,
        )

        if target is None:
            unhealthy = [r for r in records if r["health_status"] != "healthy"]
            incidents = await run("list_incidents", limit=5)
            lines = [
                f"Monitoring {len(records)} application(s).",
                (
                    f"{len(unhealthy)} are not healthy: "
                    + ", ".join(f"{r['name']} ({r['health_status']})" for r in unhealthy)
                    if unhealthy
                    else "All monitored applications are currently healthy."
                ),
            ]
            open_incidents = incidents.get("incidents", [])
            if open_incidents:
                lines.append(f"{len(open_incidents)} recent incident(s):")
                lines += [
                    f"- {item['title']} ({item['severity']}, {item['status']})"
                    for item in open_incidents[:5]
                ]
            lines.append(
                "No language model is configured, so this is a direct data summary rather "
                "than an analysis. Name an application for detail about it."
            )
            return CopilotAnswer(
                session_id=session,
                answer="\n".join(lines),
                tools_used=used,
                citations=citations,
                degraded=True,
                model="grounded",
            )

        app_id = target["app_id"]
        health = await run("get_application_health", app_id=app_id)
        metrics = await run("get_metrics_rollup", app_id=app_id, hours=1)
        commits = await run("get_recent_commits", app_id=app_id, hours=24)
        incidents = await run("list_incidents", app_id=app_id, limit=3)

        lines = [
            f"{health.get('name', app_id)} is currently {health.get('health_status', 'unknown')}."
        ]
        if metrics.get("samples"):
            lines.append(
                f"Over the last hour: p95 response time {metrics['p95_latency_ms']}ms, "
                f"average {metrics['avg_latency_ms']}ms, availability "
                f"{metrics['availability_percent']}% across {metrics['samples']} checks "
                f"({metrics['failed_probes']} failed)."
            )
        else:
            lines.append("There are no health check samples in the last hour.")

        commit_list = commits.get("commits", [])
        if commit_list:
            newest = commit_list[0]
            sha = (newest.get("commit_sha") or "")[:7]
            lines.append(
                f"Most recent change: {sha} by {newest.get('author', 'unknown')} "
                f"- {newest.get('message', '')}"
            )
        else:
            lines.append("No commits were recorded for this application in the last 24 hours.")

        incident_list = incidents.get("incidents", [])
        if incident_list:
            lines.append("Recent incidents:")
            lines += [
                f"- {item['title']} ({item['severity']}, {item['status']})"
                for item in incident_list
            ]

        lines.append(
            "No language model is configured, so this is a direct data summary rather than "
            "an analysis."
        )
        return CopilotAnswer(
            session_id=session,
            answer="\n".join(lines),
            tools_used=used,
            citations=citations,
            degraded=True,
            model="grounded",
        )
