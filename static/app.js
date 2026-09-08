/**
 * OpsMind Frontend Application Client
 * Modern interactive dashboard logic.
 */

// State
let allIncidents = [];
let currentPlanId = null;

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
  loadSystemStatus();
  loadIncidents();
  // Auto-refresh incidents every 10 seconds
  setInterval(loadIncidents, 10000);
});

// ------------------------------------------------------------------------------
// Navigation & Tabs
// ------------------------------------------------------------------------------

function switchTab(tabName) {
  // Update sidebar buttons
  document.querySelectorAll(".nav-tab").forEach((btn) => {
    btn.classList.remove("active");
  });
  const activeBtn = document.getElementById(`tab-btn-${tabName}`);
  if (activeBtn) activeBtn.classList.add("active");

  // Update content panes
  document.querySelectorAll(".tab-pane").forEach((pane) => {
    pane.classList.remove("active");
  });
  const targetPane = document.getElementById(`pane-${tabName}`);
  if (targetPane) targetPane.classList.add("active");
}

// ------------------------------------------------------------------------------
// System Readiness & Status
// ------------------------------------------------------------------------------

async function loadSystemStatus() {
  try {
    const res = await fetch("/readyz");
    if (!res.ok) throw new Error("Could not reach /readyz");
    const data = await res.json();

    document.getElementById("system-status-val").textContent = data.status === "ok" ? "Operational" : "Degraded";
    document.getElementById("active-model-val").textContent = data.llm.model || "Gemini / Bedrock";
    document.getElementById("app-mode-badge").textContent = data.app_env.toUpperCase() + " MODE";
  } catch (err) {
    document.getElementById("system-status-val").textContent = "Offline";
    document.getElementById("active-model-val").textContent = "N/A";
  }
}

// ------------------------------------------------------------------------------
// Incidents Feed & Status Management
// ------------------------------------------------------------------------------

async function loadIncidents() {
  try {
    const res = await fetch("/api/v1/incidents?limit=50");
    if (!res.ok) throw new Error("Failed to fetch incidents");
    allIncidents = await res.json();

    renderIncidents(allIncidents);
    updateIncidentCounters();
    populateIncidentSelectOptions();
  } catch (err) {
    console.error("Error loading incidents:", err);
  }
}

function updateIncidentCounters() {
  const active = allIncidents.filter((i) => i.status !== "resolved").length;
  document.getElementById("active-incidents-count").textContent = active;
  document.getElementById("sidebar-incidents-badge").textContent = active;
}

function renderIncidents(incidents) {
  const container = document.getElementById("incidents-list");
  if (!incidents || incidents.length === 0) {
    container.innerHTML = `
      <div class="empty-state-placeholder glass-panel">
        <svg width="48" height="48" fill="none" stroke="#475569" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
        <p>No incidents recorded in repository. Everything is operating smoothly!</p>
      </div>
    `;
    return;
  }

  container.innerHTML = incidents
    .map((inc) => {
      const sevClass = `sev-${inc.severity.toLowerCase()}`;
      const badgeClass = `badge-${inc.severity.toLowerCase()}`;
      const statusClass = `status-${inc.status.toLowerCase()}`;
      const confidencePct = Math.round((inc.confidence || 0.8) * 100);
      const timeStr = new Date(inc.created_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" });

      return `
      <div class="incident-card ${sevClass}" id="card-${inc.incident_id}">
        <div class="incident-header-row">
          <div class="incident-title-area">
            <span class="sev-badge ${badgeClass}">${inc.severity}</span>
            <span class="incident-title">${escapeHtml(inc.title || "Incident Report")}</span>
            <span class="incident-service-tag">${escapeHtml(inc.service)}</span>
          </div>
          <div class="incident-meta-right">
            <span class="status-tag ${statusClass}">${inc.status}</span>
            <span>${timeStr}</span>
          </div>
        </div>

        <div class="incident-body">
          <div><strong>Probable Cause:</strong> ${escapeHtml(inc.probable_cause || "Analyzing telemetry...")}</div>
        </div>

        <div class="incident-footer-row">
          <div class="confidence-meter">
            <span>AI Confidence: ${confidencePct}%</span>
            <div class="meter-bar"><div class="meter-fill" style="width: ${confidencePct}%"></div></div>
          </div>

          <div class="incident-action-btns">
            ${inc.status === "open" ? `
              <button class="btn btn-secondary" onclick="acknowledgeIncident('${inc.incident_id}')">Acknowledge</button>
            ` : ""}
            ${inc.status !== "resolved" ? `
              <button class="btn btn-secondary text-emerald" onclick="resolveIncident('${inc.incident_id}')">Resolve</button>
            ` : ""}
            <button class="btn btn-primary" onclick="quickRemediateIncident('${inc.incident_id}', '${inc.service}')">Remediate</button>
            <button class="btn btn-secondary" onclick="viewPostMortem('${inc.incident_id}')">Report</button>
          </div>
        </div>
      </div>
    `;
    })
    .join("");
}

function filterIncidents() {
  const serviceFilter = document.getElementById("filter-service").value.toLowerCase();
  const statusFilter = document.getElementById("filter-status").value.toLowerCase();

  const filtered = allIncidents.filter((inc) => {
    const matchService = !serviceFilter || inc.service.toLowerCase().includes(serviceFilter);
    const matchStatus = !statusFilter || inc.status.toLowerCase() === statusFilter;
    return matchService && matchStatus;
  });

  renderIncidents(filtered);
}

async function acknowledgeIncident(incidentId) {
  try {
    const res = await fetch(`/api/v1/incidents/${incidentId}/acknowledge`, { method: "POST" });
    if (res.ok) {
      showToast("Incident acknowledged", "success");
      loadIncidents();
    }
  } catch (err) {
    showToast("Failed to acknowledge incident", "error");
  }
}

async function resolveIncident(incidentId) {
  try {
    const res = await fetch(`/api/v1/incidents/${incidentId}/resolve`, { method: "POST" });
    if (res.ok) {
      showToast("Incident marked as RESOLVED", "success");
      loadIncidents();
    }
  } catch (err) {
    showToast("Failed to resolve incident", "error");
  }
}

async function viewPostMortem(incidentId) {
  try {
    const res = await fetch(`/api/v1/incidents/${incidentId}/postmortem`, { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      window.open(data.access_url, "_blank");
    }
  } catch (err) {
    showToast("Could not load post-mortem report", "error");
  }
}

// ------------------------------------------------------------------------------
// Triage Playground
// ------------------------------------------------------------------------------

async function submitTriagePlayground() {
  const service = document.getElementById("triage-service-input").value.trim() || "default-service";
  const environment = document.getElementById("triage-env-input").value;
  const rawLogs = document.getElementById("triage-logs-input").value.trim();

  if (!rawLogs) {
    showToast("Please enter or load some log lines first!", "error");
    return;
  }

  const logs = rawLogs.split("\n").map((l) => l.trim()).filter(Boolean);
  const btn = document.getElementById("btn-run-triage");
  btn.disabled = true;
  btn.innerHTML = `<div class="spinner" style="width:16px;height:16px;border-width:2px;"></div> Analyzing with AI...`;

  try {
    const res = await fetch("/api/v1/analyze/logs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ service, environment, logs, generate_report: true }),
    });

    if (!res.ok) throw new Error("Triage failed");
    const data = await res.json();

    displayTriageResult(data);
    showToast("Incident triaged successfully!", "success");
    loadIncidents(); // Refresh live incidents list
  } catch (err) {
    showToast("Error during AI triage: " + err.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `
      <svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
      Analyze Root Cause with AI
    `;
  }
}

function displayTriageResult(data) {
  document.getElementById("triage-empty-state").classList.add("hidden");
  const container = document.getElementById("triage-output-content");
  container.classList.remove("hidden");

  const a = data.analysis;
  const sevColor = a.severity === "critical" ? "text-rose" : a.severity === "high" ? "text-amber" : "text-cyan";

  container.innerHTML = `
    <div class="verdict-banner">
      <div class="verdict-header ${sevColor}">
        ${a.severity.toUpperCase()} SEVERITY (Confidence: ${Math.round(a.confidence * 100)}%)
      </div>
      <p><strong>Probable Cause:</strong> ${escapeHtml(a.probable_cause)}</p>
      <p style="margin-top: 6px; font-size: 0.8rem; color: var(--text-secondary);">${escapeHtml(a.summary)}</p>
    </div>

    <div>
      <h4 style="font-size: 0.85rem; font-weight: 600; margin-bottom: 6px;">Drain3 Log Clusters (${data.clusters_identified || 0} patterns):</h4>
      <div class="pattern-cluster-box">
        ${(data.observed_evidence || []).map((ev) => `<div>• ${escapeHtml(ev)}</div>`).join("")}
      </div>
    </div>

    <div>
      <h4 style="font-size: 0.85rem; font-weight: 600; margin-bottom: 6px;">Recommended Actions:</h4>
      <ul style="padding-left: 18px; font-size: 0.8rem; color: var(--text-secondary);">
        ${(a.remediation_actions || []).map((act) => `<li>${escapeHtml(act)}</li>`).join("")}
      </ul>
    </div>
  `;
}

function loadSampleCrashLogs() {
  document.getElementById("triage-service-input").value = "checkout-api";
  document.getElementById("triage-logs-input").value = [
    "2026-09-08T10:00:01Z [ERROR] Container checkout-api-7f89b terminated with exit code 137 (OOMKilled)",
    "2026-09-08T10:00:02Z [WARN] JVM heap memory allocated: 510MB / 512MB threshold exceeded",
    "2026-09-08T10:00:03Z [ERROR] java.lang.OutOfMemoryError: Java heap space",
    "2026-09-08T10:00:04Z [ERROR] Readiness probe failed for pod checkout-api-7f89b: Connection refused",
  ].join("\n");
}

function loadSampleDbLeakLogs() {
  document.getElementById("triage-service-input").value = "auth-service";
  document.getElementById("triage-logs-input").value = [
    "2026-09-08T10:05:01Z [WARN] HikariCP - Connection pool exhausted (max: 50, active: 50, waiting: 120)",
    "2026-09-08T10:05:05Z [ERROR] HTTP 504 Gateway Timeout on POST /api/v1/auth/login",
    "2026-09-08T10:05:07Z [ERROR] ConnectionTimeoutException: Timed out waiting for pooled connection after 30000ms",
  ].join("\n");
}

// ------------------------------------------------------------------------------
// Guarded Remediation Runbooks Modal
// ------------------------------------------------------------------------------

function openRemediationModal(runbookId, runbookName) {
  document.getElementById("remediation-modal-title").textContent = `Runbook: ${runbookName}`;
  document.getElementById("modal-runbook-id").value = runbookId;
  document.getElementById("modal-dry-run-preview").classList.add("hidden");
  document.getElementById("modal-approver-group").classList.add("hidden");
  document.getElementById("btn-modal-action").textContent = "Generate Dry-Run Preview";
  currentPlanId = null;

  document.getElementById("remediation-modal").classList.remove("hidden");
}

function quickRemediateIncident(incidentId, service) {
  openRemediationModal("restart-service", "Graceful Service Restart");
  document.getElementById("modal-incident-id").value = incidentId;
  document.getElementById("modal-service-name").value = service;
}

function populateIncidentSelectOptions() {
  const select = document.getElementById("modal-incident-id");
  const options = allIncidents.map((i) => `<option value="${i.incident_id}">[${i.severity.toUpperCase()}] ${i.service} — ${i.incident_id.slice(0, 8)}</option>`).join("");
  select.innerHTML = `<option value="adhoc-action">Ad-Hoc Operator Action</option>` + options;
}

async function handleRemediationModalAction() {
  const runbookId = document.getElementById("modal-runbook-id").value;
  const incidentId = document.getElementById("modal-incident-id").value;
  const service = document.getElementById("modal-service-name").value.trim() || "checkout-api";
  const namespace = document.getElementById("modal-namespace").value.trim() || "default";

  // Step 1: Generate Dry Run
  if (!currentPlanId) {
    try {
      const res = await fetch(`/api/v1/incidents/${incidentId}/remediation/dry-run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          runbook_id: runbookId,
          parameters: { service, namespace },
        }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Dry-run failed");
      }

      const plan = await res.json();
      currentPlanId = plan.plan_id;

      // Show Preview
      document.getElementById("preview-command-text").textContent = plan.command_preview;
      document.getElementById("preview-risk-val").textContent = plan.risk_level.toUpperCase();
      document.getElementById("preview-blast-val").textContent = plan.blast_radius;
      document.getElementById("modal-dry-run-preview").classList.remove("hidden");
      document.getElementById("modal-approver-group").classList.remove("hidden");

      document.getElementById("btn-modal-action").textContent = "Approve & Execute";
      showToast("Dry-run preview generated successfully", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  } else {
    // Step 2: Approve & Execute
    const approvedBy = document.getElementById("modal-approver-input").value.trim() || "sre-lead@company.com";
    try {
      const res = await fetch(`/api/v1/incidents/${incidentId}/remediation/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_id: currentPlanId,
          approved_by: approvedBy,
          reason: "Approved via OpsMind Dashboard",
        }),
      });

      if (!res.ok) throw new Error("Execution failed");
      const result = await res.json();

      showToast(`Action executed successfully! (ID: ${result.execution_id})`, "success");
      closeModal("remediation-modal");
      loadIncidents();
    } catch (err) {
      showToast("Execution error: " + err.message, "error");
    }
  }
}

// ------------------------------------------------------------------------------
// Incident Memory (RAG Search)
// ------------------------------------------------------------------------------

async function searchIncidentMemory() {
  const query = document.getElementById("memory-search-query").value.trim();
  if (!query) return;

  const container = document.getElementById("memory-results-list");
  container.innerHTML = `<div class="spinner"></div>`;

  try {
    const res = await fetch(`/api/v1/incidents?limit=20`);
    const incidents = await res.json();

    if (incidents.length === 0) {
      container.innerHTML = `<p class="text-dim">No historical records available in memory.</p>`;
      return;
    }

    // Client-side search preview
    const queryWords = query.toLowerCase().split(/\s+/);
    const matches = incidents.filter((inc) => {
      const target = `${inc.service} ${inc.title} ${inc.probable_cause}`.toLowerCase();
      return queryWords.some((w) => target.includes(w));
    });

    if (matches.length === 0) {
      container.innerHTML = `<p class="text-dim">No matching past incidents found for "${escapeHtml(query)}".</p>`;
      return;
    }

    container.innerHTML = matches
      .map(
        (m) => `
      <div class="glass-panel" style="margin-bottom: 12px; padding: 14px;">
        <div style="display:flex; justify-content:space-between; margin-bottom: 6px;">
          <strong>[${m.service}] ${escapeHtml(m.title)}</strong>
          <span class="status-tag status-${m.status.toLowerCase()}">${m.status}</span>
        </div>
        <div style="font-size: 0.8rem; color: var(--text-secondary);">
          <strong>Cause:</strong> ${escapeHtml(m.probable_cause)}
        </div>
      </div>
    `
      )
      .join("");
  } catch (err) {
    container.innerHTML = `<p class="text-rose">Error searching memory.</p>`;
  }
}

// ------------------------------------------------------------------------------
// Helper Utilities
// ------------------------------------------------------------------------------

function closeModal(modalId) {
  document.getElementById(modalId).classList.add("hidden");
}

function copyToClipboard(elementId) {
  const text = document.getElementById(elementId).textContent;
  navigator.clipboard.writeText(text);
  showToast("Copied to clipboard!", "success");
}

function showToast(message, type = "success") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 200);
  }, 3500);
}

function escapeHtml(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
