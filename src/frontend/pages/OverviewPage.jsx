import React from "react";

export function OverviewPage({
  applications = [],
  incidents = [],
  onNavigate,
  onSelectApplication,
  systemStatus,
  mode = "beginner",
}) {
  const openIncidents = incidents.filter(
    (i) => i.status !== "resolved" && i.status !== "RESOLVED"
  );
  const criticalIncident = openIncidents.find(
    (i) => i.severity === "CRITICAL" || i.severity === "critical"
  );

  const healthyApps = applications.filter((a) => a.health_status === "healthy");
  const fleetHealth =
    applications.length > 0
      ? Math.round((healthyApps.length / applications.length) * 100)
      : 100;

  return (
    <div className="overview-page">
      {/* Header */}
      <div className="page-header-row">
        <div className="page-header-titles">
          <h1>System Overview</h1>
          <p>Real-time operational health, incident status, and application telemetry.</p>
        </div>
      </div>

      {/* 4 Health Summary Cards */}
      <div
        className="health-summary-grid"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: "16px",
          marginBottom: "24px",
        }}
      >
        <div className="app-card" style={{ padding: "16px" }}>
          <span className="metric-stat-label">Monitored Applications</span>
          <div style={{ display: "flex", alignItems: "baseline", gap: "8px", marginTop: "4px" }}>
            <span style={{ fontSize: "1.8rem", fontWeight: 700, color: "var(--text-primary)" }}>
              {applications.length}
            </span>
            <span style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>services</span>
          </div>
          <span style={{ fontSize: "0.74rem", color: "var(--accent-emerald)", marginTop: "6px", display: "block" }}>
            {healthyApps.length} healthy
          </span>
        </div>

        <div className="app-card" style={{ padding: "16px" }}>
          <span className="metric-stat-label">Fleet Availability</span>
          <div style={{ display: "flex", alignItems: "baseline", gap: "8px", marginTop: "4px" }}>
            <span style={{ fontSize: "1.8rem", fontWeight: 700, color: fleetHealth < 100 ? "var(--accent-amber)" : "var(--accent-emerald)" }}>
              {fleetHealth}%
            </span>
          </div>
          <span style={{ fontSize: "0.74rem", color: "var(--text-dim)", marginTop: "6px", display: "block" }}>
            Across all environments
          </span>
        </div>

        <div className="app-card" style={{ padding: "16px" }}>
          <span className="metric-stat-label">Active Incidents</span>
          <div style={{ display: "flex", alignItems: "baseline", gap: "8px", marginTop: "4px" }}>
            <span style={{ fontSize: "1.8rem", fontWeight: 700, color: openIncidents.length > 0 ? "var(--accent-rose)" : "var(--text-primary)" }}>
              {openIncidents.length}
            </span>
            <span style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>open</span>
          </div>
          <span style={{ fontSize: "0.74rem", color: openIncidents.length > 0 ? "var(--accent-rose)" : "var(--accent-emerald)", marginTop: "6px", display: "block" }}>
            {openIncidents.length > 0 ? "Requires operator review" : "All services operational"}
          </span>
        </div>

        <div className="app-card" style={{ padding: "16px" }}>
          <span className="metric-stat-label">AI Copilot</span>
          <div style={{ display: "flex", alignItems: "baseline", gap: "8px", marginTop: "4px" }}>
            <span style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--accent-cyan)" }}>
              Ready
            </span>
          </div>
          <span style={{ fontSize: "0.74rem", color: "var(--text-dim)", marginTop: "6px", display: "block" }}>
            {systemStatus?.llm?.provider || "LiteLLM"} ({systemStatus?.llm?.model || "active"})
          </span>
        </div>
      </div>

      {/* Critical Active Incident Banner (if any) */}
      {criticalIncident && (
        <div
          className="critical-incident-banner"
          style={{
            background: "linear-gradient(135deg, rgba(244, 63, 94, 0.15), rgba(15, 23, 42, 0.9))",
            border: "1px solid rgba(244, 63, 94, 0.4)",
            borderRadius: "12px",
            padding: "20px",
            marginBottom: "24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            boxShadow: "0 4px 20px rgba(244, 63, 94, 0.2)",
          }}
        >
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
              <span className="incident-dot pulse" style={{ width: "8px", height: "8px" }} />
              <span style={{ color: "var(--accent-rose)", fontWeight: 700, fontSize: "0.78rem", textTransform: "uppercase" }}>
                Critical Incident Detected
              </span>
              <span style={{ color: "var(--text-dim)", fontSize: "0.78rem" }}>•</span>
              <span style={{ color: "var(--text-secondary)", fontSize: "0.78rem" }}>{criticalIncident.service}</span>
            </div>
            <h2 style={{ fontSize: "1.15rem", fontWeight: 700, color: "var(--text-primary)", marginBottom: "4px" }}>
              {criticalIncident.title || `${criticalIncident.service} is experiencing an outage`}
            </h2>
            <p style={{ fontSize: "0.825rem", color: "var(--text-secondary)" }}>
              {criticalIncident.probable_cause || "Automated diagnostic engine detected service degradation."}
            </p>
          </div>

          <div style={{ display: "flex", gap: "10px" }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => onNavigate && onNavigate("incidents")}
              style={{ background: "var(--accent-rose)" }}
            >
              Investigate Incident
            </button>
          </div>
        </div>
      )}

      {/* Application Fleet Grid */}
      <div style={{ marginBottom: "24px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
          <h2 style={{ fontSize: "1.05rem", fontWeight: 600, color: "var(--text-primary)" }}>
            Application Fleet
          </h2>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => onNavigate && onNavigate("applications")}
            style={{ fontSize: "0.78rem", padding: "4px 10px" }}
          >
            Manage Applications →
          </button>
        </div>

        {applications.length === 0 ? (
          <div className="empty-app-state" style={{ padding: "36px 16px" }}>
            <p style={{ color: "var(--text-secondary)", marginBottom: "12px" }}>
              No applications registered yet. Add your first service to start automated health checks.
            </p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => onNavigate && onNavigate("applications")}
            >
              + Register Application
            </button>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "14px" }}>
            {applications.map((app) => (
              <div
                key={app.app_id}
                className="app-card"
                onClick={() =>
                  onSelectApplication
                    ? onSelectApplication(app.app_id)
                    : onNavigate && onNavigate("applications")
                }
                style={{ cursor: "pointer", padding: "14px" }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                  <div>
                    <h3 style={{ fontSize: "0.95rem", fontWeight: 600, color: "var(--text-primary)" }}>{app.name}</h3>
                    <span style={{ fontSize: "0.72rem", color: "var(--text-dim)", textTransform: "capitalize" }}>{app.environment}</span>
                  </div>
                  <span
                    className={`app-status-badge ${app.health_status === "healthy" ? "healthy" : app.health_status === "degraded" ? "degraded" : "critical"}`}
                    style={{ fontSize: "0.68rem", padding: "2px 8px" }}
                  >
                    {app.health_status === "healthy" ? "● OK" : app.health_status === "degraded" ? "▲ Degraded" : "✖ Outage"}
                  </span>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "8px" }}>
                  <span>Latency: <strong>{app.current_latency_ms > 0 ? `${Math.round(app.current_latency_ms)}ms` : "—"}</strong></span>
                  <span>Uptime: <strong>{app.uptime_24h_percent.toFixed(1)}%</strong></span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Engineer Mode Diagnostics */}
      {mode === "engineer" && (
        <div className="app-card engineer-only" style={{ padding: "16px", marginTop: "24px" }}>
          <span className="metric-stat-label">Engineer Diagnostics</span>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px", marginTop: "10px", fontSize: "0.8rem" }}>
            <div>
              <span style={{ color: "var(--text-dim)" }}>LLM Provider:</span>{" "}
              <strong style={{ color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
                {systemStatus?.llm?.provider || "local"}
              </strong>
            </div>
            <div>
              <span style={{ color: "var(--text-dim)" }}>Model:</span>{" "}
              <strong style={{ color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
                {systemStatus?.llm?.model || "active"}
              </strong>
            </div>
            <div>
              <span style={{ color: "var(--text-dim)" }}>Slack ChatOps:</span>{" "}
              <strong style={{ color: systemStatus?.slack_enabled ? "var(--accent-emerald)" : "var(--text-dim)" }}>
                {systemStatus?.slack_enabled ? "Enabled" : "Disabled"}
              </strong>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
