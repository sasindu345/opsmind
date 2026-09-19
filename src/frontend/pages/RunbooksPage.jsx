import React from "react";

export function RunbooksPage({ runbooks = [], onPreview }) {
  return (
    <div className="runbooks-page">
      <div className="page-header-row">
        <div className="page-header-titles">
          <h1>Runbooks</h1>
          <p>Safe, allowlisted fixes. Nothing runs until a person approves a preview.</p>
        </div>
      </div>
      <div className="runbooks-grid">
        {runbooks.map((rb) => (
          <div key={rb.id} className="card glass-panel runbook-card">
            <div className="runbook-header">
              <span className={`risk-badge ${rb.riskClass}`}>{rb.risk} RISK</span>
              <h3 className="runbook-name">{rb.name}</h3>
            </div>
            <p className="runbook-desc">{rb.desc}</p>
            <p className="beginner-only" style={{ fontSize: "0.82rem" }}>
              Action: {rb.name}. You will preview the change before it runs.
            </p>
            <div className="runbook-command-sample engineer-only">
              <code>{rb.command}</code>
            </div>
            <button type="button" className="btn btn-primary w-full" onClick={() => onPreview(rb)}>
              Preview safe fix
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
