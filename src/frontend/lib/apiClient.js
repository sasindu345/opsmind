// Single place every HTTP call goes through.
//
// Previously reads used the configured host while mutations used relative URLs,
// so pointing the dashboard at another host silently only affected reads. The
// API key header is applied here too, so no caller has to remember it.

const API_KEY_STORAGE = "opsmind_api_key";

export function getStoredApiKey() {
  if (typeof window === "undefined" || !window.sessionStorage) return "";
  return window.sessionStorage.getItem(API_KEY_STORAGE) || "";
}

export function setStoredApiKey(value) {
  if (typeof window === "undefined" || !window.sessionStorage) return;
  if (value) {
    window.sessionStorage.setItem(API_KEY_STORAGE, value);
  } else {
    window.sessionStorage.removeItem(API_KEY_STORAGE);
  }
}

export function detectOrigin() {
  if (typeof window !== "undefined" && window.location && window.location.origin) {
    return window.location.origin;
  }
  return "";
}

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function createApiClient(baseUrl = "", getApiKey = getStoredApiKey) {
  const root = (baseUrl || "").replace(/\/+$/, "");

  async function request(path, { method = "GET", body, signal } = {}) {
    const headers = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";

    const apiKey = typeof getApiKey === "function" ? getApiKey() : getApiKey;
    if (apiKey) headers["X-API-Key"] = apiKey;

    let response;
    try {
      response = await fetch(`${root}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
      });
    } catch (err) {
      throw new ApiError(`Could not reach OpsMind: ${err.message}`, 0, null);
    }

    if (response.status === 204) return null;

    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
    }

    if (!response.ok) {
      const detail =
        payload && typeof payload === "object" && payload.detail ? payload.detail : payload;
      const message =
        response.status === 401
          ? "Not authorised. Add your API key in Settings."
          : typeof detail === "string"
            ? detail
            : `Request failed with status ${response.status}`;
      throw new ApiError(message, response.status, detail);
    }

    return payload;
  }

  return {
    baseUrl: root,
    request,

    // System
    session: () => request("/api/v1/session"),
    readiness: () => request("/readyz"),

    // Applications
    listApplications: () => request("/api/v1/applications"),
    createApplication: (payload) =>
      request("/api/v1/applications", { method: "POST", body: payload }),
    deleteApplication: (appId) =>
      request(`/api/v1/applications/${encodeURIComponent(appId)}`, { method: "DELETE" }),
    probeApplication: (appId) =>
      request(`/api/v1/applications/${encodeURIComponent(appId)}/probe`, { method: "POST" }),
    applicationMetrics: (appId, range) =>
      request(`/api/v1/applications/${encodeURIComponent(appId)}/metrics?range=${range}`),

    // Monitors
    listMonitors: (appId) =>
      request(`/api/v1/applications/${encodeURIComponent(appId)}/monitors`),
    createMonitor: (appId, payload) =>
      request(`/api/v1/applications/${encodeURIComponent(appId)}/monitors`, {
        method: "POST",
        body: payload,
      }),
    updateMonitor: (appId, monitorId, payload) =>
      request(
        `/api/v1/applications/${encodeURIComponent(appId)}/monitors/${encodeURIComponent(monitorId)}`,
        { method: "PATCH", body: payload },
      ),
    deleteMonitor: (appId, monitorId) =>
      request(
        `/api/v1/applications/${encodeURIComponent(appId)}/monitors/${encodeURIComponent(monitorId)}`,
        { method: "DELETE" },
      ),
    evaluateMonitor: (appId, monitorId) =>
      request(
        `/api/v1/applications/${encodeURIComponent(appId)}/monitors/${encodeURIComponent(monitorId)}/evaluate`,
        { method: "POST" },
      ),
    monitorOptions: () => request("/api/v1/monitors/options"),

    // Repositories
    listRepositories: () => request("/api/v1/repositories"),
    connectRepository: (payload) =>
      request("/api/v1/repositories", { method: "POST", body: payload }),
    disconnectRepository: (repoId) =>
      request(`/api/v1/repositories/${encodeURIComponent(repoId)}`, { method: "DELETE" }),
    testRepository: (repoId) =>
      request(`/api/v1/repositories/${encodeURIComponent(repoId)}/test-connection`, {
        method: "POST",
      }),
    pollRepository: (repoId) =>
      request(`/api/v1/repositories/${encodeURIComponent(repoId)}/poll`, { method: "POST" }),

    // Incidents
    listIncidents: (limit = 50) => request(`/api/v1/incidents?limit=${limit}`),
    acknowledgeIncident: (id) =>
      request(`/api/v1/incidents/${encodeURIComponent(id)}/acknowledge`, { method: "POST" }),
    resolveIncident: (id) =>
      request(`/api/v1/incidents/${encodeURIComponent(id)}/resolve`, { method: "POST" }),
    incidentPostmortem: (id) =>
      request(`/api/v1/incidents/${encodeURIComponent(id)}/postmortem`, { method: "POST" }),
    similarIncidents: (id) => request(`/api/v1/incidents/${encodeURIComponent(id)}/similar`),

    // Analysis
    analyzeLogs: (payload) => request("/api/v1/analyze/logs", { method: "POST", body: payload }),

    // Remediation
    listRunbooks: () => request("/api/v1/remediations/runbooks"),
    remediationAudit: (limit = 50) => request(`/api/v1/remediations/audit?limit=${limit}`),
    dryRun: (incidentId, payload) =>
      request(`/api/v1/incidents/${encodeURIComponent(incidentId)}/remediation/dry-run`, {
        method: "POST",
        body: payload,
      }),
    approveRemediation: (incidentId, payload) =>
      request(`/api/v1/incidents/${encodeURIComponent(incidentId)}/remediation/approve`, {
        method: "POST",
        body: payload,
      }),

    // Copilot
    copilotChat: (payload) => request("/api/v1/copilot/chat", { method: "POST", body: payload }),
    copilotSuggestions: () => request("/api/v1/copilot/suggestions"),
  };
}
