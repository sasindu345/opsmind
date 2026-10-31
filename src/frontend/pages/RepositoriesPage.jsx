import React, { useEffect, useState } from "react";

// Connect a GitHub repository so commits are correlated to incidents and a
// failed CI run produces a suggested fix. The token is sent once and stored by
// the backend; it is never read back.

const EMPTY_FORM = {
  app_id: "",
  owner: "",
  name: "",
  access_token: "",
  default_branch: "main",
};

export function RepositoriesPage({ api, applications, showToast }) {
  const [repositories, setRepositories] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [form, setForm] = useState(EMPTY_FORM);
  const [isConnecting, setIsConnecting] = useState(false);
  const [busyRepo, setBusyRepo] = useState(null);

  const load = async () => {
    setIsLoading(true);
    try {
      setRepositories((await api.listRepositories()) || []);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!form.app_id && applications.length > 0) {
      setForm((prev) => ({ ...prev, app_id: applications[0].app_id }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applications]);

  const connect = async (event) => {
    event.preventDefault();
    if (!form.app_id) {
      showToast("Add an application first, then link its repository.", "error");
      return;
    }
    setIsConnecting(true);
    try {
      await api.connectRepository(form);
      showToast(`Connected ${form.owner}/${form.name}.`, "success");
      setForm({ ...EMPTY_FORM, app_id: form.app_id });
      await load();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setIsConnecting(false);
    }
  };

  const act = async (repo, action, verb) => {
    setBusyRepo(repo.repo_id);
    try {
      const result = await action(repo.repo_id);
      if (verb === "test") {
        showToast(
          result.connected ? `${result.repository} is reachable.` : result.detail,
          result.connected ? "success" : "error",
        );
      } else if (verb === "poll") {
        showToast(
          `Recorded ${result.commits_recorded} commit(s), found ${result.failed_runs_detected} failed run(s).`,
          "success",
        );
      } else {
        showToast("Repository disconnected.", "success");
      }
      await load();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setBusyRepo(null);
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Repositories</h1>
          <p className="page-subtitle">
            Link a GitHub repository to see which commit preceded an incident, and to get a
            suggested fix when a CI run fails. OpsMind checks GitHub on a schedule, so no public
            URL or webhook setup is needed.
          </p>
        </div>
      </header>

      <section className="panel">
        <div className="panel-header">
          <h2>Connect a repository</h2>
        </div>
        <form className="repo-form" onSubmit={connect}>
          <label>
            Application
            <select
              value={form.app_id}
              onChange={(event) => setForm({ ...form, app_id: event.target.value })}
            >
              {applications.length === 0 && <option value="">No applications yet</option>}
              {applications.map((app) => (
                <option key={app.app_id} value={app.app_id}>
                  {app.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Owner
            <input
              type="text"
              placeholder="your-org"
              value={form.owner}
              onChange={(event) => setForm({ ...form, owner: event.target.value })}
            />
          </label>
          <label>
            Repository
            <input
              type="text"
              placeholder="your-repo"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
          </label>
          <label>
            Branch
            <input
              type="text"
              value={form.default_branch}
              onChange={(event) => setForm({ ...form, default_branch: event.target.value })}
            />
          </label>
          <label>
            Access token
            <input
              type="password"
              placeholder="Personal access token with read access"
              value={form.access_token}
              onChange={(event) => setForm({ ...form, access_token: event.target.value })}
              autoComplete="off"
            />
            <span className="field-hint">
              Stored securely by the server and never shown again. Needs read access to code and
              Actions.
            </span>
          </label>
          <button type="submit" className="btn btn-primary" disabled={isConnecting}>
            {isConnecting ? "Verifying..." : "Connect repository"}
          </button>
        </form>
      </section>

      {isLoading && <p className="muted">Loading repositories...</p>}

      {!isLoading && repositories.length === 0 && (
        <p className="muted">No repositories connected yet.</p>
      )}

      <div className="repo-grid">
        {repositories.map((repo) => (
          <article key={repo.repo_id} className="card repo-card">
            <header className="repo-card-header">
              <h3>{repo.full_name}</h3>
              <span className={`badge ${repo.last_error ? "badge-critical" : "badge-healthy"}`}>
                {repo.last_error ? "Needs attention" : "Connected"}
              </span>
            </header>
            <dl className="repo-meta">
              <div>
                <dt>Application</dt>
                <dd>{repo.app_id}</dd>
              </div>
              <div>
                <dt>Branch</dt>
                <dd>{repo.default_branch}</dd>
              </div>
              <div>
                <dt>Last commit seen</dt>
                <dd>{repo.last_commit_sha ? repo.last_commit_sha.slice(0, 7) : "none yet"}</dd>
              </div>
              <div>
                <dt>Last checked</dt>
                <dd>
                  {repo.last_polled_at
                    ? new Date(repo.last_polled_at).toLocaleString()
                    : "not yet"}
                </dd>
              </div>
            </dl>
            {repo.last_error && <p className="repo-error">{repo.last_error}</p>}
            <footer className="repo-card-actions">
              <button
                type="button"
                className="btn btn-secondary"
                disabled={busyRepo === repo.repo_id}
                onClick={() => act(repo, api.testRepository, "test")}
              >
                Test connection
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={busyRepo === repo.repo_id}
                onClick={() => act(repo, api.pollRepository, "poll")}
              >
                Check now
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={busyRepo === repo.repo_id}
                onClick={() => act(repo, api.disconnectRepository, "disconnect")}
              >
                Disconnect
              </button>
            </footer>
          </article>
        ))}
      </div>
    </div>
  );
}
