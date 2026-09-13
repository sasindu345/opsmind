import React, { useState } from "react";

export function AddApplicationModal({ isOpen, onClose, onCreated, baseUrl = "" }) {
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [environment, setEnvironment] = useState("production");
  const [ownerTeam, setOwnerTeam] = useState("devops");
  const [healthUrl, setHealthUrl] = useState("");
  const [interval, setInterval] = useState("30");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  if (!isOpen) return null;

  const handleNext = (e) => {
    if (e) e.preventDefault();
    setErrorMsg("");

    if (step === 1) {
      if (!name.trim()) {
        setErrorMsg("Please enter an application name.");
        return;
      }
      setStep(2);
    } else if (step === 2) {
      if (healthUrl.trim() && !healthUrl.startsWith("http://") && !healthUrl.startsWith("https://")) {
        setErrorMsg("Health URL must start with http:// or https://");
        return;
      }
      setStep(3);
    } else if (step === 3) {
      setStep(4);
    }
  };

  const handleBack = () => {
    setErrorMsg("");
    setStep((prev) => Math.max(1, prev - 1));
  };

  const handleFinish = async () => {
    setIsSubmitting(true);
    setErrorMsg("");

    const payload = {
      name: name.trim(),
      environment: environment.toLowerCase(),
      owner_team: ownerTeam.trim() || "devops",
      health_url: healthUrl.trim(),
      probe_interval_seconds: parseInt(interval, 10) || 30,
    };

    try {
      const resp = await fetch(`${baseUrl}/api/v1/applications`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: "Failed to create application" }));
        throw new Error(err.detail || `Server returned ${resp.status}`);
      }

      const createdApp = await resp.json();
      if (onCreated) onCreated(createdApp);
      handleClose();
    } catch (err) {
      setErrorMsg(err.message || "An unexpected error occurred.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    setStep(1);
    setName("");
    setEnvironment("production");
    setOwnerTeam("devops");
    setHealthUrl("");
    setInterval("30");
    setErrorMsg("");
    setIsSubmitting(false);
    onClose();
  };

  return (
    <div className="modal-backdrop" onClick={handleClose}>
      <div className="modal-content modal-md" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <h2>Monitor New Application</h2>
            <p className="modal-subtitle">Zero-config automated health checks and incident detection</p>
          </div>
          <button type="button" className="btn-close" onClick={handleClose}>✕</button>
        </div>

        {/* Wizard Step Progress */}
        <div className="wizard-step-progress">
          <div className={`step-indicator ${step >= 1 ? "active" : ""} ${step > 1 ? "done" : ""}`}>
            <div className="step-circle">{step > 1 ? "✓" : "1"}</div>
            <span className="step-label">Application</span>
          </div>
          <div className={`step-indicator ${step >= 2 ? "active" : ""} ${step > 2 ? "done" : ""}`}>
            <div className="step-circle">{step > 2 ? "✓" : "2"}</div>
            <span className="step-label">Health URL</span>
          </div>
          <div className={`step-indicator ${step >= 3 ? "active" : ""} ${step > 3 ? "done" : ""}`}>
            <div className="step-circle">{step > 3 ? "✓" : "3"}</div>
            <span className="step-label">Frequency</span>
          </div>
          <div className={`step-indicator ${step >= 4 ? "active" : ""}`}>
            <div className="step-circle">4</div>
            <span className="step-label">Preview</span>
          </div>
        </div>

        {errorMsg && (
          <div className="alert-box alert-critical" style={{ marginBottom: "16px", padding: "10px 14px", borderRadius: "8px", fontSize: "0.825rem" }}>
            <span>⚠</span> {errorMsg}
          </div>
        )}

        {/* Step 1: Application Details */}
        {step === 1 && (
          <div className="wizard-step-pane">
            <div className="form-group" style={{ marginBottom: "14px" }}>
              <label className="form-label" htmlFor="app-name">Application Display Name *</label>
              <input
                id="app-name"
                type="text"
                className="form-input"
                placeholder="e.g. Checkout API, Payment Worker"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoFocus
              />
              <span className="form-hint" style={{ fontSize: "0.72rem", color: "var(--text-dim)", marginTop: "4px", display: "block" }}>
                A clear, human-readable name to identify this service.
              </span>
            </div>

            <div className="form-row" style={{ display: "flex", gap: "12px", marginBottom: "14px" }}>
              <div className="form-group" style={{ flex: 1 }}>
                <label className="form-label" htmlFor="app-env">Environment</label>
                <select
                  id="app-env"
                  className="form-select"
                  value={environment}
                  onChange={(e) => setEnvironment(e.target.value)}
                >
                  <option value="production">Production</option>
                  <option value="staging">Staging</option>
                  <option value="development">Development</option>
                </select>
              </div>

              <div className="form-group" style={{ flex: 1 }}>
                <label className="form-label" htmlFor="app-team">Owner Team</label>
                <input
                  id="app-team"
                  type="text"
                  className="form-input"
                  placeholder="e.g. platform, payments"
                  value={ownerTeam}
                  onChange={(e) => setOwnerTeam(e.target.value)}
                />
              </div>
            </div>
          </div>
        )}

        {/* Step 2: Health Endpoint */}
        {step === 2 && (
          <div className="wizard-step-pane">
            <div className="form-group" style={{ marginBottom: "14px" }}>
              <label className="form-label" htmlFor="health-url">Health Endpoint URL</label>
              <input
                id="health-url"
                type="url"
                className="form-input"
                placeholder="https://api.example.com/healthz"
                value={healthUrl}
                onChange={(e) => setHealthUrl(e.target.value)}
                autoFocus
              />
              <span className="form-hint" style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "6px", display: "block", lineHeight: 1.4 }}>
                OpsMind periodically sends an HTTP GET request to this URL to ensure your service is responsive. Leave empty to connect via webhooks only.
              </span>
            </div>

            <div className="info-callout" style={{ background: "rgba(6, 182, 212, 0.08)", border: "1px solid rgba(6, 182, 212, 0.2)", borderRadius: "8px", padding: "10px 12px", fontSize: "0.78rem", color: "var(--text-secondary)" }}>
              🔒 <strong>SSRF Protected:</strong> Private IP ranges (127.0.0.1, 10.0.0.0/8, 192.168.0.0/16, AWS metadata) are automatically blocked.
            </div>
          </div>
        )}

        {/* Step 3: Probe Frequency */}
        {step === 3 && (
          <div className="wizard-step-pane">
            <div className="form-group" style={{ marginBottom: "14px" }}>
              <label className="form-label">How often should OpsMind check health?</label>
              <div className="frequency-options" style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "10px", marginTop: "8px" }}>
                {[
                  { value: "15", label: "Every 15s", tag: "High Alert" },
                  { value: "30", label: "Every 30s", tag: "Recommended" },
                  { value: "60", label: "Every 60s", tag: "Standard" },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    className={`btn-card-action ${interval === opt.value ? "active-frequency" : ""}`}
                    onClick={() => setInterval(opt.value)}
                    style={{
                      padding: "12px 10px",
                      border: interval === opt.value ? "1px solid var(--accent-cyan)" : "1px solid var(--border-color)",
                      background: interval === opt.value ? "rgba(6, 182, 212, 0.15)" : "rgba(255, 255, 255, 0.03)",
                      borderRadius: "8px",
                      textAlign: "center",
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      gap: "4px",
                    }}
                  >
                    <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{opt.label}</span>
                    <span style={{ fontSize: "0.68rem", color: interval === opt.value ? "var(--accent-cyan)" : "var(--text-dim)" }}>{opt.tag}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Step 4: Preview & Confirm */}
        {step === 4 && (
          <div className="wizard-step-pane">
            <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "10px" }}>
              Confirm monitoring parameters for this application:
            </p>
            <div className="wizard-preview-card">
              <div className="preview-row">
                <span className="preview-label">Application Name:</span>
                <span className="preview-value">{name}</span>
              </div>
              <div className="preview-row">
                <span className="preview-label">Environment:</span>
                <span className="preview-value" style={{ textTransform: "capitalize" }}>{environment}</span>
              </div>
              <div className="preview-row">
                <span className="preview-label">Owner Team:</span>
                <span className="preview-value">{ownerTeam || "devops"}</span>
              </div>
              <div className="preview-row">
                <span className="preview-label">Health Endpoint:</span>
                <span className="preview-value">{healthUrl || "(No HTTP probe — passive events only)"}</span>
              </div>
              <div className="preview-row">
                <span className="preview-label">Probe Interval:</span>
                <span className="preview-value">Every {interval} seconds</span>
              </div>
            </div>
          </div>
        )}

        {/* Modal Actions */}
        <div className="modal-footer" style={{ marginTop: "24px", display: "flex", justifyContent: "space-between" }}>
          <div>
            {step > 1 && (
              <button type="button" className="btn btn-secondary" onClick={handleBack} disabled={isSubmitting}>
                ← Back
              </button>
            )}
          </div>
          <div style={{ display: "flex", gap: "10px" }}>
            <button type="button" className="btn btn-secondary" onClick={handleClose} disabled={isSubmitting}>
              Cancel
            </button>
            {step < 4 ? (
              <button type="button" className="btn btn-primary" onClick={handleNext}>
                Next →
              </button>
            ) : (
              <button type="button" className="btn btn-primary" onClick={handleFinish} disabled={isSubmitting}>
                {isSubmitting ? "Registering..." : "Start Monitoring"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
