import React, { useEffect, useState } from "react";
import { plainEvidence, plainSeverity, plainStatus } from "../lib/plainText";

export function IncidentDetailPage({
  incident,
  baseUrl = "",
  mode = "beginner",
  onBack,
  onAcknowledge,
  onResolve,
  onRemediate,
  onPostmortem,
}) {
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    if (!incident?.incident_id) return undefined;
    let cancelled = false;
    fetch(`${baseUrl}/api/v1/incidents/${incident.incident_id}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [incident, baseUrl]);

  if (!incident) {
    return (
      <div className="empty-state-placeholder glass-panel">
        <p>Select an incident to investigate.</p>
      </div>
    );
  }

  const status = (incident.status || "open").toLowerCase();
  const evidence = incident.evidence || detail?.evidence || [];
  const timeline = detail?.timeline || incident.timeline || [];
  const services = detail?.affected_services || [incident.service];

  return (
    <div className="incident-detail-page">
      <div className="page-header-row">
        <div className="page-header-titles">
          <button type="button" className="btn btn-secondary btn-sm" onClick={onBack}>
            Back to incidents
          </button>
          <h1 style={{ marginTop: "12px" }}>{incident.title || "Incident investigation"}</h1>
          <p>
            <span className="beginner-only">{plainSeverity(incident.severity)} · {plainStatus(status)}</span>
            <span className="engineer-only">{incident.severity} · {incident.status} · {incident.incident_id}</span>
          </p>
        </div>
        <div className="page-header-actions" style={{ display: "flex", gap: "8px" }}>
          {status !== "resolved" && (
            <button type="button" className="btn btn-primary" onClick={() => onRemediate(incident)}>
              Safe Fix
            </button>
          )}
          <button type="button" className="btn btn-secondary" onClick={() => onPostmortem(incident.incident_id)}>
            View report
          </button>
        </div>
      </div>

      <div className="app-card" style={{ padding: "18px", marginBottom: "16px" }}>
        <span className="metric-stat-label">Diagnosis</span>
        <p style={{ margin: "8px 0 0", color: "var(--text-primary)" }}>
          {incident.probable_cause || "OpsMind is still gathering evidence."}
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "14px" }}>
        <div className="app-card" style={{ padding: "16px" }}>
          <span className="metric-stat-label">Evidence</span>
          {(evidence.length ? evidence : ["No evidence recorded yet."]).slice(0, 4).map((item) => (
            <p key={item} style={{ fontSize: "0.82rem", margin: "8px 0 0" }}>
              <span className="beginner-only">{plainEvidence(item)}</span>
              <span className="engineer-only"><code>{item}</code></span>
            </p>
          ))}
        </div>
        <div className="app-card" style={{ padding: "16px" }}>
          <span className="metric-stat-label">What else is affected</span>
          <p style={{ marginTop: "8px" }}>{services.filter(Boolean).join(", ") || incident.service}</p>
          {incident.deployment_sha && (
            <p style={{ marginTop: "8px", fontSize: "0.82rem" }}>
              <span className="beginner-only">A deployment landed close to this outage.</span>
              <span className="engineer-only">commit {incident.deployment_sha}</span>
            </p>
          )}
        </div>
        <div className="app-card" style={{ padding: "16px" }}>
          <span className="metric-stat-label">Timeline</span>
          {timeline.length === 0 ? (
            <p style={{ marginTop: "8px", color: "var(--text-secondary)" }}>No extra timeline events yet.</p>
          ) : (
            timeline.slice(0, 6).map((event, index) => (
              <p key={`${event.timestamp || index}`} style={{ fontSize: "0.8rem", margin: "8px 0 0" }}>
                {event.description || event.event_type || "Event recorded"}
                <span className="engineer-only"> · {event.source}</span>
              </p>
            ))
          )}
        </div>
      </div>

      <div style={{ display: "flex", gap: "8px", marginTop: "16px" }}>
        {status === "open" && (
          <button type="button" className="btn btn-secondary" onClick={() => onAcknowledge(incident.incident_id)}>
            Acknowledge
          </button>
        )}
        {status !== "resolved" && (
          <button type="button" className="btn btn-secondary" onClick={() => onResolve(incident.incident_id)}>
            Mark recovered
          </button>
        )}
      </div>
    </div>
  );
}
