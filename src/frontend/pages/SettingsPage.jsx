import React, { useEffect, useState } from "react";

const TABS = [
  { id: "integrations", label: "Integrations" },
  { id: "audit", label: "Audit log" },
  { id: "developer", label: "Developer API" },
];

export function SettingsPage({
  systemStatus,
  baseUrl = "",
  onOpenSetup,
  mode = "beginner",
  api,
  apiKey = "",
  authRequired = false,
  onSaveApiKey,
}) {
  const [tab, setTab] = useState("integrations");
  const [auditEntries, setAuditEntries] = useState(null);
  const [auditError, setAuditError] = useState("");
  const [keyDraft, setKeyDraft] = useState(apiKey);

  useEffect(() => {
    if (tab !== "audit" || !api) return;
    let cancelled = false;
    api
      .remediationAudit(100)
      .then((rows) => {
        if (!cancelled) {
          setAuditEntries(rows || []);
          setAuditError("");
        }
      })
      .catch((err) => {
        if (!cancelled) setAuditError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [tab, api]);
  const llmReady = Boolean(systemStatus?.llm?.configured);
  const slackReady = Boolean(systemStatus?.slack_enabled);

  return (
    <div className="settings-page">
      <div className="page-header-row">
        <div className="page-header-titles">
          <h1>Settings</h1>
          <p>Connections, remediation history, and how other tools talk to OpsMind.</p>
        </div>
      </div>

      <div style={{ display: "flex", gap: "8px", marginBottom: "16px" }}>
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`btn ${tab === item.id ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "integrations" && (
        <div style={{ display: "grid", gap: "12px" }}>
          {[
            ["GitHub", "Receives deployments so outages can be tied to a recent change.", true],
            ["Prometheus", "Receives alert notifications.", true],
            ["CloudWatch", "Receives cloud alarm events.", true],
            ["Slack", slackReady ? "Chat notifications are on." : "Not configured.", slackReady],
            ["AI model", llmReady ? "Analysis is configured." : "Not configured.", llmReady],
          ].map(([name, detail, connected]) => (
            <div key={name} className="app-card" style={{ padding: "14px 16px" }}>
              <strong>{name}</strong>
              <span style={{ marginLeft: "8px" }}>{connected ? "● Connected" : "○ Not configured"}</span>
              <p style={{ margin: "6px 0 0", color: "var(--text-secondary)" }}>{detail}</p>
              <p className="engineer-only" style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem" }}>
                {name === "Prometheus" && `PromQL proxy not enabled yet · webhook ${baseUrl}/api/v1/webhooks/prometheus`}
                {name === "GitHub" && `${baseUrl}/api/v1/webhooks/github`}
                {name === "CloudWatch" && `${baseUrl}/api/v1/webhooks/cloudwatch`}
                {name === "AI model" && `${systemStatus?.llm?.provider || "unset"} / ${systemStatus?.llm?.model || "unset"}`}
              </p>
            </div>
          ))}
          <button type="button" className="btn btn-secondary" onClick={onOpenSetup}>
            {mode === "beginner" ? "Open connection setup" : "Open webhook snippets"}
          </button>
        </div>
      )}

      {tab === "audit" && (
        <div className="app-card" style={{ padding: "18px" }}>
          <h2 style={{ fontSize: "1rem" }}>Remediation audit log</h2>
          <p>Every approved fix records who approved it, exactly what ran, and whether it was
            executed for real or only simulated.</p>

          {auditError && <p className="audit-error">Could not load the audit log: {auditError}</p>}
          {!auditError && auditEntries === null && <p className="muted">Loading audit log...</p>}
          {!auditError && auditEntries !== null && auditEntries.length === 0 && (
            <p className="muted">No remediation has been approved yet.</p>
          )}

          {auditEntries !== null && auditEntries.length > 0 && (
            <table className="audit-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Runbook</th>
                  <th>Approved by</th>
                  <th>Result</th>
                  <th className="engineer-only">Command</th>
                </tr>
              </thead>
              <tbody>
                {auditEntries.map((entry) => (
                  <tr key={entry.execution_id}>
                    <td>{new Date(entry.timestamp).toLocaleString()}</td>
                    <td>{entry.runbook_id}</td>
                    <td>{entry.approved_by}</td>
                    <td>
                      <span
                        className={`badge ${entry.simulated ? "badge-degraded" : entry.status === "success" ? "badge-healthy" : "badge-critical"}`}
                      >
                        {entry.simulated ? "Simulated" : entry.status}
                      </span>
                    </td>
                    <td className="engineer-only audit-command">{entry.command_preview}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "developer" && (
        <div className="app-card" style={{ padding: "18px" }}>
          <h2 style={{ fontSize: "1rem" }}>API key</h2>
          <p>
            {authRequired
              ? "This server requires an API key for any change. Paste it here to act from the dashboard."
              : "This server has no API key configured, so changes are open. Set API_KEY to require one."}
          </p>
          <div className="api-key-row">
            <input
              type="password"
              value={keyDraft}
              placeholder="Paste your API key"
              autoComplete="off"
              onChange={(event) => setKeyDraft(event.target.value)}
              aria-label="API key"
            />
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => onSaveApiKey && onSaveApiKey(keyDraft)}
            >
              Save
            </button>
            {apiKey && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setKeyDraft("");
                  if (onSaveApiKey) onSaveApiKey("");
                }}
              >
                Clear
              </button>
            )}
          </div>
          <p className="field-hint">
            Kept in this browser tab only, and sent as the X-API-Key header.
          </p>

          <h2 style={{ fontSize: "1rem", marginTop: "18px" }}>Endpoints</h2>
          <p className="beginner-only">Other tools can send alerts and ask OpsMind about applications. Setup stays in the connection screen.</p>
          <ul className="engineer-only" style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem" }}>
            <li>GET /healthz</li>
            <li>GET /api/v1/applications</li>
            <li>POST /api/v1/applications/{"{id}"}/probe</li>
            <li>GET /api/v1/incidents</li>
            <li>POST /api/v1/analyze/logs</li>
          </ul>
        </div>
      )}
    </div>
  );
}
