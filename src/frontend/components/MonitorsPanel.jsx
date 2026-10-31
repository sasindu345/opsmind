import React, { useEffect, useState } from "react";

// Lets a user decide what to watch on an application. Options come from the
// backend so the valid choices are never duplicated here.

const SIGNAL_LABELS = {
  probe_latency: "Response time (ms)",
  probe_error_rate: "Error rate (%)",
  probe_availability: "Availability (%)",
};

const COMPARISON_LABELS = {
  gt: "rises above",
  gte: "reaches",
  lt: "falls below",
  lte: "drops to",
};

function describe(monitor, mode) {
  const signal = SIGNAL_LABELS[monitor.signal_source] || monitor.signal_source;
  if (monitor.mode === "anomaly") {
    return `Alerts when ${signal.toLowerCase()} behaves unusually compared with its recent normal.`;
  }
  const comparison = COMPARISON_LABELS[monitor.comparison] || monitor.comparison;
  const detail =
    mode === "engineer"
      ? ` (${monitor.signal_source} ${monitor.comparison} ${monitor.threshold_value}, window ${monitor.window_seconds}s, min ${monitor.min_samples} samples)`
      : "";
  return `Alerts when ${signal.toLowerCase()} ${comparison} ${monitor.threshold_value}${detail}.`;
}

const EMPTY_FORM = {
  name: "",
  signal_source: "probe_latency",
  mode: "threshold",
  comparison: "gt",
  threshold_value: 1000,
  consecutive_breaches_required: 2,
  severity: "HIGH",
};

export function MonitorsPanel({ api, appId, mode, showToast }) {
  const [monitors, setMonitors] = useState([]);
  const [options, setOptions] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAdding, setIsAdding] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [isSaving, setIsSaving] = useState(false);

  const load = async () => {
    setIsLoading(true);
    try {
      const [list, opts] = await Promise.all([api.listMonitors(appId), api.monitorOptions()]);
      setMonitors(list || []);
      setOptions(opts);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (appId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appId]);

  const create = async (event) => {
    event.preventDefault();
    if (!form.name.trim()) {
      showToast("Give the monitor a name so you can recognise it later.", "error");
      return;
    }
    setIsSaving(true);
    try {
      await api.createMonitor(appId, {
        ...form,
        threshold_value: Number(form.threshold_value),
        consecutive_breaches_required: Number(form.consecutive_breaches_required),
      });
      showToast("Monitor created. It will be checked on the next health check.", "success");
      setForm(EMPTY_FORM);
      setIsAdding(false);
      await load();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsSaving(false);
    }
  };

  const toggle = async (monitor) => {
    try {
      await api.updateMonitor(appId, monitor.monitor_id, { enabled: !monitor.enabled });
      await load();
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  const remove = async (monitor) => {
    try {
      await api.deleteMonitor(appId, monitor.monitor_id);
      showToast(`Removed "${monitor.name}".`, "success");
      await load();
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  const checkNow = async (monitor) => {
    try {
      const result = await api.evaluateMonitor(appId, monitor.monitor_id);
      showToast(result.message, result.breached ? "error" : "success");
      await load();
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h2>Monitors</h2>
          <p className="panel-subtitle">
            Choose what should raise an incident. OpsMind checks these against its own health
            checks, so nothing extra needs installing.
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setIsAdding(!isAdding)}>
          {isAdding ? "Cancel" : "Add monitor"}
        </button>
      </div>

      {isAdding && options && (
        <form className="monitor-form" onSubmit={create}>
          <label>
            Name
            <input
              type="text"
              value={form.name}
              placeholder="Slow checkout responses"
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
          </label>
          <label>
            Watch
            <select
              value={form.signal_source}
              onChange={(event) => setForm({ ...form, signal_source: event.target.value })}
            >
              {options.signal_sources.map((item) => (
                <option key={item} value={item}>
                  {SIGNAL_LABELS[item] || item}
                </option>
              ))}
            </select>
          </label>
          <label>
            How to detect
            <select
              value={form.mode}
              onChange={(event) => setForm({ ...form, mode: event.target.value })}
            >
              <option value="threshold">A limit I choose</option>
              <option value="anomaly">Unusual behaviour</option>
            </select>
          </label>
          {form.mode === "threshold" && (
            <>
              <label>
                When it
                <select
                  value={form.comparison}
                  onChange={(event) => setForm({ ...form, comparison: event.target.value })}
                >
                  {options.comparisons.map((item) => (
                    <option key={item} value={item}>
                      {COMPARISON_LABELS[item] || item}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Limit
                <input
                  type="number"
                  value={form.threshold_value}
                  onChange={(event) => setForm({ ...form, threshold_value: event.target.value })}
                />
              </label>
            </>
          )}
          <label>
            Consecutive checks before alerting
            <input
              type="number"
              min="1"
              max="20"
              value={form.consecutive_breaches_required}
              onChange={(event) =>
                setForm({ ...form, consecutive_breaches_required: event.target.value })
              }
            />
          </label>
          <label>
            Severity
            <select
              value={form.severity}
              onChange={(event) => setForm({ ...form, severity: event.target.value })}
            >
              {options.severities.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn btn-primary" disabled={isSaving}>
            {isSaving ? "Creating..." : "Create monitor"}
          </button>
        </form>
      )}

      {isLoading && <p className="muted">Loading monitors...</p>}

      {!isLoading && monitors.length === 0 && (
        <p className="muted">
          No monitors yet. Add one to be told when this application slows down or starts failing.
        </p>
      )}

      <ul className="monitor-list">
        {monitors.map((monitor) => (
          <li key={monitor.monitor_id} className="monitor-row">
            <div className="monitor-row-main">
              <span className={`status-dot ${monitor.enabled ? "dot-healthy" : "dot-idle"}`} />
              <div>
                <p className="monitor-name">{monitor.name}</p>
                <p className="monitor-detail">{describe(monitor, mode)}</p>
                {monitor.consecutive_breaches > 0 && (
                  <p className="monitor-warning">
                    Condition currently met {monitor.consecutive_breaches} of{" "}
                    {monitor.consecutive_breaches_required} times.
                  </p>
                )}
              </div>
            </div>
            <div className="monitor-row-actions">
              <span className={`badge badge-${monitor.severity.toLowerCase()}`}>
                {monitor.severity}
              </span>
              <button type="button" className="btn btn-ghost" onClick={() => checkNow(monitor)}>
                Check now
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => toggle(monitor)}>
                {monitor.enabled ? "Pause" : "Resume"}
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => remove(monitor)}>
                Remove
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
