export function plainSeverity(severity) {
  const value = (severity || "medium").toLowerCase();
  if (value === "critical") return "Critical outage";
  if (value === "high") return "High impact";
  if (value === "low" || value === "info") return "Low impact";
  return "Needs attention";
}

export function plainStatus(status) {
  const value = (status || "open").toLowerCase();
  const labels = {
    open: "Needs attention",
    detected: "Just detected",
    acknowledged: "Someone is looking",
    investigating: "Under investigation",
    remediating: "Fix in progress",
    remediation_proposed: "Fix suggested",
    waiting_for_approval: "Waiting for approval",
    remediation_executing: "Fix running",
    verifying: "Checking recovery",
    resolved: "Recovered",
    failed: "Fix did not recover the service",
    closed: "Closed",
  };
  return labels[value] || "Needs attention";
}

export function plainEvidence(text) {
  const raw = String(text || "");
  if (!raw) return "No supporting evidence yet.";
  if (/drain3|cluster|#\d+|timed out|timeout/i.test(raw)) {
    return "A repeating error was found in the logs.";
  }
  if (/http probe|status \d+/i.test(raw)) {
    return "The health check could not reach the application.";
  }
  if (/git|commit|deploy/i.test(raw)) {
    return "A recent deployment happened close to the outage.";
  }
  return raw.replace(/`/g, "").slice(0, 180);
}
