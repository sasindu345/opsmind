# OpsMind — Development Plan: AWS-Native & Local-First AIOps Platform

OpsMind is an open-source, free/low-cost AI platform-engineering and incident-triage engine.
This plan defines the phase-by-phase roadmap to evolve OpsMind into a production-oriented, AWS-native AIOps platform while preserving 100% zero-AWS local development.

**Legend:** `[ ]` todo · `[~]` in progress · `[x]` done

---

## Architectural Modes

```
Local Mode (Zero-AWS)
Prometheus / Webhooks → FastAPI → SQLite + sqlite-vec → Ollama / Gemini → Slack / CLI

AWS Mode (Cloud-Native)
Telemetry / Webhooks → EventBridge → SQS → Incident Worker → (Drain3 + Anomaly + GitOps)
  → Amazon Bedrock → Structured RCA → DynamoDB (Metadata) + S3 (Artifacts) → Slack / CLI / Safe Runbooks
```

---

## Phase 0 — Repository Bootstrap & Baseline ✅

*Goal: a runnable skeleton and baseline test suite.*

* [x] **0.1** Environment setup (`.venv`, Python 3.11+, `requirements.txt`).
* [x] **0.2** Directory layout & project structure.
* [x] **0.3** `config/settings.py` — `pydantic-settings` `Settings` object reading `.env`.
* [x] **0.4** `.env.example`, `.gitignore`, MIT `LICENSE`.
* [x] **0.5** `src/main.py` with `/healthz` + `Dockerfile` + `docker-compose.yml`.

**Status:** ✅ Complete — 20 tests passing, `ruff check .` clean.

---

## Phase 1 — Core Engine: Anomaly Detection, GitOps Correlation & RCA ✅

*Goal: finish statistical anomaly detection, multi-source correlation, and structured LLM triage.*

* [x] **1.1** `src/core/anomaly_detector.py` — Rolling-window Z-score and Interquartile Range (IQR) detectors in NumPy for CPU, memory, latency, and HTTP 5xx rate.
* [x] **1.2** `src/core/correlator.py` — Multi-source correlation matching anomaly onsets to deployments/commits within configurable time windows. Clearly separates:
      - **Observed Evidence** (deterministic telemetry, log patterns, commit SHAs)
      - **Inferred Correlation** (statistical confidence & time proximity scores)
      - **LLM Hypothesis** (AI-suggested probable causes clearly demarcated)
* [x] **1.3** `src/llm/schemas.py` & `src/llm/prompts.py` — Extend structured contracts to carry metric anomalies, commit logs, and multi-source evidence.
* [x] **1.4** `src/core/pipeline.py` — Unified triage engine accepting logs, metrics, and deployment metadata.
* [x] **1.5** Unit tests: `tests/test_anomaly_detector.py`, `tests/test_correlator.py`, `tests/test_pipeline.py`.

**Status:** ✅ Complete — 24 tests passing, `ruff check .` clean. Deterministic anomaly detection and GitOps correlation engine feeding structured context to the LLM.

---

## Phase 2 — Asynchronous SQS & Worker Pipeline ✅

*Goal: asynchronous incident processing with durability, retries, and dead-letter queues.*

* [x] **2.1** `src/core/worker.py` — Asynchronous incident worker supporting SQS and Local In-Memory Queue.
* [x] **2.2** Visibility timeout management and exponential backoff retry handling.
* [x] **2.3** Dead-Letter Queue (DLQ) support for poison-pill isolation.
* [x] **2.4** Idempotency checks via message deduplication IDs and incident fingerprint hashing.
* [x] **2.5** Fast webhook acknowledgment (<50ms) returning HTTP 202 Accepted via `POST /api/v1/analyze/logs/async`.
* [x] **2.6** Structured JSON logging with correlation/request IDs throughout worker processing.
* [x] **2.7** Tests: `tests/test_worker_queue.py` (message lifecycle, retries, DLQ dispatch, idempotency).

**Status:** ✅ Complete — 30 tests passing, `ruff check .` clean. High-throughput async worker decoupling ingestion from heavy LLM/clustering analysis.

---

## Phase 3 — Telemetry Ingestion: EventBridge, CloudWatch & Webhooks ✅

*Goal: cloud-native event routing and observability alongside local Prometheus webhooks.*

* [x] **3.1** `src/api/routes_webhooks.py`:
      - `POST /api/v1/webhooks/prometheus` (Prometheus Alertmanager format)
      - `POST /api/v1/webhooks/github` (HMAC signature verification for push/deployment events)
      - `POST /api/v1/webhooks/cloudwatch` (CloudWatch Alarm & EventBridge envelope)
* [x] **3.2** EventBridge schema parser for CloudWatch alarms, GitHub deployment events, and app incidents.
* [x] **3.3** CloudWatch Metrics emission: `opsmind.incidents.detected`, `opsmind.incidents.resolved`, `opsmind.llm.requests`, `opsmind.llm.failures`, `opsmind.queue.processing_time`, `opsmind.anomaly.detected`.
* [x] **3.4** Sanitized logging (zero secrets/tokens/sensitive payloads).
* [x] **3.5** Tests: `tests/test_webhooks.py` (HMAC validation, payload transformations, metric recording).

**Status:** ✅ Complete — 35 tests passing, `ruff check .` clean. Multi-channel ingestion from GitHub, Prometheus, CloudWatch, and EventBridge.

---

## Phase 4 — Provider Abstraction: Bedrock, DynamoDB, S3 & Local Fallbacks ✅

*Goal: clean separation between local development storage and AWS cloud storage.*

* [x] **4.1** `src/infrastructure/interfaces.py`:
      - `EventPublisher`, `IncidentRepository`, `ArtifactStorage`, `MetricsProvider`, `SecretManager`.
* [x] **4.2** AWS implementations (`src/infrastructure/aws/`):
      - `BedrockProvider` via LiteLLM (`bedrock/<model_id>`) in `src/llm/client.py`
      - `DynamoDBIncidentRepository` (metadata, status, timeline, confidence)
      - `S3ArtifactStorage` (encrypted buckets for `incidents/`, `logs/`, `postmortems/`, `evidence/`)
      - `AWSEventPublisher`
      - `AWSSecretManager`
* [x] **4.3** Local implementations (`src/infrastructure/local/`):
      - `SQLiteIncidentRepository`
      - `LocalArtifactStorage` (`reports/` and `artifacts/`)
      - `LocalEventPublisher`
      - `LocalSecretManager`
* [x] **4.4** `src/infrastructure/factory.py` — Dependency injection factory resolving providers based on `DEPLOYMENT_MODE` (`local` vs `aws`).
* [x] **4.5** Tests: `tests/test_infrastructure.py` and `tests/test_bedrock_llm.py` (with local & mocked AWS clients).

**Status:** ✅ Complete — 43 tests passing, `ruff check .` clean. Dual-mode storage and LLM routing (Bedrock/Gemini/Ollama, DynamoDB/SQLite, S3/Local FS).

---

## Phase 5 — Interactive ChatOps, Terminal CLI & Incident Lifecycle

*Goal: rich human interfaces and complete incident lifecycle API.*

* [ ] **5.1** `src/chatops/block_builder.py` — Slack Block Kit interactive message cards (severity badges, root-cause breakdown, evidence accordion, action buttons: `Ack`, `Explain`, `Remediate`, `Post-Mortem`).
* [ ] **5.2** `src/chatops/slack_app.py` — Slack Bolt in Socket Mode (or HTTP webhook) with role/user authorization gating for remediation actions.
* [ ] **5.3** `src/cli/opsmind_cli.py` — Typer + Rich CLI with subcommands:
      - `opsmind triage`
      - `opsmind incidents list`
      - `opsmind explain <id>`
      - `opsmind remediate <id>`
      - `opsmind worker`
      - `opsmind postmortem <id>`
* [ ] **5.4** `src/api/routes_incidents.py`:
      - `GET /api/v1/incidents`
      - `GET /api/v1/incidents/{id}`
      - `POST /api/v1/incidents/{id}/acknowledge`
      - `POST /api/v1/incidents/{id}/resolve`
      - `GET /api/v1/incidents/{id}/timeline`
      - `POST /api/v1/incidents/{id}/postmortem`
* [ ] **5.5** Tests: `tests/test_api_incidents.py` and `tests/test_cli.py`.

**Deliverable 5:** Interactive Slack incident cards, terminal triage CLI, and RESTful incident management.

---

## Phase 6 — Incident Memory (RAG) & AI Safety Remediation Runbooks

*Goal: historical incident retrieval and guarded, human-in-the-loop runbook execution.*

* [ ] **6.1** `src/memory/embedder.py` — Embeddings generation (`all-MiniLM-L6-v2`) with lazy loading and fallback.
* [ ] **6.2** `src/memory/vector_store.py` — Vector memory indexing resolved post-mortems and retrieving similar historical incidents into LLM prompts.
* [ ] **6.3** `src/executor/runbooks.py` — Predefined runbook catalog (`rollback-deployment`, `restart-service`, `scale-workload`, `clear-cache`, `cordon-node`).
* [ ] **6.4** `src/executor/runner.py` — Safe execution engine:
      - Command allowlist only (`shell=False` argv lists)
      - Strict regex argument validation (service names, namespaces, replica counts)
      - Mandatory dry-run preview (command preview, blast radius, risk rating)
      - Human approval workflow (`DRY_RUN` → `APPROVE` / `CANCEL`)
      - Immutable audit log (`who`, `what`, `when`, `why`, `target`, `result`)
* [ ] **6.5** API endpoints:
      - `POST /api/v1/incidents/{id}/remediation/dry-run`
      - `POST /api/v1/incidents/{id}/remediation/approve`
* [ ] **6.6** Tests: `tests/test_executor_security.py` (rejection of non-whitelisted commands, argument tampering, shell injections, dry-run safety) and `tests/test_memory.py`.

**Deliverable 6:** Historical incident RAG and strictly guarded, safe remediation execution.

---

## Phase 7 — Terraform Infrastructure as Code & CI/CD

*Goal: automated, cost-safe AWS provisioning and GitHub Actions CI/CD pipeline.*

* [ ] **7.1** Terraform modules (`infra/terraform/`):
      - `main.tf`, `variables.tf`, `outputs.tf`, `terraform.tfvars.example`
      - `iam.tf`: Least-privilege roles for OpsMind Worker (no `AdministratorAccess`)
      - `s3.tf`: S3 bucket with SSE encryption, versioning, and lifecycle transitions
      - `sqs.tf`: SQS queue + Dead-Letter Queue (DLQ)
      - `eventbridge.tf`: Custom event bus and routing rules
      - `cloudwatch.tf`: Log groups (14-day retention), custom metrics, alarms
      - `dynamodb.tf`: DynamoDB table with `PAY_PER_REQUEST` billing mode
      - `ec2.tf`: Single low-cost t4g.small / t3.micro EC2 instance with user data for Docker + OpsMind (no NAT gateway needed)
* [ ] **7.2** Secrets Management integration via AWS Secrets Manager & SSM Parameter Store.
* [ ] **7.3** `.github/workflows/ci.yml`:
      - `ruff check .`
      - `pytest`
      - Security & dependency audit
      - Docker build & optional ECR push
* [ ] **7.4** Tests: Terraform configuration validation & linting.

**Deliverable 7:** Production-ready Terraform IaC and robust CI/CD pipeline.

---

## Phase 8 — Containerization, Hardening & Documentation

*Goal: hardened Docker images, comprehensive developer & ops documentation.*

* [ ] **8.1** `Dockerfile`: Multi-stage build, non-root user `opsmind:opsmind`, healthcheck probe, zero baked-in secrets.
* [ ] **8.2** `docker-compose.yml`: Enhanced multi-service setup (API, Worker, Prometheus, Ollama).
* [ ] **8.3** Documentation suite (`docs/`):
      - `architecture.md`: Local Mode vs AWS Mode architectural guide
      - `local-development.md`: Step-by-step zero-AWS onboarding
      - `aws-deployment.md`: EC2, ECR, Docker, Terraform deployment guide
      - `security.md`: Least-privilege IAM, secret isolation, runbook allowlists, audit trail
      - `incident-flow.md`: End-to-end incident lifecycle walkthrough
      - `cost-control.md`: Free-tier optimization, avoiding NAT gateway, AWS Budgets setup
* [ ] **8.4** Comprehensive test suite execution and validation across all components.

**Deliverable 8:** Polished open-source product with complete documentation and production hardening.

---

## Cross-Cutting Concerns

| Area | Approach |
| --- | --- |
| **Local-First** | 100% runnable without AWS credentials or cloud dependencies |
| **Config & Secrets** | `Settings` object; `.env` in local mode, AWS Secrets Manager / SSM in AWS mode |
| **AI Safety** | Zero arbitrary command execution; allowlist-only runbooks with human approval |
| **Observability** | Correlation IDs, structured JSON logging, Prometheus & CloudWatch metrics |
| **Cost Safety** | Pay-per-request, no NAT Gateway by default, aggressive S3 lifecycle expiration |
| **Testing** | Unit + integration tests with mocked AWS / LLM clients; no flaky network calls in tests |
