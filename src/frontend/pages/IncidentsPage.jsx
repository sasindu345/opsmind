import React from "react";
import { plainEvidence, plainSeverity, plainStatus } from "../lib/plainText";

export function IncidentsPage({
  incidents = [],
  isLoading = false,
  serviceFilter = "",
  statusFilter = "",
  onServiceFilter,
  onStatusFilter,
  onRefresh,
  onAcknowledge,
  onResolve,
  onRemediate,
  onPostmortem,
  onOpenIncident,
  onOpenTriage,
  mode = "beginner",
}) {
  return (
    <div className="incidents-page">
      <div className="page-header-row">
        <div className="page-header-titles">
          <h1>Incidents</h1>
          <p>
            {mode === "beginner"
              ? "What is wrong, why it likely happened, and the safest next step."
              : "Prioritized incidents with evidence, confidence, and correlated commits."}
          </p>
        </div>
        <div className="header-filters">
          <input
            type="text"
            className="input-search"
            placeholder="Filter by service..."
            value={serviceFilter}
            onChange={(e) => onServiceFilter(e.target.value)}
          />
          <select
            className="select-filter"
            value={statusFilter}
            onChange={(e) => onStatusFilter(e.target.value)}
          >
            <option value="">All statuses</option>
            <option value="open">Needs attention</option>
            <option value="acknowledged">In progress</option>
            <option value="resolved">Recovered</option>
          </select>
          <button type="button" className="btn btn-secondary" onClick={onRefresh}>
            Refresh
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="loading-spinner-wrapper">
          <div className="spinner" />
          <p>Loading incidents...</p>
        </div>
      ) : incidents.length === 0 ? (
        <div className="empty-state-placeholder glass-panel">
          <p>No incidents match this filter. Services look steady.</p>
          <button type="button" className="btn btn-primary mt-3" onClick={onOpenTriage}>
            Try a sample incident
          </button>
        </div>
      ) : (
        <div className="incidents-grid">
          {incidents.map((inc) => {
            const sev = (inc.severity || "medium").toLowerCase();
            const status = (inc.status || "open").toLowerCase();
            const confidencePct = Math.round((inc.confidence || 0) * 100);
            return (
              <div key={inc.incident_id} className={`incident-card sev-${sev}`}>
                <div className="incident-header-row">
                  <div className="incident-title-area">
                    <span className={`sev-badge badge-${sev}`}>
                      <span className="beginner-only">{plainSeverity(sev)}</span>
                      <span className="engineer-only">{inc.severity}</span>
                    </span>
                    <button
                      type="button"
                      className="incident-title"
                      style={{ background: "none", border: 0, color: "inherit", cursor: "pointer", textAlign: "left" }}
                      onClick={() => onOpenIncident(inc)}
                    >
                      {inc.title || "Incident needs review"}
                    </button>
                    <span className="incident-service-tag">{inc.service}</span>
                    {inc.deployment_sha && (
                      <span className="incident-service-tag" title={inc.deployment_sha}>
                        <span className="beginner-only">Recent deploy</span>
                        <span className="engineer-only">commit {String(inc.deployment_sha).slice(0, 7)}</span>
                      </span>
                    )}
                  </div>
                  <div className="incident-meta-right">
                    <span className={`status-tag status-${status}`}>
                      <span className="beginner-only">{plainStatus(status)}</span>
                      <span className="engineer-only">{inc.status}</span>
                    </span>
                  </div>
                </div>

                <div className="incident-body">
                  <div className="cause-line">
                    <strong>What happened:</strong>{" "}
                    <span>{inc.probable_cause || "Still gathering evidence."}</span>
                  </div>
                  {inc.evidence && inc.evidence.length > 0 && (
                    <>
                      <div className="evidence-preview beginner-only">
                        {plainEvidence(inc.evidence[0])}
                      </div>
                      <div className="evidence-preview engineer-only">
                        <span className="text-dim">Evidence: </span>
                        <code>{inc.evidence[0]}</code>
                      </div>
                    </>
                  )}
                </div>

                <div className="incident-footer-row">
                  <div className="confidence-meter">
                    <span className="beginner-only">Confidence {confidencePct}%</span>
                    <span className="engineer-only">confidence={inc.confidence} id={inc.incident_id}</span>
                    <div className="meter-bar">
                      <div className="meter-fill" style={{ width: `${Math.min(confidencePct, 100)}%` }} />
                    </div>
                  </div>
                  <div className="incident-action-btns">
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => onOpenIncident(inc)}>
                      Investigate
                    </button>
                    {status === "open" && (
                      <button type="button" className="btn btn-secondary btn-sm" onClick={() => onAcknowledge(inc.incident_id)}>
                        Acknowledge
                      </button>
                    )}
                    {status !== "resolved" && (
                      <button type="button" className="btn btn-primary btn-sm" onClick={() => onRemediate(inc)}>
                        Safe Fix
                      </button>
                    )}
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => onPostmortem(inc.incident_id)}>
                      Report
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
