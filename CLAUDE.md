# OpsMind — Project Rules

OpsMind is an AIOps monitoring and incident-triage platform. It probes registered application
endpoints, evaluates user-configured metric rules, ingests logs and GitHub events, correlates
failures against deployments, asks an LLM for a structured root cause, and proposes guarded
remediation that a human must approve.

## Architecture

The dependency direction is one-way. Keep it that way.

```
config/settings.py          configuration, imported by everything
src/api/                    HTTP routers: validate, delegate, serialise. No business logic.
src/core/                   triage logic: probes, rules, clustering, anomalies, correlation, queue
src/llm/                    prompts, structured output schemas, provider client, copilot tools
src/executor/               allowlisted runbooks and the guarded runner
src/memory/                 vector incident memory
src/infrastructure/         persistence and cloud abstraction
src/frontend/               React source, bundled to static/app.js
```

- **Routers stay thin.** A route parses input, calls one function in `src/core/`, `src/llm/` or
  `src/executor/`, and shapes the response. If a route grows branching logic, that logic belongs in
  a module that a worker and the CLI can call too.
- **All persistence goes through `src/infrastructure/interfaces.py`.** Add a Protocol there, then an
  implementation in both `local/` and `aws/`, then an accessor in `factory.py`. Never import `boto3`
  or `sqlite3` outside `src/infrastructure/`.
- **Both deployment modes must keep working.** `DEPLOYMENT_MODE=local` is the default and must run
  with no cloud credentials, no network calls at import time, and no manual setup beyond
  `pip install -r requirements.txt`. AWS mode must not be the only working path.
- **Reuse before adding.** Before writing a detector, correlator, clusterer, HTTP probe, or LLM call,
  check `src/core/` and `src/llm/client.py`. Parallel implementations of the same concern are the
  main thing to avoid in this codebase.

## No hardcoded values

Every URL, timeout, interval, threshold, limit, model name, bucket, table, and queue resolves from
`config/settings.py` or from a user-supplied record field. A literal in a function body is a bug.

- Add a typed field to `Settings` with a sensible default and, where it has a valid range, a
  `Field(ge=..., le=...)` constraint.
- Mirror every new field in `.env.example` with a comment.
- Per-resource values that a user chooses (a probe interval, a rule threshold, a poll interval)
  belong on the record, not in settings. Settings holds the default; the record holds the override.
- Secrets are never literals, never logged, and never returned by an API. Store them through
  `SecretManager` and expose only a boolean such as `token_configured`.

## Security rules

These are non-negotiable because they are the product's safety story.

- **Remediation is allowlist-only.** Commands are built as `argv` lists with `shell=False`. Never
  interpolate user input into a shell string. Every parameter is validated against a strict regex.
- **Human approval is mandatory.** Dry-run first, then an explicit approve step with a recorded
  identity. The LLM may propose a runbook; it must never be able to execute one. Copilot tools are
  read-only and must not be able to reach `src/executor/`.
- **Any user-supplied URL passes through `SSRFValidator`** before a request is made. This covers
  health URLs and any configurable API base URL.
- **Mutating endpoints require the API key** when one is configured. GETs, health probes, and the
  dashboard stay open.

## Testing and quality

Every change ships with tests. A phase is not done because it imports cleanly.

```
.venv/bin/pytest -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
npm run build          # after any src/frontend change
```

- Test real behaviour, not mocks of your own code. Assert on rejection paths for anything
  security-related: bad regex input, blocked IP ranges, missing approval, absent API key.
- No network calls in tests. Inject a fake `fetch` or repository, as the existing suites do.
- When fixing a bug, add the test that would have caught it first.

## Frontend

- Keep files small and single-purpose: one page or one component per file, under roughly 300 lines.
  `src/frontend/App.jsx` composes providers and routing; it is not where features live.
- All HTTP goes through `src/frontend/lib/apiClient.js` so the base URL and auth header are applied
  in one place.
- Anything a backend already owns, such as the runbook catalog, is fetched, not duplicated in a
  frontend array.
- Keep Beginner mode genuinely plain: no raw JSON, no regex, no cluster IDs. Technical detail goes
  behind Engineer mode. Route wording through `src/frontend/lib/plainText.js`.
- Style with the CSS variables in `static/style.css`. Do not introduce new literal colors.
- `static/app.js` is a committed build artifact. Run `npm run build` in the same change that edits
  frontend source, or CI will fail on a stale bundle.

## Documentation

- **No emojis** anywhere in code, comments, commit messages, or documentation.
- `README.md` is the entry point and must describe what actually exists. Do not mark something
  complete that is not wired up and tested.
- Document behaviour and configuration, not aspirations. If a setting is read nowhere, either wire
  it up or remove it.

## Commits

- Author is `wijewardana S.J. <wijewardanasj.23@uom.lk>`, matching the existing history.
- **Never add a `Co-Authored-By` trailer, and never add generated-by or tool attribution.** No
  commit in this repository has one.
- Short, meaningful, conventional subjects: `fix(worker): drain the local incident queue`.
  Imperative mood, lower case after the prefix, no trailing period, under 72 characters.
- One logical change per commit. Keep the body brief and focused on why, only when the subject is
  not self-explanatory.
- Do not commit secrets, `.env`, the virtualenv, or generated reports.
