# OpsMind — Master Architecture Upgrade & Phased Implementation Plan

> **Document Version:** 2.0 (Consolidated Master Plan)  
> **Status:** Draft for Review — **Do Not Start Coding Until Approved**  
> **Target System:** OpsMind AI Operations Copilot  
> **Core Product Promise:** *"Know what is wrong, understand why it happened, and safely fix it."*  
> **Preservation Guarantee:** 100% backward compatibility with all working prototype capabilities (Drain3 log clustering, Bedrock/Gemini structured LLM analysis, heuristic fallback, guarded runbooks, DynamoDB/SQLite persistence, SQS/Local workers, Slack cards).

---

## 1. Executive Architecture Assessment & Ground Truth Audit

### 1.1 Current Architectural Reality
An exhaustive source-code audit reveals that OpsMind is currently an **event-driven, passive triage pipeline**:
```
External Alerts / Logs / GitHub Pushes
              ↓
   FastAPI Endpoints (:8000)
              ↓
  Local Queue / AWS SQS (DLQ + Backoff)
              ↓
 Asynchronous Worker (Drain3 Clustering + Z-score Anomaly)
              ↓
 15-Minute Event Correlator (Logs + Git + Alerts)
              ↓
 Structured LLM Investigation (LiteLLM: Claude 3 / Gemini)
              ↓
 Persistence (SQLite / DynamoDB) + S3 Postmortems
              ↓
 Guarded Remediation (4 Runbooks, shell=False, Dry-Run)
```

### 1.2 Ground-Truth Gap Analysis

| Category | Fully Implemented (Keep & Protect) | Partially Implemented (Refactor/Extend) | Missing (Must Develop) |
| :--- | :--- | :--- | :--- |
| **Application Model** | Services as raw string names | Loose correlation across logs | First-class `ApplicationRecord` entity, CRUD API, Environment model, Health profiles |
| **Monitoring** | Passive log ingestion, Alertmanager & CloudWatch webhooks | On-demand `/readyz` local host probe | **Tier 1 Active Synthetic Probes**: 30s async HTTP/HTTPS health checks, latency tracking, 3-probe tripwires, SSRF filter |
| **Incident Engine** | 15-minute sliding window correlation, Drain3 clustering, Z-score/IQR anomaly detector | Alertmanager & log-driven incident creation | Synthetic probe outage correlation, unified `TelemetrySignal` envelope, auto-recovery detection |
| **AI / LLM** | LiteLLM client (Bedrock Claude 3, Gemini Flash), Pydantic schemas, retry backoff, heuristic fallback | One-shot postmortem & RCA prompt | Multi-turn conversational ReAct Copilot, read-only inspection tools, structured evidence cards, investigation breadcrumbs |
| **Remediation** | 4 allowlisted runbooks (`rollback-deployment`, `restart-service`, `scale-workload`, `clear-cache`), `shell=False`, dry-run | Approval token flow via API / Slack | Pre-populated 1-click incident fixes, post-remediation verification probe loop, interactive Audit Log UI |
| **UI / UX** | React 18 SPA pre-bundled via esbuild, basic incident list, dry-run modal, dark styling | Metric graphs (currently static placeholders), triage playground | Complete SaaS Information Architecture (Overview, Apps, Incidents, Copilot, Runbooks, Knowledge, Settings), **Beginner vs. Engineer Mode** |
| **Security** | `shell=False`, argument regex validation | Local disk `.jsonl` audit log | SSRF IP blacklist & DNS resolution, `X-OpsMind-API-Key` authentication on mutations, secrets masking |
| **Knowledge** | 128-dim TF-IDF vector memory, cosine similarity, S3/local Markdown postmortems | Incident similarity lookup in backend | Dedicated `/knowledge` semantic search UI, historical resolution cards |
| **Integrations** | GitHub, Alertmanager, CloudWatch, Slack webhooks | Static copy-paste snippet tab | Test Connection handshakes, Prometheus PromQL proxy, health status indicators |

---

## 2. Target Architecture: Tiered Hybrid Telemetry

OpsMind will **NOT** become a Prometheus clone, a Grafana clone, a generic log viewer, or an unrestricted shell AI. It is laser-focused on:
$$\text{Application Health} \longrightarrow \text{Incident} \longrightarrow \text{Investigation} \longrightarrow \text{Root Cause} \longrightarrow \text{Safe Action} \longrightarrow \text{Verification} \longrightarrow \text{Learning}$$

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 INCOMING TELEMETRY                                     │
├────────────────────────────┬─────────────────────────────┬─────────────────────────────┤
│  TIER 1: ZERO-CONFIG       │  TIER 2: OPTIONAL TELEMETRY │  TIER 3: EVENT STREAMS      │
│  - Active Synthetic Probes │  - Prometheus PromQL Proxy  │  - GitHub Commits / Pushes  │
│  - HTTP/HTTPS Status       │  - CloudWatch Metrics       │  - GitHub Actions Failures  │
│  - Response Latency (ms)   │  - Kubernetes Read-Only Pod │  - Alertmanager Alarms      │
│  - Consecutive Tripwire    │    Metrics & Events         │  - CloudWatch Alarm Events  │
│  - 24h Availability %      │                             │  - Raw Log Ingestion        │
└─────────────┬──────────────┴──────────────┬──────────────┴──────────────┬──────────────┘
              │                             │                             │
              └─────────────────────────────┼─────────────────────────────┘
                                            ▼
                           ┌─────────────────────────────────┐
                           │   TelemetrySignal Normalizer    │
                           └────────────────┬────────────────┘
                                            ▼
                           ┌─────────────────────────────────┐
                           │  Incident Correlation Pipeline  │
                           │ (Drain3 + Anomaly + Time Window)│
                           └────────────────┬────────────────┘
                                            ▼
                           ┌─────────────────────────────────┐
                           │  AI Investigation Engine        │
                           │  (ReAct Tools: Read-Only Data)  │
                           └────────────────┬────────────────┘
                                            ▼
                           ┌─────────────────────────────────┐
                           │ Guarded Remediation & Trust     │
                           │ (Dry-Run → Human Approval       │
                           │  → shell=False → Verify Probe)  │
                           └────────────────┬────────────────┘
                                            ▼
                           ┌─────────────────────────────────┐
                           │ Vector Incident Memory (RAG)    │
                           └─────────────────────────────────┘
```

---

## 3. Data Models & Database Strategy

### 3.1 Persistence Architecture
- **Dual-Mode Persistence Strategy (Preserved):** SQLite for local development; Amazon DynamoDB + S3 for AWS cloud deployment.
- **Data Retention Policy:**
  - High-frequency `HealthProbeSnapshot`: 30-day rolling window (older records auto-purged or rolled up into hourly averages).
  - Incidents & Remediation Audits: Retained permanently for compliance and vector RAG retrieval.

### 3.2 Core Schemas

#### 1. `ApplicationRecord`
```python
class ApplicationRecord(BaseModel):
    app_id: str                      # UUID / slug (e.g. "checkout-api")
    name: str                        # Human display name ("Checkout API")
    description: Optional[str]       # Service description
    environment: str                 # "production" | "staging" | "development"
    owner_team: str                  # "payments-team"
    health_url: str                  # "https://api.example.com/healthz"
    probe_interval_seconds: int = 30 # Default 30s
    health_status: str               # "healthy" | "degraded" | "critical" | "unknown"
    consecutive_failures: int = 0    # Tripwire counter
    current_latency_ms: float = 0.0  # Latest probe latency
    uptime_24h_percent: float = 100.0# Rolling 24h uptime
    last_probe_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
```

#### 2. `HealthProbeSnapshot`
```python
class HealthProbeSnapshot(BaseModel):
    probe_id: str                    # UUID
    app_id: str                      # Foreign key to ApplicationRecord
    timestamp: datetime
    http_status: int                 # e.g. 200, 503, 0 (timeout/network error)
    latency_ms: float                # Request duration in ms
    is_success: bool                 # True if 2xx / expected status
    error_message: Optional[str]     # "Connection timeout after 5000ms"
    resolved_ip: Optional[str]       # Public IP validated by SSRF filter
```

#### 3. `TelemetrySignal` (Unified Ingestion Envelope)
```python
class TelemetrySignal(BaseModel):
    signal_id: str
    source: Literal["synthetic", "log", "metric", "git", "cloudwatch", "alertmanager"]
    app_id: str
    service: str
    environment: str
    timestamp: datetime
    level: str                       # "INFO", "WARN", "ERROR", "CRITICAL"
    metric_name: Optional[str]       # e.g. "http_probe_latency", "cpu_utilization"
    metric_value: Optional[float]
    raw_message: Optional[str]
    pattern_template: Optional[str]  # Extracted by Drain3
    metadata: Dict[str, Any] = {}
```

#### 4. `IncidentRecord` (Enhanced Lifecycle)
```python
class IncidentStatus(str, Enum):
    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REMEDIATION_PROPOSED = "REMEDIATION_PROPOSED"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    REMEDIATION_EXECUTING = "REMEDIATION_EXECUTING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"

class IncidentRecord(BaseModel):
    incident_id: str
    app_id: str
    service: str
    environment: str
    title: str                       # Plain-English title
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    status: IncidentStatus
    start_time: datetime
    detected_at: datetime
    acknowledged_at: Optional[datetime]
    resolved_at: Optional[datetime]
    probable_root_cause: Optional[str]
    confidence_score: float          # 0.0 - 1.0 (evidence-backed)
    blast_radius: List[str]          # Affected downstream services
    evidence: List[Dict[str, Any]]   # Log clusters, metrics, git commits
    timeline: List[Dict[str, Any]]   # Chronological sequence of events
    active_remediation_id: Optional[str]
```

#### 5. `RemediationAuditRecord`
```python
class RemediationAuditRecord(BaseModel):
    execution_id: str
    incident_id: str
    app_id: str
    runbook_id: str                  # e.g. "rollback-deployment"
    requested_action: str
    parameters: Dict[str, Any]       # Validated against regex allowlists
    dry_run_output: Optional[str]
    approved_by: str                 # Operator identity/email
    approval_timestamp: datetime
    execution_timestamp: datetime
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    verification_status: Literal["VERIFIED_HEALTHY", "VERIFICATION_FAILED", "SKIPPED"]
    verification_details: Optional[str]
```

---

## 4. Security Architecture & Threat Model

### 4.1 Mandatory SSRF Protection Engine (`src/core/security.py`)
Allowing users to specify arbitrary health check URLs introduces severe Server-Side Request Forgery (SSRF) risk. The synthetic monitoring engine enforces a strict multi-layer guard:

```
User Health URL (e.g., https://api.mycorp.com/health)
                      ↓
       1. URL Protocol Validation (HTTP/HTTPS only)
                      ↓
       2. DNS Pre-Resolution (getaddrinfo)
                      ↓
       3. IP Address Inspection against Prohibited CIDRs:
          - 127.0.0.0/8 (Loopback)
          - 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 (RFC 1918 Private)
          - 169.254.169.254 / 169.254.0.0/16 (Link-Local & Cloud Metadata)
          - 0.0.0.0/8, ::1, fc00::/7 (IPv6 local/private)
                      ↓
       4. Socket Connection Pinning (to the resolved, validated IP)
                      ↓
       5. Redirect Destination Re-Validation (max 3 redirects)
                      ↓
       6. Hard Request Timeout (5000ms) & Max Body Cap (512KB)
```

### 4.2 Remediation Execution Security
- **`shell=False` strictly enforced:** All runbook commands are executed as discrete argument vectors (`argv` lists), completely eliminating shell injection vulnerabilities.
- **Strict Parameter Regex:** Every parameter (`service_name`, `deployment_name`, `replicas`) is validated against strict regexes (e.g. `^[a-zA-Z0-9_-]{1,64}$`).
- **Human Approval Gate:** Mutating operations require explicit operator action with identity recording. AI agents are structurally barred from executing commands autonomously.

### 4.3 API Authentication
- Mutating endpoints (`POST /api/v1/applications`, `POST /api/v1/remediations/{id}/execute`, etc.) require an `X-OpsMind-API-Key` header verified via FastAPI dependency injection.

---

## 5. UI/UX Design Specification & Information Architecture

### 5.1 Design Principles
- **Inspiration:** Linear, Vercel, Stripe Dashboard, calm incident response software.
- **Aesthetic:** Clean, light-first enterprise interface, high contrast, 8px grid system, 12-16px card border-radius, subtle 1px borders (`#E2E8F0` / dark `#334155`), minimal drop shadows.
- **Color System:**
  - Background: Neutral White `#FFFFFF` / Slate 50 `#F8FAFC` (Dark: Slate 950 `#020617`).
  - Primary Text: Slate 900 `#0F172A` (Dark: Slate 50 `#F8FAFC`).
  - Secondary Text: Slate 500 `#64748B`.
  - Healthy: Emerald 600 `#059669` / Emerald 50 `#ECFDF5`.
  - Degraded: Amber 600 `#D97706` / Amber 50 `#FFFBEB`.
  - Critical: Rose 600 `#E11D48` / Rose 50 `#FFF1F2`.
  - Informational: Blue 600 `#2563EB` / Blue 50 `#EFF6FF`.
- **Never rely on color alone:** Status badges always include a semantic icon and clear text (e.g. `● Operational`, `▲ Degraded`, `✖ Critical Outage`).

### 5.2 Core Information Hierarchy
Every screen answers user questions in this strict order:
$$\text{STATUS} \longrightarrow \text{IMPACT} \longrightarrow \text{CAUSE} \longrightarrow \text{EVIDENCE} \longrightarrow \text{ACTION} \longrightarrow \text{VERIFICATION} \longrightarrow \text{TECHNICAL DETAILS}$$

### 5.3 Beginner Mode vs. Engineer Mode

| Feature / Element | Beginner Mode (Default) | Engineer Mode |
| :--- | :--- | :--- |
| **Error Patterns** | "Common Error Patterns (45 occurrences)" | "Drain3 Cluster #47: `Database connection to <*> timed out`" |
| **Telemetry Rates** | "Requests per minute: 1,420" | "PromQL: `sum(rate(http_requests_total[5m])) by (status)`" |
| **Remediation Details**| "Action: Rollback to previous deployment" | "Command: `kubectl rollout undo deployment/checkout-api`" |
| **Incident Memory** | "Similar past incident: DB Pool Exhaustion" | "Vector Cosine Similarity: `0.924` (Dim: 128)" |
| **Status Codes** | "Application unavailable" | "HTTP probe failed: status `503`, latency `5021ms`" |
| **Infrastructure** | Hidden | Queue depths, worker latencies, LLM token metrics |

### 5.4 Screen-by-Screen Specifications

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ TOP BAR: [OpsMind Logo] | [Status: Operational ●] | [2 Active Incidents] | [Beginner | Engineer] │
├───────────────────┬──────────────────────────────────────────────────────────────────────┤
│ SIDEBAR (240px)   │ MAIN CONTENT AREA                                                    │
│ ───────────────── │                                                                      │
│ ✦ Overview        │ /overview                                                            │
│ ▦ Applications    │ Top: 4 Health Cards (Apps Monitored, Fleet Health %, Incidents, AI) │
│ ⚠ Incidents (2)   │ Middle: Critical Active Incident Banner (if any)                     │
│ 💬 AI Copilot     │ Bottom: Application Health Grid (Cards with 24h uptime bars)        │
│ ⚡ Runbooks       │ Right/Sub: Recent Activity Stream                                    │
│ 📖 Knowledge      │                                                                      │
│ ───────────────── │                                                                      │
│ ⚙ Settings        │                                                                      │
│   - Integrations  │                                                                      │
│   - Audit Logs    │                                                                      │
│   - Developer API │                                                                      │
└───────────────────┴──────────────────────────────────────────────────────────────────────┘
```

#### Screen Details:
1. **Global Shell (`AppShell`):** Top bar displays brand, real-time `/readyz` health pill, active incident badge, **Beginner/Engineer Mode switch**, global search (`Cmd+K`), and user avatar. Sidebar (220-240px) with clean icons.
2. **Overview Page (`/overview`):** Answers *"Is everything okay?"* in 3 seconds. 4 summary cards, an expandable Critical Incident Banner, an application health grid with sparkline latency and uptime bars, and an activity timeline.
3. **Applications Page (`/applications`):** Application inventory with search, environment filters (`Production`, `Staging`, `Dev`), status filters, and a prominent `+ Add Application` primary CTA button.
4. **Add Application Flow (4-Step Modal):**
   - Step 1: Name (`Checkout API`) & Environment (`Production`).
   - Step 2: Health URL (`https://api.example.com/healthz`) with explanation of automated checks.
   - Step 3: Check frequency (Default: `30 seconds`).
   - Step 4: Preview & Confirm $\rightarrow$ Immediate test probe $\rightarrow$ Monitored!
5. **Application Detail (`/applications/:id`):** Live Health Hero card, Key Metrics (Availability %, Latency ms, Error Rate %), clean response-time line chart, active incidents, recent git deployments, and AI Copilot summary card.
6. **Incidents Page (`/incidents`):** Prioritized incident cards leading with plain-English human diagnosis, AI confidence %, supporting evidence summary bullets, and quick action buttons (`[Acknowledge]`, `[Investigate]`, `[Safe Fix]`).
7. **Incident Detail / Investigation Workspace (`/incidents/:id`):** AI diagnosis headline, evidence cards (Logs, Metrics, Git, Historical), chronological timeline, blast radius map, and safe remediation proposal with dry-run preview.
8. **Remediation Trust Console:** Modal flow showing: What will happen $\rightarrow$ Why recommended $\rightarrow$ Target service $\rightarrow$ Exact command $\rightarrow$ Risk level $\rightarrow$ Explicit "Approve & Execute" button $\rightarrow$ Real-time post-remediation health verification check.
9. **AI Copilot (`/copilot`):** Interactive investigation workspace. Suggested starter prompts (`Why is Checkout API slow?`, `What changed in Production?`). Safe action breadcrumbs (`[✓ Checking health]`, `[✓ Reviewing logs]`, `[✓ Correlating deployments]`) followed by grounded conclusions with evidence cards.
10. **Runbooks Page (`/runbooks`):** Catalog of allowlisted operational procedures (`Rollback Deployment`, `Restart Service`, `Scale Workload`, `Clear Cache`) with risk badges, allowed parameters, and execution history.
11. **Knowledge Page (`/knowledge`):** Semantic search bar across historical incidents, postmortems, and resolution outcomes.
12. **Settings Page (`/settings`):**
    - Sub-tab 1: Integrations Hub (GitHub, Prometheus, CloudWatch, Slack) with live connection status and test buttons.
    - Sub-tab 2: Remediation Audit Log (Filterable table of all executed runbooks, approvers, stdout/stderr, and verification results).
    - Sub-tab 3: Developer API Docs & API Keys.

---

## 6. AI Copilot: ReAct Tools & Investigation Loop

The AI Copilot operates with strictly partitioned tools to preserve safety:

```
                               ┌────────────────────────────────┐
                               │     User / Incident Trigger    │
                               └───────────────┬────────────────┘
                                               ▼
                               ┌────────────────────────────────┐
                               │   AI Copilot Orchestrator      │
                               │  (LiteLLM: Claude 3 / Gemini)  │
                               └───────────────┬────────────────┘
                                               │
         ┌─────────────────────────────────────┴─────────────────────────────────────┐
         ▼                                                                           ▼
┌─────────────────────────────────┐                                 ┌─────────────────────────────────┐
│   READ-ONLY INSPECTION TOOLS    │                                 │    GUARDED REMEDIATION TOOLS    │
│  (AI can execute autonomously)  │                                 │   (AI CANNOT execute alone)     │
├─────────────────────────────────┤                                 ├─────────────────────────────────┤
│ • get_application_health(id)    │                                 │ • propose_remediation(plan)    │
│ • get_health_probe_history(id)  │                                 │   → Prepares proposal only      │
│ • get_recent_log_patterns(id)   │                                 │                                 │
│ • get_recent_deployments(id)    │                                 │ • execute_approved_remediation  │
│ • query_metrics(id, range)      │                                 │   → REQUIRES Operator Token     │
│ • search_incident_memory(query) │                                 │   → Verified by Human Approval  │
│ • get_active_incidents()        │                                 │                                 │
└─────────────────────────────────┘                                 └─────────────────────────────────┘
```

### Investigation Output Contract:
All AI diagnoses conform to a strict schema containing:
- `summary`: One-sentence plain-English summary.
- `probable_root_cause`: Grounded explanation.
- `confidence`: Calibrated score (e.g. 0.92) based on presence of corroborating evidence.
- `evidence`: Array of structured evidence items (e.g. `{type: "log_cluster", text: "45 connection timeouts", count: 45}`).
- `blast_radius`: List of downstream affected services.
- `recommended_action`: Associated allowlisted runbook recommendation.
- `verification_plan`: Method to verify recovery (e.g. 3 consecutive HTTP 200 probes).

---

## 7. Phased Implementation Plan

### Phase 0: Baseline & Design Foundation
- **Goal:** Build the global modern SaaS application shell and establish design tokens without breaking any existing backend or frontend features.
- **Code Status:**
  - Existing `src/frontend/App.jsx` provides working triage and incident lists.
  - Reusable: Incident cards, triage playground, API client.
- **Backend Changes:** None.
- **Frontend Changes:**
  - Create `src/frontend/components/AppShell.jsx`, `TopBar.jsx`, `Sidebar.jsx`, `ModeToggle.jsx`.
  - Create design tokens in `static/style.css` (8px grid, CSS variables, subtle card borders, semantic status colors).
  - Add global Beginner / Engineer Mode context provider.
- **Deliverables & Verification:**
  - Verify layout responsiveness on desktop and mobile.
  - Test mode toggle state propagation.
  - Run `npm run build` to compile `static/app.js`.

---

### Phase 1: Application-Centric Foundation
- **Goal:** Model applications as first-class entities with CRUD APIs and repository persistence.
- **Code Status:**
  - Currently services are loose strings in incident payloads. Needs new data models and tables.
- **Backend Changes:**
  - Define `ApplicationRecord` in `src/infrastructure/interfaces.py` and `src/api/schemas.py`.
  - Add SQLite schema migration: `CREATE TABLE IF NOT EXISTS applications (...)` in `src/infrastructure/local/repository.py`.
  - Add DynamoDB item mappings in `src/infrastructure/aws/repository.py`.
  - Implement `src/api/routes_applications.py` (`POST`, `GET`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}`).
  - Mount router in `src/main.py`.
- **Frontend Changes:**
  - Build `src/frontend/pages/ApplicationsPage.jsx` with card grid / table view.
  - Build `src/frontend/components/AddApplicationModal.jsx` (4-step onboarding flow).
- **Acceptance Criteria:**
  - A user can register `checkout-api` with `https://httpbin.org/status/200` via UI or API and see it persist in the catalog.

---

### Phase 2: Synthetic Health Monitoring & SSRF Protection
- **Goal:** Active, automated zero-configuration health checking with strict SSRF defense.
- **Code Status:**
  - Currently OpsMind only receives external webhooks. Needs background probing engine.
- **Backend Changes:**
  - Implement `src/core/security.py`: `SSRFValidator` with IP blacklist, DNS pre-resolution, and redirect destination inspection.
  - Implement `src/core/synthetic.py`: `SyntheticHealthWorker` running periodic async HTTP/HTTPS probes.
  - Record probe history as `HealthProbeSnapshot`.
  - Implement consecutive failure counter (default: 3 failures $\rightarrow$ trigger incident).
  - Add `POST /api/v1/applications/{id}/probe` for on-demand checks.
  - Register worker in FastAPI lifespan in `src/main.py`.
- **Frontend Changes:**
  - Live status indicators on application cards (Healthy / Degraded / Critical) with latest latency in ms.
  - "Check Now" manual probe button in Application Detail view.
- **Acceptance Criteria:**
  - Target URL returning 500 trips an incident after 3 consecutive probe intervals.
  - Attempting to probe `http://169.254.169.254` or `http://localhost:8000` is rejected with `400 Bad Request (SSRF Protection Triggered)`.
  - Recovery probe resets consecutive failures and clears degradation.

---

### Phase 3: Incident Engine Unification & Telemetry Normalization
- **Goal:** Correlate synthetic probe failures, raw log clusters, metric anomalies, and git deployments into a unified incident timeline.
- **Code Status:**
  - Reusable: `DrainFilter` in `src/core/drain_filter.py`, `AnomalyDetector` in `src/core/anomaly_detector.py`, `IncidentCorrelator` in `src/core/correlator.py`.
- **Backend Changes:**
  - Create `src/core/telemetry.py` with `TelemetrySignal` envelope.
  - Update `src/core/pipeline.py` to accept synthetic probe signals alongside logs and alerts.
  - Map incidents to their parent `ApplicationRecord`.
  - Expand `IncidentStatus` enum with `VERIFYING`, `WAITING_FOR_APPROVAL`, `REMEDIATION_EXECUTING`.
- **Frontend Changes:**
  - Update incident list with plain-English human-readable titles.
  - Display correlated git commit badge on incident rows.
- **Acceptance Criteria:**
  - A single incident aggregates probe downtime, closest git deployment commit SHA, and Drain3 log error cluster into one coherent record.

---

### Phase 4: UI/UX Redesign & Information Architecture
- **Goal:** Complete redesign of all pages adhering to the modern SaaS design spec and progressive disclosure.
- **Code Status:**
  - Replaces the prototype tabbed layout with a full router-based SaaS interface.
- **Frontend Changes:**
  - `src/frontend/pages/OverviewPage.jsx`: Fleet health, active incident banner, scannable application grid, activity stream.
  - `src/frontend/pages/ApplicationDetailPage.jsx`: Health hero, latency chart, incident history, commit feed.
  - `src/frontend/pages/IncidentsPage.jsx`: Prioritized incident cards with plain-English diagnosis.
  - `src/frontend/pages/IncidentDetailPage.jsx`: Evidence cards, chronological timeline, blast radius, remediation drawer.
  - `src/frontend/pages/RunbooksPage.jsx`: Runbook catalog with risk tags.
  - `src/frontend/pages/KnowledgePage.jsx`: Semantic search and postmortem viewer.
  - `src/frontend/pages/SettingsPage.jsx`: Integrations hub, audit logs table, developer API docs.
- **Acceptance Criteria:**
  - Beginner Mode presents zero raw JSON, zero regex, and plain-English text.
  - Engineer Mode toggle reveals raw payloads, PromQL, cluster IDs, and system telemetry without altering page layout.

---

### Phase 5: Native Operational Metrics & Visualization
- **Goal:** Render essential operational charts (latency, uptime, error rates) natively without requiring Grafana.
- **Code Status:**
  - Needs time-series aggregation endpoints and lightweight native chart components.
- **Backend Changes:**
  - Implement `GET /api/v1/applications/{id}/metrics` with 1h, 6h, 24h, 7d aggregation buckets from probe snapshots.
- **Frontend Changes:**
  - Create `src/frontend/components/MetricSparkline.jsx`: Native SVG response-time line chart with tooltips.
  - Create `src/frontend/components/AvailabilityBar.jsx`: 24-hour segmented uptime bar.
- **Acceptance Criteria:**
  - Application Detail displays response time trends and 24h uptime visualization with smooth loading and empty states.

---

### Phase 6: Conversational AI Operations Copilot
- **Goal:** Transform static 1-shot RCA into an interactive, multi-turn ReAct operations agent.
- **Code Status:**
  - Reusable: `LLMClient` (Bedrock / Gemini) in `src/llm/client.py`, vector memory in `src/memory/vector_store.py`.
- **Backend Changes:**
  - Implement `src/llm/tools.py`: Read-only inspection tools (`get_application_health`, `get_recent_logs`, `get_recent_deployments`, `search_incident_memory`).
  - Implement `src/llm/copilot.py`: ReAct supervisor loop with LiteLLM structured function calling.
  - Implement `src/api/routes_copilot.py`: `POST /api/v1/copilot/chat` and conversation session store.
- **Frontend Changes:**
  - Build `src/frontend/pages/CopilotPage.jsx`: 3-pane layout with suggested questions, safe breadcrumb indicators (`[✓ Checking health]`), and structured evidence cards.
  - Global `Cmd+K` drawer shortcut.
- **Acceptance Criteria:**
  - User can ask *"Why is payment-api slow?"* and receive an evidence-backed answer citing actual probe latencies and recent commits.

---

### Phase 7: Guarded Remediation Trust Console & Post-Fix Verification
- **Goal:** Ensure every remediation action is safe, previewable, human-approved, audited, and automatically verified.
- **Code Status:**
  - Reusable: `GuardedRemediationRunner` in `src/executor/runner.py`, 4 allowlisted runbooks, `shell=False`.
- **Backend Changes:**
  - Implement automated post-fix verification in `src/executor/runner.py`: After runbook execution, trigger immediate synthetic health probes at 5s, 15s, and 30s.
  - If probes return healthy (HTTP 200), auto-transition incident to `RESOLVED (Verified Recovered)`.
  - If probes fail, return `VERIFICATION_FAILED` and alert the operator without executing further commands.
  - Implement `GET /api/v1/remediations/audit` endpoint.
- **Frontend Changes:**
  - Build `RemediationModal.jsx`: Risk level badge, parameter preview, dry-run output, and explicit approval button.
  - Build Audit Log table in Settings with stdout/stderr inspection.
- **Acceptance Criteria:**
  - No runbook executes without operator approval.
  - Executed runbooks automatically initiate recovery verification and log a complete audit record.

---

### Phase 8: Knowledge Base & Postmortem Incident Memory
- **Goal:** Enable institutional memory search across past incidents and postmortems using RAG.
- **Code Status:**
  - Reusable: 128-dim TF-IDF embedder and cosine similarity index in `src/memory/vector_store.py`.
- **Backend Changes:**
  - Expose `GET /api/v1/knowledge/search?q={query}` returning matched past incidents, root causes, and effective runbooks.
- **Frontend Changes:**
  - Search bar on `/knowledge` page with instant filtering.
  - Postmortem reader modal with structured markdown rendering.
- **Acceptance Criteria:**
  - Querying *"connection timeout"* returns past database incidents with similarity score and resolution steps.

---

### Phase 9: Deep Telemetry Integrations & Engineer Mode Extensions
- **Goal:** Connect external telemetry providers (Prometheus, CloudWatch, Slack) as optional extensions.
- **Code Status:**
  - Reusable: Webhook handlers in `src/api/routes_webhooks.py`, Slack Bolt app in `src/chatops/slack_app.py`.
- **Backend Changes:**
  - Add Prometheus query proxy: `GET /api/v1/integrations/prometheus/query?query={promql}`.
  - Add test connection endpoints: `POST /api/v1/integrations/{name}/test`.
- **Frontend Changes:**
  - Integrations Hub with connection status badges (`Connected ●`, `Not configured ○`) and credential test modals.
  - Engineer Mode PromQL query tester.
- **Acceptance Criteria:**
  - Configuring Prometheus enables real-time container metrics in Engineer Mode without disrupting Beginner Mode users.

---

### Phase 10: Security Hardening, Performance & E2E Validation
- **Goal:** Production hardening across authentication, authorization, rate limiting, and end-to-end integration tests.
- **Backend Changes:**
  - Add `X-OpsMind-API-Key` authentication middleware to mutating routes.
  - Implement 30-day auto-purge retention for probe snapshots.
  - Run database query indexing for high-volume telemetry tables.
- **Automated Testing Suite:**
  - E2E Lifecycle Test (`tests/test_e2e_lifecycle.py`):
    $$\text{Register App} \rightarrow \text{Probing Starts} \rightarrow \text{Endpoint Fails} \rightarrow \text{Incident Detected} \rightarrow \text{AI Investigates} \rightarrow \text{Dry-Run} \rightarrow \text{Approve} \rightarrow \text{Execute} \rightarrow \text{Verify Recovery} \rightarrow \text{Postmortem Stored}$$
- **Acceptance Criteria:**
  - Unauthenticated mutation requests return `401 Unauthorized`.
  - Full E2E test passes cleanly with 0 regressions across SQLite and DynamoDB modes.

---

## 8. File & Component Impact Matrix

| File Path | Action | Description & Rationale |
| :--- | :---: | :--- |
| `src/infrastructure/interfaces.py` | **MODIFY** | Add `ApplicationRecord`, `HealthProbeSnapshot`, and `RemediationAuditRecord` abstract protocols. |
| `src/infrastructure/local/repository.py` | **MODIFY** | Implement SQLite tables and CRUD operations for applications and probe history. |
| `src/infrastructure/aws/repository.py` | **MODIFY** | Implement DynamoDB item serialization and queries for applications. |
| `src/core/security.py` | **NEW** | Implement `SSRFValidator` with IP blacklist, DNS pre-resolution, and redirect destination checks. |
| `src/core/synthetic.py` | **NEW** | Implement `SyntheticHealthWorker` running asynchronous HTTP/HTTPS probes and failure tripwires. |
| `src/core/telemetry.py` | **NEW** | Implement `TelemetrySignal` normalization model. |
| `src/core/pipeline.py` | **MODIFY** | Ingest synthetic probe outages into the incident correlation engine. |
| `src/executor/runner.py` | **MODIFY** | Add post-execution automated verification probe loop and audit record persistence. |
| `src/llm/tools.py` | **NEW** | Implement read-only tool catalog for the AI ReAct agent. |
| `src/llm/copilot.py` | **NEW** | Implement conversational AI agent loop with LiteLLM tool calling. |
| `src/api/routes_applications.py` | **NEW** | Application CRUD endpoints (`/api/v1/applications`) and on-demand probing. |
| `src/api/routes_copilot.py` | **NEW** | Copilot conversation endpoint (`/api/v1/copilot/chat`). |
| `src/api/routes_remediation.py` | **NEW** | Remediation audit trail endpoints (`/api/v1/remediations/audit`). |
| `src/api/routes_integrations.py` | **NEW** | Integrations status, Prometheus PromQL proxy, and test connection endpoints. |
| `src/frontend/App.jsx` | **MODIFY** | Refactor into full SaaS routing structure with `AppShell`. |
| `src/frontend/components/AppShell.jsx` | **NEW** | Responsive navigation shell with collapsible sidebar and global top bar. |
| `src/frontend/components/TopBar.jsx` | **NEW** | Top bar with system health pill, incident count, and Beginner/Engineer toggle. |
| `src/frontend/components/Sidebar.jsx` | **NEW** | Clean 240px navigation sidebar. |
| `src/frontend/pages/OverviewPage.jsx` | **NEW** | High-level fleet overview with 3-second status clarity. |
| `src/frontend/pages/ApplicationsPage.jsx` | **NEW** | Application catalog and 4-step onboarding modal. |
| `src/frontend/pages/ApplicationDetailPage.jsx` | **NEW** | Application health hero, native latency sparkline, and deployment feed. |
| `src/frontend/pages/IncidentsPage.jsx` | **NEW** | Human-readable incident cards with plain-English diagnosis. |
| `src/frontend/pages/IncidentDetailPage.jsx` | **NEW** | Investigation workspace with evidence cards, timeline, and safe fix drawer. |
| `src/frontend/pages/CopilotPage.jsx` | **NEW** | AI operations investigation workspace with safe action breadcrumbs. |
| `src/frontend/pages/RunbooksPage.jsx` | **NEW** | Remediation catalog with risk indicators and parameter preview. |
| `src/frontend/pages/KnowledgePage.jsx` | **NEW** | Semantic postmortem search and incident memory. |
| `src/frontend/pages/SettingsPage.jsx` | **NEW** | Integrations hub, searchable audit log table, developer docs. |
| `static/style.css` | **MODIFY** | Design tokens, 8px grid, typography, status colors, and responsive utilities. |
| `tests/test_ssrf.py` | **NEW** | Unit tests for IP blacklist and DNS re-resolution validation. |
| `tests/test_synthetic.py` | **NEW** | Unit tests for async health worker and consecutive failure tripwires. |
| `tests/test_e2e_lifecycle.py` | **NEW** | Comprehensive end-to-end incident lifecycle test. |

---

## 9. Definition of Done (Mandatory for Every Phase)

No phase is considered complete simply because code compiles. Every phase requires:
1. **Implementation:** Clean, type-annotated code adhering to existing repository abstractions.
2. **Regression-Free:** Existing endpoints, Drain3 clustering, and guarded runbooks continue working.
3. **Automated Tests:** Comprehensive unit and integration test coverage (`pytest`).
4. **Code Quality:** Passes `ruff check .` with zero warnings.
5. **Frontend Build:** Pre-bundled via `npm run build` with zero errors.
6. **Security Validation:** Input validation and SSRF/authorization checks verified.
7. **Phase Report:** Formal delivery report containing:
   - `IMPLEMENTED`
   - `TESTED`
   - `NOT IMPLEMENTED`
   - `KNOWN LIMITATIONS`
   - `NEXT PHASE`
8. **User Gate:** Explicit user approval before advancing to the subsequent phase.

---

## 10. Execution Readiness Checklist

- [x] Codebase inspected and audited against ground truth.
- [x] Working prototype features cataloged and preserved.
- [x] SSRF security architecture specified.
- [x] Dual-mode UI (Beginner / Engineer) specified.
- [x] AI ReAct read-only tool catalog defined.
- [x] Remediation trust and verification loop designed.
- [x] Phased implementation roadmap established (Phases 0 through 10).
- [ ] **Awaiting User Review and Approval to begin Phase 0.**
