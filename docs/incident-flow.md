# End-to-End Incident Lifecycle Walkthrough

This document outlines how an alert transitions through OpsMind from initial trigger to root-cause verdict and resolution.

---

## 1. Lifecycle Timeline Diagram

```
Telemetry Source               OpsMind Ingestion                Triage & Root Cause             Remediation & Storage
────────────────               ─────────────────                ───────────────────             ─────────────────────

Prometheus / GitHub ──HTTP──► Webhook Route (202 Accepted)
                                     │
                                     ▼
                              SQS / Local Queue
                                     │
                                     ▼
                              Incident Worker
                                     │
                                     ├──► Drain3 Clustering
                                     │
                                     ├──► Statistical Anomaly Check (Z-Score/IQR)
                                     │
                                     ├──► GitOps Commit Time-Correlation
                                     │
                                     ├──► Historical Memory (RAG Lookup)
                                     │
                                     ▼
                              LLM Structured Reasoner (Bedrock/Gemini/Ollama)
                                     │
                                     ▼
                              Incident Record Created
                                     ├──► DynamoDB / SQLite Database
                                     ├──► Post-Mortem Report (S3 / Local FS)
                                     └──► Slack Card with Interactive Action Buttons
                                                 │
                                                 ├──► [Acknowledge]
                                                 ├──► [Explain]
                                                 └──► [Remediate (Dry-Run -> Approve)]
```

---

## 2. Step-by-Step Breakdown

1. **Ingestion (< 50ms)**:
   - Alert arrives at `/api/v1/webhooks/prometheus` or `/api/v1/analyze/logs/async`.
   - Endpoint issues a correlation ID and returns HTTP 202 immediately.

2. **Drain3 Log Clustering**:
   - Compresses raw logs into concise template clusters (e.g. `Connection to <*> failed with timeout`).

3. **Multi-Source Anomaly Correlation**:
   - Flags metric anomalies (latency spike, memory exhaustion).
   - Identifies if a GitHub deployment or commit occurred within the anomaly onset window.

4. **Historical RAG Enrichment**:
   - Queries vector memory for similar historical outages and injects prior fixes into LLM context.

5. **LLM Root Cause Synthesis**:
   - Returns structured JSON specifying probable cause, severity level, confidence score, and remediation steps.

6. **Notification & ChatOps**:
   - Posts Slack Block Kit cards with interactive buttons (`Ack`, `Explain`, `Remediate`, `Post-Mortem`).

7. **Guarded Resolution**:
   - Operator triggers runbook dry-run, reviews preview, and confirms execution.
