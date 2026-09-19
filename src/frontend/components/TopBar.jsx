import React from "react";
import { ModeToggle } from "./ModeToggle";

export function TopBar({
  systemStatus,
  activeIncidentCount = 0,
  mode,
  onModeToggle,
  onOpenSearch,
  appEnv = "production"
}) {
  const isHealthy = systemStatus?.status === "ok";

  return (
    <header className="top-nav-bar">
      <div className="top-nav-left">
        <div className="top-brand">
          <div className="brand-logo-mark">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
            </svg>
          </div>
          <div className="brand-titles">
            <span className="brand-name">OpsMind</span>
            <span className="brand-tag">AI Operations Copilot</span>
          </div>
        </div>

        <div className="system-health-pill" title={`Subsystem: ${systemStatus?.llm?.provider || "local"} (${systemStatus?.llm?.model || "active"})`}>
          <span className={`status-dot ${isHealthy ? "healthy" : "critical"}`} />
          <span className="status-text">{isHealthy ? "System Operational" : "Degraded"}</span>
        </div>

        {activeIncidentCount > 0 ? (
          <div className="active-incident-pill" title={`${activeIncidentCount} active incident(s) require attention`}>
            <span className="incident-dot pulse" />
            <span className="incident-count">{activeIncidentCount}</span>
            <span className="incident-label">{activeIncidentCount === 1 ? "Active Incident" : "Active Incidents"}</span>
          </div>
        ) : (
          <div className="no-incident-pill">
            <span className="no-incident-check">✓</span>
            <span className="no-incident-text">Zero Active Outages</span>
          </div>
        )}
      </div>

      <div className="top-nav-right">
        <ModeToggle mode={mode} onToggle={onModeToggle} />

        {onOpenSearch && (
          <button
            type="button"
            className="quick-search-trigger"
            onClick={onOpenSearch}
            title="Global Quick Search (Cmd+K)"
          >
            <span className="search-icon">🔍</span>
            <span className="search-placeholder">Search apps, incidents...</span>
            <kbd className="search-kbd">⌘K</kbd>
          </button>
        )}

        <div className="env-badge" title={`Environment: ${appEnv}`}>
          <span className="env-dot" />
          <span className="env-text">{appEnv}</span>
        </div>
      </div>
    </header>
  );
}
