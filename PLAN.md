# OpsMind — Development Plan

Phase-by-phase build plan for the OpsMind AI incident-triage engine.
Each phase ends in a demoable deliverable; nothing later depends on a phase that has not shipped.

**Legend:** `[ ]` todo · `[~]` in progress · `[x]` done

---

## Phase 0 — Repository Bootstrap (Day 1)

*Goal: a runnable skeleton before any feature code.*

* [x] **0.1** `python -m venv .venv`, pin Python 3.11+, create `requirements.txt`
      (`fastapi`, `uvicorn[standard]`, `pydantic>=2`, `pydantic-settings`, `drain3`,
      `litellm`, `jinja2`, `numpy`, `httpx`, `typer`, `rich`, `slack-bolt`,
      `sqlite-vec`, `sentence-transformers`, `pytest`, `ruff`).
* [x] **0.2** Create the directory tree from the README's *Project Structure* section.
* [x] **0.3** `config/settings.py` — `pydantic-settings` `Settings` object reading `.env`
      (`LLM_PROVIDER`, `GEMINI_API_KEY`, `OLLAMA_MODEL`, `SLACK_*`, `PROMETHEUS_URL`, `DATABASE_URL`).
* [x] **0.4** `.env.example`, `.gitignore` (`.venv`, `*.db`, `reports/*.md`, `.env`), MIT `LICENSE`.
* [x] **0.5** `src/main.py` with `/healthz` + `Dockerfile` + `docker-compose.yml` (api + optional ollama service).

**Status:** ✅ Complete — `pytest` (2 passed) and `ruff check .` clean.

**Exit criteria:** `uvicorn src.main:app --reload` serves `GET /healthz → {"status":"ok"}`.

---

## Phase 1 — Core Engine & Log Intelligence (Week 1–2)

*Goal: FastAPI backbone, log parser, and LLM root-cause generator.*

* [ ] **1.1** Pydantic request models for log ingestion (`LogBatch`: service, environment, timestamp, `list[str]` lines).
* [ ] **1.2** `src/core/drain_filter.py` — Drain3 `TemplateMiner` with `FilePersistence`, configured by `config/drain3.ini`.
      Returns clusters: `template`, `count`, `sample_lines`, `extracted_params`.
* [ ] **1.3** `src/llm/client.py` — LiteLLM wrapper routing to `gemini/gemini-2.0-flash` or `ollama/llama3:8b`,
      with retry/backoff and a hard timeout. Free-tier rate limiting (15 RPM token bucket).
* [ ] **1.4** `src/llm/schemas.py` — `Severity` (enum), `SuggestedFix`, `RootCauseAnalysis`
      (summary, probable_cause, confidence 0–1, affected_services, evidence, fixes, severity).
      Enforce structured JSON output; validate and retry once on parse failure.
* [ ] **1.5** `src/llm/prompts.py` — system + user templates that take clustered templates, not raw logs.
* [ ] **1.6** `templates/post_mortem.md.jinja2` + generator writing `reports/incident-YYYY-MM-DD-<slug>.md`.
* [ ] **1.7** `src/api/routes_logs.py` — `POST /api/v1/analyze/logs` wiring: parse → cluster → LLM → report.
* [ ] **1.8** Tests: `tests/test_drain.py` (clustering collapses N similar lines to 1 template),
      `tests/test_llm_schemas.py` (schema validation, bad-JSON retry path with a mocked client).

**Deliverable 1:** `POST /api/v1/analyze/logs` accepts raw logs, clusters them, invokes the LLM,
and returns a structured JSON root-cause report plus the path to a generated Markdown post-mortem.

**Risks:** free-tier LLMs return malformed JSON → mitigate with schema retry + a deterministic fallback report.

---

## Phase 2 — Interactive ChatOps & Terminal CLI (Week 3–4)

*Goal: connect the Phase 1 reasoning engine to Slack and the terminal.*

* [ ] **2.1** `src/chatops/slack_app.py` — `slack-bolt` in Socket Mode (no public IP needed in dev),
      started as a background task from the FastAPI lifespan.
* [ ] **2.2** `src/chatops/block_builder.py` — `RootCauseAnalysis` → Block Kit card
      (severity colour, summary, evidence, buttons: `Ack`, `Explain`, `Rollback`, `Export Post-Mortem`).
* [ ] **2.3** Action handlers: `ack_incident`, `expand_details`, `generate_report`
      (`Rollback` stays disabled/no-op until Phase 4's validated executor exists).
* [ ] **2.4** `src/cli/opsmind_cli.py` — Typer app with `triage --last 15m`, `incidents`, `explain <id>`;
      Rich tables, spinners and colourised severity output.
* [ ] **2.5** Shared service layer so Slack and CLI call the *same* analysis functions as the HTTP route.
* [ ] **2.6** SQLite incident table (id, created_at, service, severity, status, rca_json, report_path).

**Deliverable 2:** a Slack bot posting interactive incident cards on incoming errors, and
`opsmind triage --last 15m` printing colourised root-cause breakdowns in the terminal.

**Risks:** Socket Mode reconnect loops → run the handler supervised with reconnect logging.

---

## Phase 3 — GitOps & Metric Correlation (Week 5–6)

*Goal: correlate root causes against live commits and Prometheus anomalies.*

* [ ] **3.1** `src/api/routes_github.py` — `POST /api/v1/webhooks/github`, HMAC signature verification,
      stores deployment timestamp, commit SHA, author, changed files, message.
* [ ] **3.2** `src/core/anomaly_detector.py` — rolling-window Z-score and IQR detectors in NumPy for
      CPU, memory and HTTP 5xx rate; configurable window and threshold.
* [ ] **3.3** Prometheus client (`httpx`) issuing PromQL `query_range` calls over the alert window.
* [ ] **3.4** `src/core/correlator.py` — match anomaly onsets to deployments within ±10 minutes,
      score candidates by time proximity + service/file overlap, return ranked suspects.
* [ ] **3.5** Extend prompts to carry commit log/diff summary + metric spike context alongside log templates.
* [ ] **3.6** `POST /api/v1/webhooks/prometheus` Alertmanager receiver that kicks off full triage.
* [ ] **3.7** Tests: `tests/test_correlator.py` (spike inside window matches, outside window does not,
      ties broken by changed-file overlap).

**Deliverable 3:** a unified triage engine that reports
*"CPU spiked to 98% 3 minutes after commit `a1b2c3d` by Developer X deployed configuration change Y."*

**Risks:** clock skew between Prometheus and git timestamps → normalise everything to UTC on ingest.

---

## Phase 4 — Incident Memory (RAG) & Safe Remediation (Week 7+)

*Goal: historical incident retrieval and guarded execution.*

* [ ] **4.1** `src/memory/vector_store.py` (sqlite-vec) + `src/memory/embedder.py`
      (`all-MiniLM-L6-v2`, 384-dim, lazy model load).
* [ ] **4.2** Auto-index resolved post-mortems as embeddings on incident closure.
* [ ] **4.3** RAG retrieval: on a new alert, fetch top-k similar past incidents and inject their
      resolutions into the prompt as "previously seen" context.
* [ ] **4.4** `src/executor/runner.py` + `runbooks.py` — command whitelist, argument validation,
      mandatory dry-run preview, explicit confirmation flag, full audit log of every execution.
* [ ] **4.5** Wire the Slack **Execute Rollback** button to the validated runner
      (`kubectl rollout undo`, `docker compose restart <svc>`), gated on an allowlist of Slack user IDs.
* [ ] **4.6** Tests for the executor: non-whitelisted command rejected, dry-run never shells out,
      confirmation required before execution.

**Deliverable 4:** an end-to-end triage platform that matches current incidents to past solutions
and allows 1-click execution of safe remediation commands.

**Risks:** command injection / accidental prod damage → whitelist by *command shape*, never
string-interpolate model output into a shell; `shell=False` argv lists only.

---

## Cross-Cutting Concerns

| Area | Approach |
| --- | --- |
| Config | Single `Settings` object; no `os.getenv` scattered through modules |
| Secrets | `.env` only, never committed; `.env.example` documents every key |
| Logging | `structlog`-style JSON logs with an incident id correlation field |
| Testing | `pytest` + mocked LLM client; no test may hit a live LLM or Prometheus |
| CI | GitHub Actions: `ruff check`, `pytest`, Docker build on every PR |
| Cost | Every default path must stay on free tier or local inference |

---

## Definition of Done (per phase)

1. Deliverable demoable end-to-end from a clean clone following only the README.
2. Tests for the phase pass; `ruff check .` is clean.
3. README updated with any new endpoint, env var or command.
4. No paid service required on the default path.
