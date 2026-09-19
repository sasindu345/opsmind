import React, { useState, useEffect, useCallback } from "react";
import { MetricSparkline } from "../components/MetricSparkline";
import { AvailabilityBar } from "../components/AvailabilityBar";

export function ApplicationDetailPage({
  app,
  incidents = [],
  baseUrl = "",
  mode = "beginner",
  onBack,
  onRefresh,
  onOpenIncident,
}) {
  const [probing, setProbing] = useState(false);
  const [notice, setNotice] = useState("");
  const [timeRange, setTimeRange] = useState("24h");
  const [metricsData, setMetricsData] = useState(null);
  const [isLoadingMetrics, setIsLoadingMetrics] = useState(true);

  const fetchMetrics = useCallback(async () => {
    if (!app?.app_id) return;
    setIsLoadingMetrics(true);
    try {
      const resp = await fetch(`${baseUrl}/api/v1/applications/${app.app_id}/metrics?range=${timeRange}`);
      if (resp.ok) {
        const data = await resp.json();
        setMetricsData(data);
      }
    } catch (err) {
      console.error("Failed to fetch application metrics:", err);
    } finally {
      setIsLoadingMetrics(false);
    }
  }, [app?.app_id, baseUrl, timeRange]);

  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  if (!app) {
    return (
      <div className="empty-state-placeholder glass-panel">
        <p>Select an application to view its health.</p>
      </div>
    );
  }

  const related = incidents.filter(
    (inc) => inc.service === app.app_id || inc.app_id === app.app_id || inc.service === app.name
  );

  const statusLabel = {
    healthy: "Operational",
    degraded: "Degraded",
    critical: "Critical outage",
    unknown: "Waiting for first check",
  }[app.health_status] || "Unknown";

  const checkNow = async () => {
    setProbing(true);
    setNotice("");
    try {
      const resp = await fetch(`${baseUrl}/api/v1/applications/${app.app_id}/probe`, { method: "POST" });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setNotice(data.detail || "Health check was rejected.");
      } else if (data.is_success) {
        setNotice(`Healthy. Responded in ${Math.round(data.latency_ms || 0)} ms.`);
        if (onRefresh) onRefresh();
        fetchMetrics();
      } else {
        setNotice(data.error || "The health check failed.");
        if (onRefresh) onRefresh();
        fetchMetrics();
      }
    } catch (err) {
      setNotice(err.message);
    } finally {
      setProbing(false);
    }
  };

  const effectiveUptime = metricsData ? metricsData.uptime_percent : Number(app.uptime_24h_percent || 100);
  const effectiveAvgLatency = metricsData && metricsData.avg_latency_ms > 0
    ? metricsData.avg_latency_ms
    : app.current_latency_ms;
  const effectiveP95 = metricsData ? metricsData.p95_latency_ms : 0;
  const effectiveErrorRate = metricsData ? metricsData.error_rate_percent : 0;

  return (
    <div className="application-detail-page">
      {/* Top Header */}
      <div className="page-header-row">
        <div className="page-header-titles">
          <button type="button" className="btn btn-secondary btn-sm" onClick={onBack}>
            ← Back to applications
          </button>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "12px" }}>
            <h1 style={{ margin: 0 }}>{app.name}</h1>
            <span className={`app-status-badge ${app.health_status}`}>{statusLabel}</span>
          </div>
          <p>{app.environment} · {app.owner_team || "unassigned team"}</p>
        </div>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={checkNow}
            disabled={probing || !app.health_url}
          >
            {probing ? "Probing..." : "⚡ Check Now"}
          </button>
        </div>
      </div>

      {notice && (
        <div
          className="app-card"
          style={{
            padding: "12px 14px",
            marginBottom: "16px",
            borderLeft: notice.includes("Healthy") ? "4px solid #10B981" : "4px solid #EF4444",
          }}
        >
          {notice}
        </div>
      )}

      {/* Live Health Hero Card */}
      <div className="app-card" style={{ padding: "18px", marginBottom: "16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "center" }}>
          <div>
            <span className="metric-stat-label">Health Endpoint Target</span>
            <div style={{ marginTop: "4px", fontSize: "0.95rem", fontWeight: 600, color: "var(--text-primary)" }}>
              {app.health_url ? (
                <code>{app.health_url}</code>
              ) : (
                <span style={{ color: "var(--text-dim)" }}>No automated health URL configured</span>
              )}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <span className="metric-stat-label">Probe Cadence</span>
            <div style={{ fontSize: "0.9rem", color: "var(--text-secondary)" }}>
              Every <strong>{app.probe_interval_seconds}s</strong>
            </div>
          </div>
        </div>

        {mode === "engineer" && (
          <div
            style={{
              marginTop: "12px",
              paddingTop: "10px",
              borderTop: "1px solid rgba(255, 255, 255, 0.08)",
              fontFamily: "var(--font-mono)",
              fontSize: "0.78rem",
              color: "var(--text-dim)",
              display: "flex",
              gap: "16px",
            }}
          >
            <span>Failures: {app.consecutive_failures}/3</span>
            <span>Last Probe: {app.last_probe_at ? new Date(app.last_probe_at).toLocaleTimeString() : "Pending"}</span>
            <span>App ID: {app.app_id}</span>
          </div>
        )}
      </div>

      {/* 4 Summary Stat Cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: "14px",
          marginBottom: "16px",
        }}
      >
        <div className="app-card" style={{ padding: "16px" }}>
          <span className="metric-stat-label">Period Availability</span>
          <div style={{ fontSize: "1.6rem", fontWeight: 700, marginTop: "4px" }}>
            {effectiveUptime.toFixed(1)}%
          </div>
          <span style={{ fontSize: "0.75rem", color: "var(--text-dim)" }}>Rolling {timeRange} window</span>
        </div>

        <div className="app-card" style={{ padding: "16px" }}>
          <span className="metric-stat-label">Average Latency</span>
          <div style={{ fontSize: "1.6rem", fontWeight: 700, marginTop: "4px" }}>
            {effectiveAvgLatency > 0 ? `${Math.round(effectiveAvgLatency)} ms` : "—"}
          </div>
          <span style={{ fontSize: "0.75rem", color: "var(--text-dim)" }}>
            {effectiveAvgLatency < 200 ? "● Excellent speed" : effectiveAvgLatency < 500 ? "▲ Moderate" : "✖ Slow"}
          </span>
        </div>

        <div className="app-card" style={{ padding: "16px" }}>
          <span className="metric-stat-label">
            {mode === "beginner" ? "Service Reliability" : "P95 Tail Latency"}
          </span>
          <div style={{ fontSize: "1.6rem", fontWeight: 700, marginTop: "4px" }}>
            {mode === "beginner" ? (
              effectiveErrorRate === 0 ? "100% Solid" : `${(100 - effectiveErrorRate).toFixed(1)}% Pass`
            ) : effectiveP95 > 0 ? (
              `${Math.round(effectiveP95)} ms`
            ) : (
              "—"
            )}
          </div>
          <span style={{ fontSize: "0.75rem", color: "var(--text-dim)" }}>
            {mode === "beginner" ? "Zero dropped probes" : "95th percentile latency"}
          </span>
        </div>

        <div className="app-card" style={{ padding: "16px" }}>
          <span className="metric-stat-label">
            {mode === "beginner" ? "Active Outages" : "Total Probe Samples"}
          </span>
          <div style={{ fontSize: "1.6rem", fontWeight: 700, marginTop: "4px" }}>
            {mode === "beginner"
              ? related.filter((i) => i.status !== "resolved").length
              : metricsData?.total_probes ?? 0}
          </div>
          <span style={{ fontSize: "0.75rem", color: "var(--text-dim)" }}>
            {mode === "beginner"
              ? "Requiring operator action"
              : `Error rate: ${effectiveErrorRate.toFixed(1)}%`}
          </span>
        </div>
      </div>

      {/* Segmented Availability Timeline */}
      <div className="app-card" style={{ padding: "16px", marginBottom: "16px" }}>
        <AvailabilityBar
          segments={metricsData?.availability_segments || []}
          uptimePercent={effectiveUptime}
          range={timeRange}
          mode={mode}
        />
      </div>

      {/* Native Metric Sparkline with Range Selector */}
      <div className="app-card" style={{ padding: "16px", marginBottom: "16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
          <div>
            <span className="metric-stat-label">Operational Response-Time Trend</span>
            <div style={{ fontSize: "0.82rem", color: "var(--text-secondary)", marginTop: "2px" }}>
              Continuous synthetic probe latency in milliseconds
            </div>
          </div>

          {/* Time Range Selector */}
          <div className="range-selector-pills" style={{ display: "flex", gap: "4px" }}>
            {["1h", "6h", "24h", "7d"].map((r) => (
              <button
                key={r}
                type="button"
                className={`btn btn-sm ${timeRange === r ? "btn-primary" : "btn-secondary"}`}
                style={{ fontSize: "0.75rem", padding: "4px 10px" }}
                onClick={() => setTimeRange(r)}
              >
                {r.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <MetricSparkline
          series={metricsData?.series || []}
          p95={effectiveP95}
          avg={effectiveAvgLatency}
          isLoading={isLoadingMetrics}
          mode={mode}
        />
      </div>

      {/* Related Incidents & Correlated Commits */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "14px" }}>
        <div className="app-card" style={{ padding: "16px" }}>
          <span className="metric-stat-label">Related Incidents</span>
          {related.length === 0 ? (
            <p style={{ color: "var(--text-secondary)", marginTop: "8px", fontSize: "0.85rem" }}>
              No incidents tied to this application. All monitors are quiet.
            </p>
          ) : (
            related.slice(0, 5).map((inc) => (
              <button
                key={inc.incident_id}
                type="button"
                className="btn btn-secondary"
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  marginTop: "8px",
                  padding: "10px 12px",
                }}
                onClick={() => onOpenIncident(inc)}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <strong style={{ fontSize: "0.85rem" }}>{inc.title || "Incident Report"}</strong>
                  <span className={`status-tag status-${(inc.status || "open").toLowerCase()}`}>
                    {inc.status}
                  </span>
                </div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-dim)", marginTop: "4px" }}>
                  {inc.probable_cause ? inc.probable_cause.slice(0, 70) + "..." : "Under investigation"}
                </div>
              </button>
            ))
          )}
        </div>

        <div className="app-card" style={{ padding: "16px" }}>
          <span className="metric-stat-label">Correlated Deployments</span>
          {related.filter((i) => i.deployment_sha).length === 0 ? (
            <p style={{ color: "var(--text-secondary)", marginTop: "8px", fontSize: "0.85rem" }}>
              No recent git deployments correlated to this service.
            </p>
          ) : (
            related
              .filter((i) => i.deployment_sha)
              .slice(0, 5)
              .map((inc) => (
                <div
                  key={inc.deployment_sha}
                  style={{
                    padding: "10px",
                    background: "rgba(255, 255, 255, 0.04)",
                    borderRadius: "6px",
                    marginTop: "8px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem", color: "var(--accent-cyan)" }}>
                      commit {inc.deployment_sha.slice(0, 7)}
                    </span>
                    <span style={{ fontSize: "0.72rem", color: "var(--text-dim)" }}>
                      {new Date(inc.start_time || Date.now()).toLocaleDateString()}
                    </span>
                  </div>
                  <div style={{ fontSize: "0.8rem", marginTop: "4px", color: "var(--text-secondary)" }}>
                    Correlated with incident <strong>{inc.title || inc.incident_id.slice(0, 8)}</strong>
                  </div>
                </div>
              ))
          )}
        </div>
      </div>
    </div>
  );
}
