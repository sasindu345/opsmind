import React, { useState, useMemo } from "react";
import { AddApplicationModal } from "../components/AddApplicationModal";

export function ApplicationsPage({
  applications = [],
  isLoading = false,
  onRefresh,
  baseUrl = "",
  mode = "beginner",
  onSelectApplication,
}) {
  const [searchQuery, setSearchQuery] = useState("");
  const [envFilter, setEnvFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [probingAppId, setProbingAppId] = useState(null);
  const [probeNotice, setProbeNotice] = useState(null);

  const filteredApps = useMemo(() => {
    return applications.filter((app) => {
      const matchesSearch =
        !searchQuery ||
        app.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        app.app_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (app.owner_team && app.owner_team.toLowerCase().includes(searchQuery.toLowerCase()));

      const matchesEnv = envFilter === "all" || app.environment === envFilter;
      const matchesStatus = statusFilter === "all" || app.health_status === statusFilter;

      return matchesSearch && matchesEnv && matchesStatus;
    });
  }, [applications, searchQuery, envFilter, statusFilter]);

  const handleProbeNow = async (appId, e) => {
    if (e) e.stopPropagation();
    setProbingAppId(appId);
    setProbeNotice(null);

    try {
      const resp = await fetch(`${baseUrl}/api/v1/applications/${appId}/probe`, {
        method: "POST",
      });
      const data = await resp.json();
      if (resp.ok) {
        setProbeNotice({
          appId,
          type: data.is_success ? "success" : "critical",
          text: data.is_success
            ? `Probe passed (HTTP ${data.http_status || 200}, ${data.latency_ms}ms)`
            : `Probe failed: ${data.error || "Unhealthy status"}`,
        });
        if (onRefresh) onRefresh();
      }
    } catch (err) {
      setProbeNotice({ appId, type: "critical", text: `Probe error: ${err.message}` });
    } finally {
      setProbingAppId(null);
    }
  };

  const handleDeleteApp = async (appId, appName, e) => {
    if (e) e.stopPropagation();
    if (!window.confirm(`Are you sure you want to stop monitoring '${appName}'?`)) return;

    try {
      const resp = await fetch(`${baseUrl}/api/v1/applications/${appId}`, {
        method: "DELETE",
      });
      if (resp.ok && onRefresh) {
        onRefresh();
      }
    } catch (err) {
      alert(`Failed to delete application: ${err.message}`);
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case "healthy":
        return <span className="app-status-badge healthy">● Operational</span>;
      case "degraded":
        return <span className="app-status-badge degraded">▲ Degraded</span>;
      case "critical":
        return <span className="app-status-badge critical">✖ Outage</span>;
      default:
        return <span className="app-status-badge">○ Pending Probe</span>;
    }
  };

  return (
    <div className="applications-page">
      {/* Header */}
      <div className="page-header-row">
        <div className="page-header-titles">
          <h1>Applications</h1>
          <p>Monitor availability, response latency, and health across your services.</p>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setIsAddModalOpen(true)}
          >
            <span>+</span> Add Application
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="applications-filter-bar">
        <input
          type="text"
          className="app-search-input"
          placeholder="Search applications by name, team, or ID..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />

        <select
          className="app-select-filter"
          value={envFilter}
          onChange={(e) => setEnvFilter(e.target.value)}
        >
          <option value="all">All Environments</option>
          <option value="production">Production</option>
          <option value="staging">Staging</option>
          <option value="development">Development</option>
        </select>

        <select
          className="app-select-filter"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="all">All Statuses</option>
          <option value="healthy">Operational</option>
          <option value="degraded">Degraded</option>
          <option value="critical">Outage</option>
        </select>
      </div>

      {/* Notice Message */}
      {probeNotice && (
        <div
          className={`alert-box ${probeNotice.type === "success" ? "alert-success" : "alert-critical"}`}
          style={{ marginBottom: "16px", padding: "10px 14px", borderRadius: "8px", fontSize: "0.825rem" }}
        >
          <span>{probeNotice.type === "success" ? "✓" : "⚠"}</span> {probeNotice.text}
        </div>
      )}

      {/* Loading Skeleton */}
      {isLoading && applications.length === 0 && (
        <div className="empty-app-state">
          <div className="spinner" style={{ marginBottom: "16px" }} />
          <p>Loading registered applications...</p>
        </div>
      )}

      {/* Empty State */}
      {!isLoading && applications.length === 0 && (
        <div className="empty-app-state">
          <div className="empty-state-icon">▦</div>
          <h3>Monitor your first application</h3>
          <p>
            Connect an application or API to automatically monitor response time,
            detect outages, and diagnose incidents with AI.
          </p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setIsAddModalOpen(true)}
          >
            + Add Application
          </button>
        </div>
      )}

      {/* Grid of Application Cards */}
      {!isLoading && applications.length > 0 && (
        <div className="applications-grid">
          {filteredApps.map((app) => {
            const isProbing = probingAppId === app.app_id;

            return (
              <div
                key={app.app_id}
                className="app-card"
                onClick={() => onSelectApplication && onSelectApplication(app.app_id)}
                style={{ cursor: onSelectApplication ? "pointer" : "default" }}
              >
                <div>
                  <div className="app-card-header">
                    <div className="app-card-title-group">
                      <h3>{app.name}</h3>
                      <div className="app-card-meta">
                        <span style={{ textTransform: "capitalize" }}>{app.environment}</span>
                        <span>•</span>
                        <span>{app.owner_team}</span>
                        {mode === "engineer" && (
                          <>
                            <span>•</span>
                            <span style={{ fontFamily: "var(--font-mono)" }}>{app.app_id}</span>
                          </>
                        )}
                      </div>
                    </div>
                    {getStatusBadge(app.health_status)}
                  </div>

                  <div className="app-card-endpoint" title={app.health_url || "No health probe configured"}>
                    {app.health_url ? `GET ${app.health_url}` : "Passive Telemetry Only (Webhooks/Logs)"}
                  </div>

                  <div className="app-card-metrics-row">
                    <div className="metric-stat">
                      <span className="metric-stat-label">Response Time</span>
                      <span className="metric-stat-value">
                        {app.current_latency_ms > 0 ? `${Math.round(app.current_latency_ms)} ms` : "—"}
                      </span>
                    </div>

                    <div className="metric-stat">
                      <span className="metric-stat-label">24h Availability</span>
                      <span className="metric-stat-value" style={{ color: app.uptime_24h_percent < 99 ? "var(--accent-amber)" : "inherit" }}>
                        {app.uptime_24h_percent.toFixed(1)}%
                      </span>
                    </div>

                    {mode === "engineer" && (
                      <div className="metric-stat engineer-only">
                        <span className="metric-stat-label">Probe Interval</span>
                        <span className="metric-stat-value">{app.probe_interval_seconds}s</span>
                      </div>
                    )}
                  </div>
                </div>

                <div className="app-card-actions" onClick={(e) => e.stopPropagation()}>
                  {app.health_url && (
                    <button
                      type="button"
                      className="btn-card-action btn-probe"
                      onClick={(e) => handleProbeNow(app.app_id, e)}
                      disabled={isProbing}
                    >
                      {isProbing ? "Checking..." : "Check Now"}
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn-card-action"
                    onClick={(e) => handleDeleteApp(app.app_id, app.name, e)}
                    style={{ color: "var(--text-dim)" }}
                    title="Deregister application"
                  >
                    Delete
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Add Application Modal */}
      <AddApplicationModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onCreated={() => {
          if (onRefresh) onRefresh();
        }}
        baseUrl={baseUrl}
      />
    </div>
  );
}
