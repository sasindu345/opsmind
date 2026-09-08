# OpsMind Security & AI Safety Model

Security and AI safety are core architectural tenets of OpsMind.

---

## 1. Zero Arbitrary Command Execution

OpsMind enforces a strict safety boundary between AI triage and cluster modifications:

- **Allowlist-Only Catalog**: OpsMind will never execute arbitrary shell scripts or LLM-generated code. Only predefined, statically coded runbooks in `src/executor/runbooks.py` can be triggered.
- **No Raw Shell (`shell=False`)**: All subprocess executions use explicitly tokenized argument arrays (e.g. `["kubectl", "rollout", "restart", ...]`). This eliminates bash shell chaining (`&&`, `;`, `|`) and command injection vulnerabilities.
- **Strict Regex Parameter Validation**: All dynamic variables (service names, namespaces, replica counts) are validated against strict alphanumeric patterns before being passed to executables.

---

## 2. Human Approval & Audit Trails

Every remediation action follows a mandatory three-step lifecycle:

```
1. DRY RUN REQUEST ──► 2. PREVIEW PLAN ──► 3. APPROVAL & AUDIT LOG
 (POST /dry-run)        (Shows exact argv)   (POST /approve with user ID)
```

- **Dry-Run Preview**: Shows the exact command line and blast radius.
- **Operator Authorization**: Execution requires an approved user identity.
- **Immutable Audit Trail**: Records execution logs to `data/remediation_audit.jsonl` with timestamp, approver email, exit code, and stdout/stderr output.

---

## 3. Secret & Credential Sanitization

- **Automated Redaction**: Telemetry ingestion and logging filters strip API keys, AWS secret tokens (`AKIA...`), GitHub personal access tokens (`ghp_...`), and Bearer tokens before writing to logs.
- **No Hardcoded Secrets**: Credentials are fed via environment variables, `.env`, or AWS Secrets Manager / IAM Instance Profiles.
- **Least-Privilege IAM**: The AWS IAM instance profile grants only minimal CRUD on specific DynamoDB and S3 ARNs with zero `AdministratorAccess`.
