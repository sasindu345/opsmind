import React, { useState } from "react";

const TABS = [
  { id: "integrations", label: "Integrations" },
  { id: "audit", label: "Audit log" },
  { id: "developer", label: "Developer API" },
];

export function SettingsPage({ systemStatus, baseUrl = "", onOpenSetup, mode = "beginner" }) {
  const [tab, setTab] = useState("integrations");
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
          <p>Every approved fix records who approved it, what ran, and whether the service recovered.</p>
          <p className="engineer-only" style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem" }}>
            data/remediation_audit.jsonl
          </p>
          <p className="beginner-only">A searchable execution table lands with the verification console. Previews still require approval today.</p>
        </div>
      )}

      {tab === "developer" && (
        <div className="app-card" style={{ padding: "18px" }}>
          <h2 style={{ fontSize: "1rem" }}>Developer API</h2>
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
