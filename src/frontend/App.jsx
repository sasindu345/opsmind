import React, { useState, useEffect, useMemo } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "./components/AppShell";
import { OverviewPage } from "./pages/OverviewPage";
import { ApplicationsPage } from "./pages/ApplicationsPage";

// ==============================================================================
// Preset Incident Scenarios for Interactive Triage Playground
// ==============================================================================
const PRESET_SCENARIOS = [
  {
    id: "oom",
    title: "JVM OutOfMemory Crash",
    service: "checkout-api",
    env: "production",
    tag: "High Memory",
    logs: [
      "2026-09-12T12:00:01Z [ERROR] Container checkout-api-7f89b terminated with exit code 137 (OOMKilled)",
      "2026-09-12T12:00:02Z [WARN] JVM heap memory allocated: 510MB / 512MB threshold exceeded",
      "2026-09-12T12:00:03Z [ERROR] java.lang.OutOfMemoryError: Java heap space",
      "2026-09-12T12:00:04Z [ERROR] Readiness probe failed for pod checkout-api-7f89b: Connection refused",
      "2026-09-12T12:00:05Z [INFO] Kubernetes node ip-10-0-1-42 invoked oom-killer on task 9184",
    ].join("\n"),
  },
  {
    id: "db_pool",
    title: "HikariCP DB Pool Exhaustion",
    service: "auth-service",
    env: "production",
    tag: "Database",
    logs: [
      "2026-09-12T12:05:01Z [WARN] HikariCP - Connection pool exhausted (max: 50, active: 50, waiting: 120)",
      "2026-09-12T12:05:05Z [ERROR] HTTP 504 Gateway Timeout on POST /api/v1/auth/login",
      "2026-09-12T12:05:07Z [ERROR] ConnectionTimeoutException: Timed out waiting for pooled connection after 30000ms",
      "2026-09-12T12:05:10Z [WARN] PostgreSQL slow query log: SELECT * FROM sessions WHERE token = $1 took 8420ms",
    ].join("\n"),
  },
  {
    id: "redis_latency",
    title: "Redis Cluster Saturation",
    service: "cache-gateway",
    env: "production",
    tag: "Cache & Network",
    logs: [
      "2026-09-12T12:10:00Z [WARN] Redis latency spike detected: P99 response time exceeded 250ms (baseline: 4ms)",
      "2026-09-12T12:10:02Z [ERROR] JedisConnectionException: Unexpected end of stream from redis-cluster-node-3:6379",
      "2026-09-12T12:10:04Z [ERROR] CircuitBreaker OPEN for Redis cache read operations - fallback to primary DB triggered",
      "2026-09-12T12:10:06Z [CRITICAL] 502 Bad Gateway rate surged by +340% over 2 minutes",
    ].join("\n"),
  },
  {
    id: "k8s_crashloop",
    title: "CrashLoopBackOff Deployment",
    service: "payment-worker",
    env: "staging",
    tag: "Kubernetes",
    logs: [
      "2026-09-12T12:15:01Z [INFO] Pulling image registry.internal/payment-worker:v2.4.1-patch",
      "2026-09-12T12:15:04Z [ERROR] ConfigurationError: Required environment variable STRIPE_API_SECRET is unset or empty",
      "2026-09-12T12:15:05Z [FATAL] Application failed to bootstrap. Exiting process with code 1",
      "2026-09-12T12:15:08Z [WARN] Back-off 40s restarting failed container payment-worker in pod payment-worker-8b4cf",
    ].join("\n"),
  },
];

// ==============================================================================
// Safe Runbooks Catalog
// ==============================================================================
const RUNBOOKS_CATALOG = [
  {
    id: "rollback-deployment",
    name: "Rollback Deployment",
    risk: "MEDIUM",
    riskClass: "risk-medium",
    desc: "Rolls back a Kubernetes or ECS service deployment to its previous stable revision.",
    command: "kubectl rollout undo deployment/{service} -n {namespace}",
    defaultService: "checkout-api",
    defaultNamespace: "default",
  },
  {
    id: "restart-service",
    name: "Graceful Service Restart",
    risk: "LOW",
    riskClass: "risk-low",
    desc: "Initiates a rolling restart of all application instances or pods in target service.",
    command: "kubectl rollout restart deployment/{service} -n {namespace}",
    defaultService: "checkout-api",
    defaultNamespace: "default",
  },
  {
    id: "scale-workload",
    name: "Scale Workload Replicas",
    risk: "MEDIUM",
    riskClass: "risk-medium",
    desc: "Adjusts replica count (1 to 20) to immediately relieve CPU, memory, or thread exhaustion.",
    command: "kubectl scale deployment/{service} --replicas={replicas} -n {namespace}",
    defaultService: "payment-worker",
    defaultNamespace: "default",
  },
  {
    id: "clear-cache",
    name: "Async Redis Cache Flush",
    risk: "HIGH",
    riskClass: "risk-high",
    desc: "Flushes transient Redis cache keyspace asynchronously to purge corrupt keys or poison cache entries.",
    command: "redis-cli -h {host} -p 6379 FLUSHDB ASYNC",
    defaultService: "cache-gateway",
    defaultNamespace: "default",
  },
];

// ==============================================================================
// Main OpsMind Dashboard Application Component
// ==============================================================================
export function App() {
  // Navigation (default to overview)
  const [activeTab, setActiveTab] = useState("overview");

  // System & Environment Status
  const [systemStatus, setSystemStatus] = useState({
    status: "ok",
    app_env: "production",
    llm: { model: "anthropic.claude-3-haiku", configured: true, provider: "bedrock" },
    slack_enabled: false,
  });

  // Hosting URL detection
  const detectedOrigin = typeof window !== "undefined" && window.location.origin
    ? window.location.origin
    : "http://localhost:8000";
  const [customHostUrl, setCustomHostUrl] = useState(detectedOrigin);
  const activeBaseUrl = (customHostUrl || detectedOrigin).replace(/\/+$/, "");

  // Applications Inventory State
  const [applications, setApplications] = useState([]);
  const [isLoadingApps, setIsLoadingApps] = useState(true);

  // Beginner vs Engineer Mode State
  const [mode, setMode] = useState(() => {
    if (typeof window !== "undefined" && window.localStorage) {
      return window.localStorage.getItem("opsmind_mode") || "beginner";
    }
    return "beginner";
  });

  const handleModeToggle = (newMode) => {
    setMode(newMode);
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.setItem("opsmind_mode", newMode);
    }
    showToast(`Switched to ${newMode === "beginner" ? "Beginner Mode (Simplified)" : "Engineer Mode (Full Diagnostics)"}`, "info");
  };

  const fetchApplications = async () => {
    setIsLoadingApps(true);
    try {
      const res = await fetch(`${activeBaseUrl}/api/v1/applications`);
      if (res.ok) {
        const data = await res.json();
        setApplications(data);
      }
    } catch (err) {
      console.error("Failed to fetch applications:", err);
    } finally {
      setIsLoadingApps(false);
    }
  };

  // Incidents Stream State
  const [incidents, setIncidents] = useState([]);
  const [isLoadingIncidents, setIsLoadingIncidents] = useState(true);
  const [serviceFilter, setServiceFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  // Triage Playground State
  const [triageService, setTriageService] = useState("checkout-api");
  const [triageEnv, setTriageEnv] = useState("production");
  const [triageLogs, setTriageLogs] = useState(PRESET_SCENARIOS[0].logs);
  const [isTriaging, setIsTriaging] = useState(false);
  const [triageResult, setTriageResult] = useState(null);

  // Remediation Modal State
  const [modalOpen, setModalOpen] = useState(false);
  const [activeRunbook, setActiveRunbook] = useState(RUNBOOKS_CATALOG[0]);
  const [selectedIncidentId, setSelectedIncidentId] = useState("adhoc-action");
  const [modalService, setModalService] = useState("checkout-api");
  const [modalNamespace, setModalNamespace] = useState("default");
  const [modalReplicas, setModalReplicas] = useState("3");
  const [dryRunPlan, setDryRunPlan] = useState(null);
  const [isGeneratingDryRun, setIsGeneratingDryRun] = useState(false);
  const [approverEmail, setApproverEmail] = useState("lead-sre@company.com");
  const [isExecutingPlan, setIsExecutingPlan] = useState(false);

  // Postmortem Report Modal State
  const [postmortemModalOpen, setPostmortemModalOpen] = useState(false);
  const [postmortemContent, setPostmortemContent] = useState("");
  const [postmortemLoading, setPostmortemLoading] = useState(false);
  const [postmortemIncidentId, setPostmortemIncidentId] = useState("");

  // Incident Memory (RAG) State
  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryResults, setMemoryResults] = useState(null);
  const [isSearchingMemory, setIsSearchingMemory] = useState(false);

  // Toasts
  const [toasts, setToasts] = useState([]);

  const showToast = (message, type = "success") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  };

  const copyToClipboard = (text, label) => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text);
      showToast(`${label || "Content"} copied to clipboard!`, "success");
    }
  };

  // API Call: Fetch System Status
  const fetchSystemStatus = async () => {
    try {
      const res = await fetch(`${activeBaseUrl}/readyz`);
      if (res.ok) {
        const data = await res.json();
        setSystemStatus(data);
      }
    } catch {
      // Fallback
    }
  };

  // API Call: Fetch Incidents Stream
  const fetchIncidents = async () => {
    try {
      const res = await fetch(`${activeBaseUrl}/api/v1/incidents?limit=50`);
      if (res.ok) {
        const data = await res.json();
        setIncidents(data);
      }
    } catch {
      // Offline fallback
    } finally {
      setIsLoadingIncidents(false);
    }
  };

  // Periodic polling
  useEffect(() => {
    fetchSystemStatus();
    fetchIncidents();
    fetchApplications();
    const interval = setInterval(() => {
      fetchIncidents();
      fetchApplications();
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  // Filtered incidents
  const filteredIncidents = useMemo(() => {
    return incidents.filter((inc) => {
      const matchService = !serviceFilter || (inc.service || "").toLowerCase().includes(serviceFilter.toLowerCase());
      const matchStatus = !statusFilter || (inc.status || "").toLowerCase() === statusFilter.toLowerCase();
      return matchService && matchStatus;
    });
  }, [incidents, serviceFilter, statusFilter]);

  const activeIncidentsCount = useMemo(() => {
    return incidents.filter((i) => i.status !== "resolved").length;
  }, [incidents]);

  // Actions on incidents
  const handleAcknowledge = async (incidentId) => {
    try {
      const res = await fetch(`/api/v1/incidents/${incidentId}/acknowledge`, { method: "POST" });
      if (res.ok) {
        showToast("Incident acknowledged by operator.", "success");
        fetchIncidents();
      } else {
        showToast("Failed to acknowledge incident.", "error");
      }
    } catch (err) {
      showToast("Network error: " + err.message, "error");
    }
  };

  const handleResolve = async (incidentId) => {
    try {
      const res = await fetch(`/api/v1/incidents/${incidentId}/resolve`, { method: "POST" });
      if (res.ok) {
        showToast("Incident marked as RESOLVED.", "success");
        fetchIncidents();
      } else {
        showToast("Failed to resolve incident.", "error");
      }
    } catch (err) {
      showToast("Network error: " + err.message, "error");
    }
  };

  const handleOpenRemediation = (runbook, incidentId = "adhoc-action", service = "") => {
    setActiveRunbook(runbook);
    setSelectedIncidentId(incidentId);
    setModalService(service || runbook.defaultService);
    setModalNamespace(runbook.defaultNamespace);
    setDryRunPlan(null);
    setModalOpen(true);
  };

  const handleOpenPostmortem = async (incidentId) => {
    setPostmortemIncidentId(incidentId);
    setPostmortemModalOpen(true);
    setPostmortemLoading(true);
    setPostmortemContent("");

    try {
      const res = await fetch(`/api/v1/incidents/${incidentId}/postmortem`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        if (data.report_markdown) {
          setPostmortemContent(data.report_markdown);
        } else if (data.access_url) {
          try {
            const reportRes = await fetch(data.access_url);
            if (reportRes.ok) {
              const text = await reportRes.text();
              setPostmortemContent(text);
            } else {
              setPostmortemContent(`Postmortem report is available at: ${data.access_url}`);
            }
          } catch {
            setPostmortemContent(`Postmortem report is stored at: ${data.access_url}`);
          }
        } else {
          setPostmortemContent(JSON.stringify(data, null, 2));
        }
      } else {
        setPostmortemContent("No markdown report generated yet. Triaging or remediating this incident will compile full root cause data.");
      }
    } catch (err) {
      setPostmortemContent("Failed to load postmortem: " + err.message);
    } finally {
      setPostmortemLoading(false);
    }
  };

  // Submit Triage Playground
  const handleRunTriage = async () => {
    if (!triageLogs.trim()) {
      showToast("Please provide or load log lines first!", "error");
      return;
    }

    const logLines = triageLogs.split("\n").map((l) => l.trim()).filter(Boolean);
    setIsTriaging(true);

    try {
      const res = await fetch("/api/v1/analyze/logs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          service: triageService,
          environment: triageEnv,
          logs: logLines,
          generate_report: true,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Analysis request failed");
      }

      const data = await res.json();
      setTriageResult(data);
      showToast("AI Root-Cause Analysis Completed!", "success");
      fetchIncidents();
    } catch (err) {
      showToast("Triage Error: " + err.message, "error");
    } finally {
      setIsTriaging(false);
    }
  };

  // Safe Runbook Dry-Run
  const handleGenerateDryRun = async () => {
    setIsGeneratingDryRun(true);
    try {
      const res = await fetch(`/api/v1/incidents/${selectedIncidentId}/remediation/dry-run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          runbook_id: activeRunbook.id,
          parameters: {
            service: modalService,
            namespace: modalNamespace,
            replicas: parseInt(modalReplicas, 10) || 3,
            host: modalService + ".internal",
            port: 6379,
          },
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Dry-run generation failed");
      }

      const plan = await res.json();
      setDryRunPlan(plan);
      showToast("Dry-Run command verified by Guarded Engine", "success");
    } catch (err) {
      showToast("Dry-Run Error: " + err.message, "error");
    } finally {
      setIsGeneratingDryRun(false);
    }
  };

  // Safe Runbook Execution
  const handleApproveAndExecute = async () => {
    if (!dryRunPlan) return;
    setIsExecutingPlan(true);

    try {
      const res = await fetch(`/api/v1/incidents/${selectedIncidentId}/remediation/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_id: dryRunPlan.plan_id,
          approved_by: approverEmail || "sre-operator@company.com",
          reason: "Approved via OpsMind React Console",
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Execution failed");
      }

      const execResult = await res.json();
      showToast(`Remediation executed! (ID: ${execResult.execution_id.slice(0, 8)})`, "success");
      setModalOpen(false);
      fetchIncidents();
    } catch (err) {
      showToast("Remediation execution error: " + err.message, "error");
    } finally {
      setIsExecutingPlan(false);
    }
  };

  // Test Webhook Trigger
  const handleSendTestWebhook = async (type) => {
    try {
      let endpoint = "";
      let payload = {};

      if (type === "github") {
        endpoint = "/api/v1/webhooks/github";
        payload = {
          ref: "refs/heads/main",
          repository: { full_name: "company/ecommerce-core", html_url: "https://github.com/company/ecommerce-core" },
          head_commit: {
            id: "7a89f0c29b4",
            message: "feat: update memory allocation and checkout cart caching",
            author: { name: "DevOps Engineer", email: "devops@company.com" },
            timestamp: new Date().toISOString(),
          },
        };
      } else if (type === "prometheus") {
        endpoint = "/api/v1/webhooks/prometheus";
        payload = {
          version: "4",
          status: "firing",
          receiver: "opsmind-webhook",
          alerts: [
            {
              status: "firing",
              labels: {
                alertname: "KubePodCrashLooping",
                service: "checkout-api",
                severity: "critical",
                namespace: "production",
              },
              annotations: {
                summary: "Pod checkout-api is restarting frequently",
                description: "Container checkout-api in namespace production has restarted 7 times in 10 minutes.",
              },
              startsAt: new Date().toISOString(),
            },
          ],
        };
      } else {
        endpoint = "/api/v1/webhooks/cloudwatch";
        payload = {
          Type: "Notification",
          MessageId: "cw-msg-" + Date.now(),
          TopicArn: "arn:aws:sns:us-east-1:123456789012:opsmind-alerts",
          Subject: "ALARM: HighCPUUtilization-production",
          Message: JSON.stringify({
            AlarmName: "HighCPUUtilization-production",
            NewStateValue: "ALARM",
            NewStateReason: "Threshold Crossed: 1 out of 1 datapoints [92.4%] was greater than threshold [85.0%]",
            StateChangeTime: new Date().toISOString(),
          }),
        };
      }

      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        showToast(`Sent test ${type.toUpperCase()} webhook! Ingestion successful.`, "success");
        setTimeout(fetchIncidents, 1000);
      } else {
        showToast(`Webhook responded with status ${res.status}`, "error");
      }
    } catch (err) {
      showToast("Webhook ping failed: " + err.message, "error");
    }
  };

  // Search Incident Memory
  const handleSearchMemory = async () => {
    if (!memoryQuery.trim()) return;
    setIsSearchingMemory(true);

    try {
      const res = await fetch("/api/v1/incidents?limit=100");
      if (!res.ok) throw new Error("Could not fetch memory index");
      const list = await res.json();

      const q = memoryQuery.toLowerCase();
      const terms = q.split(/\s+/).filter(Boolean);

      const scored = list
        .map((item) => {
          const text = `${item.service} ${item.title} ${item.probable_cause} ${item.status}`.toLowerCase();
          let score = 0;
          terms.forEach((t) => {
            if (text.includes(t)) score += 25;
          });
          if (item.probable_cause && item.probable_cause.toLowerCase().includes(q)) score += 40;
          return { item, score: Math.min(score, 98) };
        })
        .filter((entry) => entry.score > 0)
        .sort((a, b) => b.score - a.score);

      setMemoryResults(scored);
    } catch (err) {
      showToast("Search failed: " + err.message, "error");
    } finally {
      setIsSearchingMemory(false);
    }
  };

  return (
    <div className="opsmind-root dark-theme">
      <AppShell
        activeTab={activeTab}
        onSelectTab={(tab) => setActiveTab(tab)}
        systemStatus={systemStatus}
        incidentCount={activeIncidentsCount}
        applicationCount={applications.length}
        mode={mode}
        onModeToggle={handleModeToggle}
        onOpenSearch={() => {}}
      >
        {/* ================================================================ */}
        {/* TAB 0: SYSTEM OVERVIEW */}
        {/* ================================================================ */}
        {activeTab === "overview" && (
          <OverviewPage
            applications={applications}
            incidents={incidents}
            onNavigate={(tab) => setActiveTab(tab)}
            systemStatus={systemStatus}
            mode={mode}
          />
        )}

        {/* ================================================================ */}
        {/* TAB 0.5: APPLICATION FLEET */}
        {/* ================================================================ */}
        {activeTab === "applications" && (
          <ApplicationsPage
            applications={applications}
            isLoading={isLoadingApps}
            onRefresh={fetchApplications}
            baseUrl={activeBaseUrl}
            mode={mode}
            onSelectApplication={(id) => {
              setServiceFilter(id);
              setActiveTab("incidents");
            }}
          />
        )}

        {/* ================================================================ */}
        {/* TAB 1: LIVE INCIDENTS */}
        {/* ================================================================ */}
        {activeTab === "incidents" && (
            <div className="tab-pane active">
              <div className="section-header">
                <div>
                  <h1 className="page-title">Live Incident Stream</h1>
                  <p className="page-subtitle">
                    Real-time AI root-cause analysis, Drain3 pattern clusters, and guarded remediation.
                  </p>
                </div>
                <div className="header-filters">
                  <input
                    type="text"
                    className="input-search"
                    placeholder="Filter by service..."
                    value={serviceFilter}
                    onChange={(e) => setServiceFilter(e.target.value)}
                  />
                  <select
                    className="select-filter"
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                  >
                    <option value="">All Statuses</option>
                    <option value="open">Open</option>
                    <option value="acknowledged">Acknowledged</option>
                    <option value="resolved">Resolved</option>
                  </select>
                  <button className="btn btn-secondary" onClick={fetchIncidents} title="Refresh incidents">
                    <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Refresh
                  </button>
                </div>
              </div>

              {isLoadingIncidents ? (
                <div className="loading-spinner-wrapper">
                  <div className="spinner"></div>
                  <p>Scanning incident repository & telemetry...</p>
                </div>
              ) : filteredIncidents.length === 0 ? (
                <div className="empty-state-placeholder glass-panel">
                  <svg width="48" height="48" fill="none" stroke="#475569" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <p>No incidents match your filter. The system is operating cleanly!</p>
                  <button className="btn btn-primary mt-3" onClick={() => setActiveTab("triage")}>
                    Simulate a Test Incident
                  </button>
                </div>
              ) : (
                <div className="incidents-grid">
                  {filteredIncidents.map((inc) => {
                    const sev = (inc.severity || "medium").toLowerCase();
                    const status = (inc.status || "open").toLowerCase();
                    const confidencePct = Math.round((inc.confidence || 0.85) * 100);
                    const timeStr = inc.created_at
                      ? new Date(inc.created_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" })
                      : "Just now";

                    return (
                      <div key={inc.incident_id} className={`incident-card sev-${sev}`}>
                        <div className="incident-header-row">
                          <div className="incident-title-area">
                            <span className={`sev-badge badge-${sev}`}>{inc.severity}</span>
                            <span className="incident-title">{inc.title || "Incident Report"}</span>
                            <span className="incident-service-tag">{inc.service}</span>
                            {inc.deployment_sha && (
                              <span className="incident-service-tag" title={inc.deployment_sha}>
                                commit {String(inc.deployment_sha).slice(0, 7)}
                              </span>
                            )}
                          </div>
                          <div className="incident-meta-right">
                            <span className={`status-tag status-${status}`}>{inc.status}</span>
                            <span className="incident-time">{timeStr}</span>
                          </div>
                        </div>

                        <div className="incident-body">
                          <div className="cause-line">
                            <strong className="text-cyan">Probable Cause:</strong>{" "}
                            <span>{inc.probable_cause || "Analyzing telemetry signals..."}</span>
                          </div>
                          {inc.evidence && inc.evidence.length > 0 && (
                            <div className="evidence-preview">
                              <span className="text-dim">Clustered Pattern: </span>
                              <code>{inc.evidence[0]}</code>
                            </div>
                          )}
                        </div>

                        <div className="incident-footer-row">
                          <div className="confidence-meter">
                            <span>AI Confidence: {confidencePct}%</span>
                            <div className="meter-bar">
                              <div className="meter-fill" style={{ width: `${confidencePct}%` }}></div>
                            </div>
                          </div>

                          <div className="incident-action-btns">
                            {status === "open" && (
                              <button
                                className="btn btn-secondary btn-sm"
                                onClick={() => handleAcknowledge(inc.incident_id)}
                              >
                                Acknowledge
                              </button>
                            )}
                            {status !== "resolved" && (
                              <button
                                className="btn btn-secondary btn-sm text-emerald"
                                onClick={() => handleResolve(inc.incident_id)}
                              >
                                Resolve
                              </button>
                            )}
                            <button
                              className="btn btn-primary btn-sm"
                              onClick={() => handleOpenRemediation(RUNBOOKS_CATALOG[1], inc.incident_id, inc.service)}
                            >
                              Remediate
                            </button>
                            <button
                              className="btn btn-secondary btn-sm"
                              onClick={() => handleOpenPostmortem(inc.incident_id)}
                            >
                              Postmortem
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* ================================================================ */}
          {/* TAB 2: TRIAGE PLAYGROUND */}
          {/* ================================================================ */}
          {activeTab === "triage" && (
            <div className="tab-pane active">
              <div className="section-header">
                <div>
                  <h1 className="page-title">Interactive AI Triage Playground</h1>
                  <p className="page-subtitle">
                    Paste raw logs, trigger crash presets, and let OpsMind extract Drain3 clusters and AI diagnoses.
                  </p>
                </div>
              </div>

              {/* Scenario Preset Chips */}
              <div className="scenario-chips-container glass-panel">
                <span className="scenario-chips-label">1-Click Crash Presets:</span>
                <div className="chips-row">
                  {PRESET_SCENARIOS.map((sc) => (
                    <button
                      key={sc.id}
                      className="scenario-chip"
                      onClick={() => {
                        setTriageService(sc.service);
                        setTriageEnv(sc.env);
                        setTriageLogs(sc.logs);
                      }}
                    >
                      <span className="chip-tag">{sc.tag}</span>
                      <span className="chip-title">{sc.title}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="triage-layout">
                {/* Left Column: Form */}
                <div className="card glass-panel triage-form-card">
                  <h2 className="card-title">1. Provide Incident Telemetry</h2>
                  <div className="form-row">
                    <div className="form-group flex-1">
                      <label>Target Service Name</label>
                      <input
                        type="text"
                        className="form-control"
                        value={triageService}
                        onChange={(e) => setTriageService(e.target.value)}
                      />
                    </div>
                    <div className="form-group flex-1">
                      <label>Deployment Environment</label>
                      <select
                        className="form-control"
                        value={triageEnv}
                        onChange={(e) => setTriageEnv(e.target.value)}
                      >
                        <option value="production">Production</option>
                        <option value="staging">Staging</option>
                        <option value="development">Development</option>
                      </select>
                    </div>
                  </div>

                  <div className="form-group">
                    <label>Raw Crash Logs & Stacktraces (one message per line)</label>
                    <textarea
                      className="form-control code-editor"
                      rows="9"
                      value={triageLogs}
                      onChange={(e) => setTriageLogs(e.target.value)}
                      placeholder="Paste stack traces, stdout lines, or container logs..."
                    />
                  </div>

                  <button
                    className="btn btn-primary btn-lg w-full"
                    disabled={isTriaging}
                    onClick={handleRunTriage}
                  >
                    {isTriaging ? (
                      <>
                        <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
                        Clustering Patterns & Calling Bedrock AI...
                      </>
                    ) : (
                      <>
                        <svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                        </svg>
                        Analyze Root Cause with AI
                      </>
                    )}
                  </button>
                </div>

                {/* Right Column: AI Diagnosis Output */}
                <div className="card glass-panel triage-result-card">
                  <h2 className="card-title">2. AI Diagnosis & Pattern Clustering</h2>
                  {!triageResult ? (
                    <div className="empty-state-placeholder">
                      <svg width="48" height="48" fill="none" stroke="#475569" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      <p>Select a scenario preset on the left and click "Analyze Root Cause with AI".</p>
                    </div>
                  ) : (
                    <div className="triage-output-content">
                      <div className="verdict-banner">
                        <div className="verdict-header text-amber">
                          {triageResult.analysis?.severity?.toUpperCase()} SEVERITY •{" "}
                          {Math.round((triageResult.analysis?.confidence || 0.8) * 100)}% CONFIDENCE
                        </div>
                        <div className="verdict-cause">
                          <strong>Probable Cause:</strong> {triageResult.analysis?.probable_cause}
                        </div>
                        <div className="verdict-summary">{triageResult.analysis?.summary}</div>
                      </div>

                      <div className="triage-section-block">
                        <h4 className="section-small-title">
                          Drain3 Log Clusters Identified ({triageResult.clusters_identified || 0}):
                        </h4>
                        <div className="pattern-cluster-box">
                          {(triageResult.observed_evidence || []).map((ev, i) => (
                            <div key={i} className="cluster-line">• {ev}</div>
                          ))}
                        </div>
                      </div>

                      <div className="triage-section-block">
                        <h4 className="section-small-title">Recommended Remediation Steps:</h4>
                        <ul className="remediation-steps-list">
                          {(triageResult.analysis?.remediation_actions || []).map((action, i) => (
                            <li key={i}>{action}</li>
                          ))}
                        </ul>
                      </div>

                      <div className="mt-3">
                        <button
                          className="btn btn-primary w-full"
                          onClick={() => {
                            setActiveTab("remediation");
                          }}
                        >
                          Open Guarded Runbooks ➔
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ================================================================ */}
          {/* TAB 3: CONNECT REPOSITORY & WEBHOOKS (LIVE HOST VERSION) */}
          {/* ================================================================ */}
          {activeTab === "connect" && (
            <div className="tab-pane active">
              <div className="section-header">
                <div>
                  <h1 className="page-title">Connect Developer Tools & Webhooks</h1>
                  <p className="page-subtitle">
                    Integrate GitHub, Prometheus Alertmanager, and CloudWatch alerts with OpsMind using your live host endpoint.
                  </p>
                </div>
              </div>

              {/* HOST DETECTION CONFIGURATION BAR */}
              <div className="card glass-panel host-config-banner">
                <div className="host-banner-left">
                  <div className="host-status-indicator">
                    <span className="metric-dot live"></span>
                    <strong>Active Hosting Endpoint</strong>
                  </div>
                  <div className="host-url-display">
                    <code>{activeBaseUrl}</code>
                    <button
                      className="btn-copy"
                      onClick={() => copyToClipboard(activeBaseUrl, "Host Base URL")}
                    >
                      Copy Host
                    </button>
                  </div>
                </div>

                <div className="host-banner-right">
                  <label className="host-override-label">
                    Custom Domain / Reverse Proxy Override (Optional):
                  </label>
                  <input
                    type="text"
                    className="form-control form-control-sm"
                    placeholder="e.g. https://opsmind.yourcompany.com"
                    value={customHostUrl}
                    onChange={(e) => setCustomHostUrl(e.target.value)}
                  />
                  <small className="text-dim">
                    All webhook URLs and code snippets below adapt immediately to this URL.
                  </small>
                </div>
              </div>

              <div className="connect-grid">
                {/* Integration Card 1: GitHub Webhook */}
                <div className="card glass-panel integration-card">
                  <div className="integration-header">
                    <div className="integration-icon gh-icon">
                      <svg width="24" height="24" fill="currentColor" viewBox="0 0 24 24">
                        <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="integration-title">GitHub Repository Webhook</h3>
                      <p className="integration-sub">Auto-correlate git commits and deploy onsets to outages.</p>
                    </div>
                  </div>

                  <div className="setup-steps">
                    <div className="step-item">
                      <span className="step-num">1</span>
                      <span>Go to GitHub Repo ➔ <strong>Settings</strong> ➔ <strong>Webhooks</strong> ➔ <strong>Add webhook</strong></span>
                    </div>

                    <div className="step-item">
                      <span className="step-num">2</span>
                      <span>Paste Payload URL:</span>
                    </div>
                    <div className="code-box">
                      <code>{`${activeBaseUrl}/api/v1/webhooks/github`}</code>
                      <button
                        className="btn-copy"
                        onClick={() => copyToClipboard(`${activeBaseUrl}/api/v1/webhooks/github`, "GitHub Payload URL")}
                      >
                        Copy URL
                      </button>
                    </div>

                    <div className="step-item">
                      <span className="step-num">3</span>
                      <span>Content type: <code>application/json</code> • Events: <strong>Pushes</strong> & <strong>Deployments</strong></span>
                    </div>

                    <div className="integration-card-actions">
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleSendTestWebhook("github")}
                      >
                        ⚡ Send Sample GitHub Push Webhook
                      </button>
                    </div>
                  </div>
                </div>

                {/* Integration Card 2: Prometheus Alertmanager */}
                <div className="card glass-panel integration-card">
                  <div className="integration-header">
                    <div className="integration-icon prom-icon">
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#F97316" strokeWidth="2">
                        <circle cx="12" cy="12" r="10" />
                        <path d="M12 6v6l4 2" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="integration-title">Prometheus Alertmanager</h3>
                      <p className="integration-sub">Stream threshold breaches & metric anomalies directly.</p>
                    </div>
                  </div>

                  <div className="setup-steps">
                    <div className="step-item">
                      <span className="step-num">1</span>
                      <span>Add this receiver configuration into your <code>alertmanager.yml</code>:</span>
                    </div>

                    <div className="code-box multi-line">
                      <pre>
{`receivers:
  - name: 'opsmind-alerts'
    webhook_configs:
      - url: '${activeBaseUrl}/api/v1/webhooks/prometheus'
        send_resolved: true`}
                      </pre>
                      <button
                        className="btn-copy"
                        onClick={() =>
                          copyToClipboard(
                            `receivers:\n  - name: 'opsmind-alerts'\n    webhook_configs:\n      - url: '${activeBaseUrl}/api/v1/webhooks/prometheus'\n        send_resolved: true`,
                            "Prometheus YAML"
                          )
                        }
                      >
                        Copy YAML
                      </button>
                    </div>

                    <div className="integration-card-actions">
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleSendTestWebhook("prometheus")}
                      >
                        ⚡ Send Sample Prometheus Firing Alert
                      </button>
                    </div>
                  </div>
                </div>

                {/* Integration Card 3: AWS CloudWatch Alarms */}
                <div className="card glass-panel integration-card">
                  <div className="integration-header">
                    <div className="integration-icon aws-icon">
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#F59E0B" strokeWidth="2">
                        <path d="M3 15h18M3 9h18M9 21V3m6 18V3" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="integration-title">AWS CloudWatch / SNS Alerts</h3>
                      <p className="integration-sub">Capture EC2, ECS, or Lambda threshold alarms via SNS HTTPS.</p>
                    </div>
                  </div>

                  <div className="setup-steps">
                    <div className="step-item">
                      <span className="step-num">1</span>
                      <span>Create an AWS SNS Topic ➔ Create Subscription ➔ Protocol: <strong>HTTPS</strong></span>
                    </div>

                    <div className="step-item">
                      <span className="step-num">2</span>
                      <span>Subscription Endpoint:</span>
                    </div>
                    <div className="code-box">
                      <code>{`${activeBaseUrl}/api/v1/webhooks/cloudwatch`}</code>
                      <button
                        className="btn-copy"
                        onClick={() => copyToClipboard(`${activeBaseUrl}/api/v1/webhooks/cloudwatch`, "CloudWatch SNS URL")}
                      >
                        Copy URL
                      </button>
                    </div>

                    <div className="step-item">
                      <span className="step-num">3</span>
                      <span>OpsMind automatically confirms the SNS Subscription URL upon receiving AWS handshake.</span>
                    </div>

                    <div className="integration-card-actions">
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleSendTestWebhook("cloudwatch")}
                      >
                        ⚡ Send Sample CloudWatch Alarm
                      </button>
                    </div>
                  </div>
                </div>

                {/* Integration Card 4: Generic cURL / Custom Logs */}
                <div className="card glass-panel integration-card">
                  <div className="integration-header">
                    <div className="integration-icon generic-icon">
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#06B6D4" strokeWidth="2">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="integration-title">Direct Ingestion via cURL</h3>
                      <p className="integration-sub">Post logs, traces, or alarms directly from your scripts or CI/CD pipelines.</p>
                    </div>
                  </div>

                  <div className="setup-steps">
                    <div className="step-item">
                      <span className="step-num">1</span>
                      <span>Execute in your terminal or automation runner:</span>
                    </div>

                    <div className="code-box multi-line">
                      <pre>
{`curl -X POST "${activeBaseUrl}/api/v1/analyze/logs" \\
  -H "Content-Type: application/json" \\
  -d '{
    "service": "checkout-api",
    "environment": "production",
    "logs": [
      "Container terminated with exit code 137 (OOMKilled)",
      "Readiness probe failed on port 8080"
    ]
  }'`}
                      </pre>
                      <button
                        className="btn-copy"
                        onClick={() =>
                          copyToClipboard(
                            `curl -X POST "${activeBaseUrl}/api/v1/analyze/logs" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "service": "checkout-api",\n    "environment": "production",\n    "logs": [\n      "Container terminated with exit code 137 (OOMKilled)",\n      "Readiness probe failed on port 8080"\n    ]\n  }'`,
                            "cURL Command"
                          )
                        }
                      >
                        Copy cURL
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ================================================================ */}
          {/* TAB 4: GUARDED SAFE RUNBOOKS */}
          {/* ================================================================ */}
          {activeTab === "remediation" && (
            <div className="tab-pane active">
              <div className="section-header">
                <div>
                  <h1 className="page-title">Guarded Remediation Runbooks</h1>
                  <p className="page-subtitle">
                    Allowlist-only execution engine with strict parameter validation, dry-run previews, and immutable audit logs.
                  </p>
                </div>
              </div>

              <div className="runbooks-grid">
                {RUNBOOKS_CATALOG.map((rb) => (
                  <div key={rb.id} className="card glass-panel runbook-card">
                    <div className="runbook-header">
                      <span className={`risk-badge ${rb.riskClass}`}>{rb.risk} RISK</span>
                      <h3 className="runbook-name">{rb.name}</h3>
                    </div>
                    <p className="runbook-desc">{rb.desc}</p>
                    <div className="runbook-command-sample">
                      <code>{rb.command}</code>
                    </div>
                    <button
                      className="btn btn-primary w-full"
                      onClick={() => handleOpenRemediation(rb)}
                    >
                      Configure & Preview Dry-Run
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ================================================================ */}
          {/* TAB 5: INCIDENT MEMORY (RAG) */}
          {/* ================================================================ */}
          {activeTab === "memory" && (
            <div className="tab-pane active">
              <div className="section-header">
                <div>
                  <h1 className="page-title">Incident Memory & Knowledge Base (RAG)</h1>
                  <p className="page-subtitle">
                    Search historical outages and post-mortems using vector semantic similarity.
                  </p>
                </div>
              </div>

              <div className="card glass-panel memory-search-card">
                <div className="search-bar-row">
                  <input
                    type="text"
                    className="form-control flex-1"
                    placeholder="Search past incidents (e.g. 'OOMKilled memory peak', 'Redis connection timeout', 'HTTP 504')"
                    value={memoryQuery}
                    onChange={(e) => setMemoryQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleSearchMemory()}
                  />
                  <button
                    className="btn btn-primary"
                    onClick={handleSearchMemory}
                    disabled={isSearchingMemory}
                  >
                    {isSearchingMemory ? "Searching..." : "Semantic Search"}
                  </button>
                </div>
              </div>

              <div className="memory-results-container">
                {memoryResults === null ? (
                  <div className="empty-state-placeholder glass-panel">
                    <p className="text-dim">Enter symptoms or error messages above to search OpsMind historical knowledge.</p>
                  </div>
                ) : memoryResults.length === 0 ? (
                  <div className="empty-state-placeholder glass-panel">
                    <p className="text-dim">No historical incidents found matching your query.</p>
                  </div>
                ) : (
                  memoryResults.map(({ item, score }) => (
                    <div key={item.incident_id} className="glass-panel memory-result-card">
                      <div className="memory-card-header">
                        <div>
                          <strong className="text-cyan">[{item.service}]</strong>{" "}
                          <span className="font-semibold">{item.title || "Incident Report"}</span>
                        </div>
                        <div className="memory-card-meta">
                          <span className="score-badge">{score}% match</span>
                          <span className={`status-tag status-${item.status}`}>{item.status}</span>
                        </div>
                      </div>
                      <div className="memory-card-body">
                        <div>
                          <strong>Cause:</strong> {item.probable_cause}
                        </div>
                        {item.summary && <p className="text-dim text-sm mt-1">{item.summary}</p>}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {/* ================================================================ */}
          {/* TAB 6: ARCHITECTURE & OPERATING GUIDE */}
          {/* ================================================================ */}
          {activeTab === "architecture" && (
            <div className="tab-pane active">
              <div className="section-header">
                <div>
                  <h1 className="page-title">OpsMind System Architecture & Workflow</h1>
                  <p className="page-subtitle">
                    How OpsMind ingests alerts, correlates git changes, clusters patterns, and remediates incidents safely.
                  </p>
                </div>
              </div>

              <div className="architecture-grid">
                <div className="card glass-panel arch-card">
                  <div className="arch-step-badge">Phase 1</div>
                  <h3 className="arch-step-title">Multi-Signal Ingestion</h3>
                  <p className="arch-step-desc">
                    Captures logs, Prometheus metric breaches, AWS CloudWatch alarms, and GitHub push/deploy events via asynchronous webhooks and AWS SQS queues.
                  </p>
                  <div className="arch-tech-tags">
                    <span>FastAPI</span>
                    <span>AWS SQS</span>
                    <span>Webhooks</span>
                  </div>
                </div>

                <div className="card glass-panel arch-card">
                  <div className="arch-step-badge">Phase 2</div>
                  <h3 className="arch-step-title">Drain3 Pattern Clustering</h3>
                  <p className="arch-step-desc">
                    Compresses thousands of noisy log messages into clean structural templates in microseconds, stripping dynamic IDs and IPs to expose true underlying error patterns.
                  </p>
                  <div className="arch-tech-tags">
                    <span>Drain3</span>
                    <span>Regex Heuristics</span>
                    <span>Entropy Filter</span>
                  </div>
                </div>

                <div className="card glass-panel arch-card">
                  <div className="arch-step-badge">Phase 3</div>
                  <h3 className="arch-step-title">AI Root-Cause Diagnosis</h3>
                  <p className="arch-step-desc">
                    Feeds clustered templates, recent git commits, and telemetry to AWS Bedrock Claude 3 or Gemini. The model predicts the probable cause, blast radius, and confidence score.
                  </p>
                  <div className="arch-tech-tags">
                    <span>AWS Bedrock</span>
                    <span>Claude 3 Haiku</span>
                    <span>Google Gemini</span>
                  </div>
                </div>

                <div className="card glass-panel arch-card">
                  <div className="arch-step-badge">Phase 4</div>
                  <h3 className="arch-step-title">Guarded Safe Remediation</h3>
                  <p className="arch-step-desc">
                    Allows operators to preview generated runbook commands (Rollback, Restart, Scale) in a strict dry-run mode before signed approval and audited execution.
                  </p>
                  <div className="arch-tech-tags">
                    <span>Guarded Engine</span>
                    <span>Dry-Run Preview</span>
                    <span>Audit Trail</span>
                  </div>
                </div>
              </div>

              <div className="card glass-panel mt-4 p-4">
                <h3 className="text-lg font-semibold mb-2">Live AWS Infrastructure Topology</h3>
                <div className="topology-info-row">
                  <div>• <strong>Compute:</strong> AWS EC2 ARM64 (Ubuntu 24.04 LTS)</div>
                  <div>• <strong>Database:</strong> Amazon DynamoDB (Partition: incident_id)</div>
                  <div>• <strong>Async Queue:</strong> Amazon SQS & Dead Letter Queue (DLQ)</div>
                  <div>• <strong>Artifact Storage:</strong> Amazon S3 with 30-day lifecycle expiration</div>
                  <div>• <strong>AI Engine:</strong> AWS Bedrock (Claude 3 Haiku) / Gemini Flash</div>
                </div>
              </div>
            </div>
          )}

        {/* ================================================================ */}
        {/* TAB 7: AI OPERATIONS COPILOT */}
        {/* ================================================================ */}
        {activeTab === "copilot" && (
          <div className="tab-pane active">
            <div className="section-header">
              <div>
                <h1 className="page-title">AI Operations Copilot</h1>
                <p className="page-subtitle">
                  Ask natural-language questions about your application health, outages, and correlated deployments.
                </p>
              </div>
            </div>

            <div className="app-card" style={{ padding: "28px", maxWidth: "800px", margin: "0 auto", textAlign: "center" }}>
              <div style={{ fontSize: "2.4rem", marginBottom: "12px" }}>💬</div>
              <h2 style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--text-primary)", marginBottom: "8px" }}>
                Interactive AI Copilot Workspace
              </h2>
              <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem", marginBottom: "20px", lineHeight: 1.5 }}>
                OpsMind inspects active synthetic health probes, correlated deployments, and log error clusters to answer your operational questions with verified evidence.
              </p>

              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", justifyContent: "center", marginBottom: "20px" }}>
                {applications.slice(0, 3).map((a) => (
                  <button
                    key={a.app_id}
                    type="button"
                    className="btn btn-secondary"
                    style={{ fontSize: "0.78rem" }}
                    onClick={() => {
                      showToast(`Investigating ${a.name}...`, "info");
                    }}
                  >
                    Why is {a.name} {a.health_status === "healthy" ? "healthy?" : "degraded?"}
                  </button>
                ))}
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ fontSize: "0.78rem" }}
                  onClick={() => {
                    showToast("Scanning for recent deployments...", "info");
                  }}
                >
                  What changed in Production today?
                </button>
              </div>

              <div style={{ display: "flex", gap: "10px" }}>
                <input
                  type="text"
                  className="form-control"
                  placeholder="Ask OpsMind about service health, latency spikes, or errors..."
                />
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => {
                    showToast("Copilot query submitted", "info");
                  }}
                >
                  Ask Copilot
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ================================================================ */}
        {/* TAB 8: REMEDIATION AUDIT LOG */}
        {/* ================================================================ */}
        {activeTab === "settings-audit" && (
          <div className="tab-pane active">
            <div className="section-header">
              <div>
                <h1 className="page-title">Remediation Audit Log</h1>
                <p className="page-subtitle">
                  Immutable audit records of all approved and executed remediation runbooks.
                </p>
              </div>
            </div>

            <div className="app-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                <span style={{ fontSize: "0.9rem", fontWeight: 600, color: "var(--text-primary)" }}>Execution History</span>
                <span className="badge-count">Audit Active</span>
              </div>
              <p style={{ fontSize: "0.825rem", color: "var(--text-secondary)", lineHeight: 1.5 }}>
                Every runbook action requires explicit human approval with recorded operator identity, parameters, exit code, stdout/stderr, and recovery verification.
              </p>
              <div style={{ marginTop: "16px", padding: "12px", background: "rgba(0,0,0,0.25)", borderRadius: "8px", fontFamily: "var(--font-mono)", fontSize: "0.78rem", color: "var(--text-dim)" }}>
                Logs stored at: <span style={{ color: "var(--accent-cyan)" }}>artifacts/remediations.jsonl</span> &amp; S3
              </div>
            </div>
          </div>
        )}
      </AppShell>

      {/* ==================================================================== */}
      {/* MODAL: REMEDIATION DRY-RUN & APPROVAL */}
      {/* ==================================================================== */}
      {modalOpen && (
        <div className="modal-backdrop">
          <div className="modal-dialog glass-panel">
            <div className="modal-header">
              <h3 className="modal-title">Runbook: {activeRunbook.name}</h3>
              <button className="btn-close" onClick={() => setModalOpen(false)}>×</button>
            </div>

            <div className="modal-body">
              <div className="form-group">
                <label>Target Incident</label>
                <select
                  className="form-control"
                  value={selectedIncidentId}
                  onChange={(e) => setSelectedIncidentId(e.target.value)}
                >
                  <option value="adhoc-action">Ad-Hoc Operator Action</option>
                  {incidents.map((i) => (
                    <option key={i.incident_id} value={i.incident_id}>
                      [{i.severity.toUpperCase()}] {i.service} — {i.incident_id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-row">
                <div className="form-group flex-1">
                  <label>Service / Target</label>
                  <input
                    type="text"
                    className="form-control"
                    value={modalService}
                    onChange={(e) => setModalService(e.target.value)}
                  />
                </div>
                <div className="form-group flex-1">
                  <label>Namespace</label>
                  <input
                    type="text"
                    className="form-control"
                    value={modalNamespace}
                    onChange={(e) => setModalNamespace(e.target.value)}
                  />
                </div>
              </div>

              {activeRunbook.id === "scale-workload" && (
                <div className="form-group">
                  <label>Target Replicas (1 to 20)</label>
                  <input
                    type="number"
                    min="1"
                    max="20"
                    className="form-control"
                    value={modalReplicas}
                    onChange={(e) => setModalReplicas(e.target.value)}
                  />
                </div>
              )}

              {/* Dry-Run Result Preview */}
              {dryRunPlan && (
                <div className="dry-run-preview-box">
                  <div className="preview-badge">DRY-RUN VALIDATED</div>
                  <div className="preview-command">
                    <code>{dryRunPlan.command_preview}</code>
                  </div>
                  <div className="preview-meta">
                    <span>Risk: <strong className="text-amber">{dryRunPlan.risk_level.toUpperCase()}</strong></span>
                    <span>Blast Radius: <strong>{dryRunPlan.blast_radius}</strong></span>
                  </div>
                </div>
              )}

              {dryRunPlan && (
                <div className="form-group mt-3">
                  <label>Approver Email / Username (Audit Log Signing)</label>
                  <input
                    type="text"
                    className="form-control"
                    value={approverEmail}
                    onChange={(e) => setApproverEmail(e.target.value)}
                    placeholder="lead-sre@company.com"
                  />
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setModalOpen(false)}>
                Cancel
              </button>
              {!dryRunPlan ? (
                <button
                  className="btn btn-primary"
                  disabled={isGeneratingDryRun}
                  onClick={handleGenerateDryRun}
                >
                  {isGeneratingDryRun ? "Verifying..." : "Generate Dry-Run Preview"}
                </button>
              ) : (
                <button
                  className="btn btn-primary"
                  disabled={isExecutingPlan}
                  onClick={handleApproveAndExecute}
                >
                  {isExecutingPlan ? "Executing..." : "Approve & Execute Command"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ==================================================================== */}
      {/* MODAL: POSTMORTEM REPORT VIEWER */}
      {/* ==================================================================== */}
      {postmortemModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-dialog modal-lg glass-panel">
            <div className="modal-header">
              <h3 className="modal-title">Incident Postmortem Report</h3>
              <button className="btn-close" onClick={() => setPostmortemModalOpen(false)}>×</button>
            </div>
            <div className="modal-body">
              {postmortemLoading ? (
                <div className="loading-spinner-wrapper">
                  <div className="spinner" />
                  <p>Loading postmortem report...</p>
                </div>
              ) : (
                <div className="postmortem-viewer-box">
                  <pre>{postmortemContent}</pre>
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button
                className="btn btn-secondary"
                onClick={() => copyToClipboard(postmortemContent, "Postmortem")}
              >
                Copy Markdown
              </button>
              <button className="btn btn-primary" onClick={() => setPostmortemModalOpen(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ==================================================================== */}
      {/* FLOATING TOAST NOTIFICATIONS */}
      {/* ==================================================================== */}
      <div className="toast-container">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.type}`}>
            {t.message}
          </div>
        ))}
      </div>
    </div>
  );
}

// Mount the React Application into the DOM root element
const rootElement = document.getElementById("root");
if (rootElement) {
  createRoot(rootElement).render(<App />);
}
