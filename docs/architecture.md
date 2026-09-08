# OpsMind Architecture

OpsMind operates in two primary deployment modes, offering complete portability between zero-cost local development and high-throughput AWS production deployments.

---

## 1. Dual Architectural Modes

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LOCAL MODE (Zero-AWS)                             │
│                                                                             │
│  Alerts / Webhooks ──► FastAPI ──► In-Memory Queue ──► Background Worker     │
│                                                            │                │
│                                     ┌──────────────────────┴──────────────┐ │
│                                     ▼                                     ▼ │
│                                Drain3 + Anomaly                       Ollama/Gemini │
│                                     │                                     │ │
│                                     ▼                                     ▼ │
│                              SQLite DB + Vectors ◄─── Post-Mortem Markdown  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          AWS MODE (Cloud-Native)                            │
│                                                                             │
│  CloudWatch / GitHub ──► EventBridge ──► Amazon SQS ──► Incident Worker     │
│                                                            │                │
│                                     ┌──────────────────────┴──────────────┐ │
│                                     ▼                                     ▼ │
│                               Drain3 + GitOps                       Amazon Bedrock  │
│                                     │                                     │ │
│                                     ▼                                     ▼ │
│                              Amazon DynamoDB ◄───────── Amazon S3 Bucket    │
│                             (Metadata/State)            (Encrypted Reports) │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Components

1. **Ingestion & Webhooks (`src/api/routes_webhooks.py`)**:
   - Ingests alerts from Prometheus Alertmanager, GitHub deployments (with HMAC verification), CloudWatch Alarms, and custom EventBridge payloads.
   - Responds with fast acknowledgment (`HTTP 202 Accepted`) in < 50ms.

2. **Telemetry & Statistical Intelligence (`src/core/`)**:
   - **Drain3 Pattern Clustering**: Parses unstructured log streams into structural templates.
   - **Rolling Anomaly Detection**: Uses Z-score and Interquartile Range (IQR) detectors on CPU, Memory, Latency, and HTTP 5xx rates.
   - **Multi-Source Correlator**: Links telemetry anomalies to Git commits and deployment onsets.

3. **LLM Root-Cause Reasoning (`src/llm/`)**:
   - Uses LiteLLM to route prompts to Amazon Bedrock (`bedrock/anthropic.claude-3-haiku`), Google Gemini (`gemini/gemini-2.0-flash`), or local Ollama (`ollama/llama3:8b`).
   - Guarantees strict JSON schema compliance with automated repair retries.

4. **Incident Memory & RAG (`src/memory/`)**:
   - Embeds historical post-mortems and resolutions using normalized vector embeddings.
   - Retrieves similar past outages (`GET /api/v1/incidents/{id}/similar`) to speed up root-cause diagnosis.

5. **Guarded Safe Remediation (`src/executor/`)**:
   - Safe predefined runbooks (`rollback-deployment`, `restart-service`, `scale-workload`, `clear-cache`, `cordon-node`).
   - Zero raw shell execution (`shell=False`), mandatory regex parameter validation, dry-run previews, and immutable audit logs.
