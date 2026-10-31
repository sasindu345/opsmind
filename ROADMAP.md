# OpsMind Roadmap

Honest status of what is built, what is partial, and what is not started. This file replaces
`PLAN.md` and `OPSMIND_MASTER_IMPLEMENTATION_PLAN.md`, both of which marked phases complete that
had never been implemented.

Status is judged by one rule: a capability is **done** only if it is wired into the running
application and covered by a test. Code that exists but is imported nowhere is not done.

---

## Built

### Monitoring

- [x] Application registry with health URL and per-application probe interval
- [x] Background probe worker with a consecutive-failure tripwire
- [x] SSRF protection on every user-supplied URL: protocol allowlist, DNS pre-resolution, private
      and metadata address rejection, socket pinning, redirect re-validation, timeout and body caps
- [x] User-configured metric monitors over latency, error rate and availability, in threshold or
      anomaly mode, with a required breach streak and reset on recovery
- [x] Probe history, latency percentiles and availability aggregation

### Incident engine

- [x] Drain3 log clustering
- [x] Z-score and IQR anomaly detection
- [x] Correlator separating observed evidence, inferred correlation and LLM hypothesis
- [x] Unified telemetry signal store
- [x] Asynchronous queue and incident worker, local in-memory or Amazon SQS, with retries, a
      dead-letter queue and fingerprint deduplication
- [x] Stable incident identity, so repeated signals for one failure update one incident

### AI

- [x] LiteLLM client across Gemini, Ollama and Bedrock, with rate limiting and a JSON-repair retry
- [x] Structured `RootCauseAnalysis` output with calibrated confidence
- [x] Deterministic heuristic fallback when no model is configured
- [x] Per-provider credential validation, so readiness cannot claim a provider that would fail
- [x] Conversational Copilot over eight read-only tools, with tool breadcrumbs and citations
- [x] Copilot grounded mode, answering from data when no model is available
- [x] Vector incident memory and similar-incident retrieval
- [x] CI-specific prompt for build failures

### GitHub

- [x] Repository linking with a personal access token, verified before storage
- [x] Token held through `SecretManager`, never returned by an API or written to a log
- [x] Commit polling with conditional requests and rate-limit awareness
- [x] Failed Actions run detection, failing-job log retrieval, and AI-suggested fix
- [x] Webhook receiver for push, deployment status and workflow run
- [x] Shared deduplication between the poller and the webhook

### Remediation

- [x] Five allowlisted runbooks with strict regular-expression parameter validation
- [x] Argument-vector execution with `shell=False`
- [x] Mandatory dry-run preview showing the exact command, risk level and blast radius
- [x] Human approval with recorded identity
- [x] Simulation as explicit configuration, reported honestly to the caller and the audit record
- [x] Immutable JSONL audit trail, readable over the API

### Interfaces

- [x] React dashboard: overview, applications, application detail, incidents, incident detail,
      repositories, Copilot, runbooks, knowledge search, settings, triage playground
- [x] Beginner and Engineer modes with a plain-language translation layer
- [x] Native SVG latency sparklines and uptime bars
- [x] Single API client applying the base URL and auth header in one place
- [x] Slack incident cards, dispatched from the pipeline when tokens are configured
- [x] Typer and Rich terminal CLI

### Platform

- [x] Dual local and AWS modes behind one set of interfaces
- [x] Opt-in API key authentication on mutating endpoints
- [x] Terraform for EC2, SQS, DynamoDB, S3, EventBridge, CloudWatch and least-privilege IAM
- [x] SSH ingress scoped separately from the application port, rejecting `0.0.0.0/0`
- [x] GitHub Actions CI: lint, tests on Python 3.11 to 3.13, Terraform validation, Docker build,
      bundle freshness, and deployment from repository variables with no committed identifiers
- [x] Hardened multi-stage Docker image running as a non-root user
- [x] 177 tests passing, `ruff` clean

---

## Partial

| Capability | What works | What is missing |
| :--- | :--- | :--- |
| Prometheus | Alertmanager webhook ingestion | OpsMind does not query Prometheus. `PROMETHEUS_URL` is reserved and unread, so there is no PromQL proxy or metric scraping |
| CloudWatch | Alarm and EventBridge webhook ingestion | No metric queries; `CLOUDWATCH_NAMESPACE` is not yet used for emission |
| Slack | Incident cards dispatched, interactive handlers written | Socket Mode listener is not started by the application, so button presses are not received |
| Knowledge search | Vector memory and a search UI | Ranking is TF-IDF cosine similarity, weaker than a sentence-transformer embedding |
| Postmortems | Generated on request from the incident record | Not generated automatically on resolution |

---

## Not started

- **Automated post-remediation verification.** Re-probe at intervals after an approved fix and
  transition the incident to resolved only once it is confirmed healthy. This is the most valuable
  remaining item: it closes the loop from detection to verified recovery.
- **Kubernetes-native telemetry.** Read-only pod and event metrics.
- **HTTP rate limiting.** The LLM call budget is limited, but the API itself is not.
- **Probe snapshot retention.** High-frequency samples accumulate without a rolling purge or
  hourly roll-up.
- **Multi-user access control.** Authentication is a single shared API key, with no users, roles or
  per-application permissions.
- **Frontend test suite.** No JavaScript test runner is configured.
- **Distributed local mode.** The in-memory queue is per-process; running API and worker separately
  requires AWS mode.
- **Alert notification routing.** Beyond Slack, there is no paging, escalation or on-call schedule
  integration.

---

## Deliberately out of scope

These are not gaps. OpsMind is the layer that explains failures and carries them to a safe fix, so
it does not try to be:

- a metrics time-series database, or a replacement for Prometheus alerting rules, label matchers,
  silences or inhibition;
- a general log search platform;
- a dashboard builder;
- an unrestricted automation agent. Remediation stays allowlist-only behind human approval, and the
  AI is structurally unable to execute anything.
