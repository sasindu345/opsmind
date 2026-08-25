# OpsMind 🧠⚡

> Free & open-source AI platform-engineering and incident-triage engine.

OpsMind listens to your telemetry (logs, Prometheus metrics, deployment webhooks), filters the noise
locally with Drain3 clustering, runs root-cause analysis on a free-tier or fully local LLM, and delivers
actionable incident cards to Slack and your terminal — at zero infrastructure cost.

---

## ✨ Why OpsMind

| Problem | OpsMind's answer |
| --- | --- |
| Alert storms bury the real signal | Drain3 clusters repetitive log lines into templates (>80% fewer LLM tokens) |
| "What changed?" takes 20 minutes | GitOps correlation maps metric spikes to commit SHAs, PR authors and config diffs |
| LLM triage is expensive | Dual engine: local Ollama (`llama3:8b`) or Gemini free tier via LiteLLM |
| Post-mortems never get written | One click exports a blameless Markdown report into your repo |
| Remediation is manual | Whitelisted, dry-run-first runbooks (`kubectl rollout undo`, Docker restarts) |

---

## 🏗 Architecture

```text
[Events / Webhooks] ──> [Ingestion & Drain3 Parsing] ──> [Anomaly & Git Correlation]
                                                                   │
                                                                   ▼
[Slack / CLI UI]    <── [Runbook / Fix Action Engine] <── [LLM Root Cause Analysis]
```

**Data flow**

1. Logs, Prometheus alerts and GitHub/GitLab deploy events hit the FastAPI webhook endpoints.
2. Drain3 collapses raw log lines into pattern templates + extracted parameters.
3. A rolling-window Z-score/IQR detector flags CPU, memory and HTTP-500 anomalies.
4. The correlator matches anomaly windows against deployments within ±10 minutes.
5. LiteLLM asks Gemini or Ollama for a structured `RootCauseAnalysis` (enforced JSON schema).
6. Results render as Slack Block Kit cards and Rich terminal tables; actions run through the safe executor.
7. Resolved incidents are embedded into `sqlite-vec` so future alerts retrieve past fixes (RAG).

---

## 🚀 Quick Start

### 1. Prerequisites

* Python 3.11+
* Either [Ollama](https://ollama.com) (100% offline inference) **or** a free Google Gemini API key
* Optional: `ngrok` or a Cloudflare Tunnel to route webhooks to localhost

### 2. Installation

```bash
git clone https://github.com/your-org/opsmind.git
cd opsmind
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 3. Configure `.env`

```ini
LLM_PROVIDER="gemini"          # or "ollama"
GEMINI_API_KEY="your-free-gemini-key"
OLLAMA_MODEL="llama3:8b"
SLACK_BOT_TOKEN="xoxb-..."
SLACK_APP_TOKEN="xapp-..."
DATABASE_URL="sqlite:///./opsmind.db"
PROMETHEUS_URL="http://localhost:9090"
```

### 4. Run

```bash
# Backend API + Slack Socket Mode listener
uvicorn src.main:app --reload --port 8000

# Terminal triage
python -m src.cli.opsmind_cli triage --last 15m
```

### 5. Smoke test

```bash
curl -X POST http://localhost:8000/api/v1/analyze/logs \
  -H "Content-Type: application/json" \
  -d '{"service":"checkout","logs":["ERROR OOMKilled pod checkout-7d9","ERROR OOMKilled pod checkout-7f2"]}'
```

---

## 🧭 User Flow

| Step | You do | OpsMind does |
| --- | --- | --- |
| 1. Setup | `git clone` + configure `.env` | Boots FastAPI + Ollama/Gemini client |
| 2. Ingest | Point Prometheus & GitHub webhooks at it | Records health metrics and deployment events |
| 3. Trigger | App errors / memory spikes | Clusters logs via Drain3, computes metric Z-scores |
| 4. Triage | Read the Slack card | LLM posts root-cause hypothesis + action buttons |
| 5. Act | Click **Rollback** | Runs validated `kubectl rollout undo` or safe script |
| 6. Close | Click **Export Post-Mortem** | Writes `/reports/incident-YYYY-MM-DD.md` |

---

## 🔌 API Surface

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/analyze/logs` | Cluster raw logs, run LLM analysis, return `RootCauseAnalysis` + Markdown |
| `POST` | `/api/v1/webhooks/prometheus` | Alertmanager receiver |
| `POST` | `/api/v1/webhooks/github` | Deployment / push events (commit SHA, author, timestamp) |
| `GET`  | `/api/v1/incidents` | List recent incidents and their status |
| `GET`  | `/healthz` | Liveness probe |
| `GET`  | `/readyz` | Readiness probe — reports which subsystems are configured |

> Only `/healthz` and `/readyz` exist today (Phase 0). The remaining routes land in Phases 1–3 — see [PLAN.md](PLAN.md).

---

## 💸 Free-Tier Boundaries

* **LLM calls:** Gemini free tier (15 RPM) or unlimited local Ollama
* **Storage:** embedded SQLite + `sqlite-vec` — no cloud database fees
* **Tunneling:** Cloudflare Tunnel or ngrok free tier
* **Embeddings:** `all-MiniLM-L6-v2` running locally via `sentence-transformers`

---

## 📁 Project Structure

```text
opsmind/
├── .env.example
├── .gitignore
├── README.md
├── PLAN.md                      # Phase-by-phase development plan
├── LICENSE
├── pyproject.toml               # ruff + pytest configuration
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
├── config/
│   ├── settings.py              # Environment & application configuration
│   └── drain3.ini               # Drain3 log parser configuration
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI server entry point
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes_logs.py       # Log ingestion endpoints
│   │   ├── routes_metrics.py    # Metric ingestion & Prometheus webhooks
│   │   └── routes_github.py     # GitHub Actions / deployment webhooks
│   ├── core/
│   │   ├── __init__.py
│   │   ├── drain_filter.py      # Drain3 log clustering engine
│   │   ├── anomaly_detector.py  # Statistical Z-score / IQR calculation
│   │   └── correlator.py        # Correlation across logs, metrics & git diffs
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py            # LiteLLM client (Gemini / Ollama)
│   │   ├── prompts.py           # Structured prompt templates
│   │   └── schemas.py           # Pydantic models for structured outputs
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── vector_store.py      # sqlite-vec database client
│   │   └── embedder.py          # sentence-transformers embeddings
│   ├── chatops/
│   │   ├── __init__.py
│   │   ├── slack_app.py         # Slack-Bolt app & event listeners
│   │   └── block_builder.py     # Slack Block Kit JSON builder
│   ├── executor/
│   │   ├── __init__.py
│   │   ├── runner.py            # Async safe command runner
│   │   └── runbooks.py          # Whitelisted execution scripts (K8s / Docker)
│   └── cli/
│       ├── __init__.py
│       └── opsmind_cli.py       # Typer / Rich terminal CLI
├── templates/
│   └── post_mortem.md.jinja2    # Markdown report template
├── reports/                     # Generated post-mortems
└── tests/
    ├── test_health.py
    ├── test_drain.py
    ├── test_correlator.py
    └── test_llm_schemas.py
```

---

## 🛠 Tech Stack

* **Backend:** FastAPI, Pydantic v2, Uvicorn
* **Log pre-processing:** Drain3
* **LLM engine:** LiteLLM (Gemini free tier / Ollama Llama 3)
* **Metrics:** Prometheus HTTP API, NumPy
* **Incident memory:** SQLite + `sqlite-vec` + `sentence-transformers`
* **ChatOps & CLI:** Slack-Bolt (Socket Mode), Typer, Rich
* **Reporting:** Jinja2 Markdown templates

---

## 🗺 Roadmap

See [PLAN.md](PLAN.md) for the full phase-by-phase build plan.

| Phase | Focus | Deliverable |
| --- | --- | --- |
| 0 | Repository bootstrap | ✅ Runnable FastAPI skeleton with `/healthz`, settings, Docker |
| 1 | Core engine & log intelligence | `POST /api/v1/analyze/logs` returning structured RCA + post-mortem |
| 2 | Interactive ChatOps & CLI | Slack incident cards + `opsmind triage --last 15m` |
| 3 | GitOps & metric correlation | "CPU spiked 3 min after commit `a1b2c3d` by Dev X" |
| 4 | Incident memory (RAG) & safe remediation | Similar-incident retrieval + 1-click validated rollback |

---

## 🤝 Contributing

1. Fork and create a feature branch (`feat/<short-name>`).
2. Run `pytest` and `ruff check .` before opening a PR.
3. Keep new external dependencies free-tier friendly — no paid SaaS in the default path.

## 📄 License

MIT — see `LICENSE`.
