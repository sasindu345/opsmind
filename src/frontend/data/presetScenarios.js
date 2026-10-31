// Demo log samples for the triage playground.
// Client-side fixtures on purpose: these are example inputs a user can load,
// not platform configuration, so the backend has no reason to serve them.

export const PRESET_SCENARIOS = [
  {
    id: "oom",
    title: "JVM OutOfMemory Crash",
    service: "checkout-api",
    env: "production",
    tag: "High Memory",
    logs: [
      "2026-09-12T12:00:01Z [ERROR] Container checkout-api-7f89b terminated with exit code 137 (OOMKilled)",
      "2026-09-12T12:00:02Z [WARN] JVM heap memory allocated: 510MB / 512MB threshold exceeded",
      "2026-09-12T12:00:03Z [ERROR] java.lang.OutOfMemoryError: Java heap space",
      "2026-09-12T12:00:04Z [ERROR] Readiness probe failed for pod checkout-api-7f89b: Connection refused",
      "2026-09-12T12:00:05Z [INFO] Kubernetes node ip-10-0-1-42 invoked oom-killer on task 9184",
    ].join("\n"),
  },
  {
    id: "db_pool",
    title: "HikariCP DB Pool Exhaustion",
    service: "auth-service",
    env: "production",
    tag: "Database",
    logs: [
      "2026-09-12T12:05:01Z [WARN] HikariCP - Connection pool exhausted (max: 50, active: 50, waiting: 120)",
      "2026-09-12T12:05:05Z [ERROR] HTTP 504 Gateway Timeout on POST /api/v1/auth/login",
      "2026-09-12T12:05:07Z [ERROR] ConnectionTimeoutException: Timed out waiting for pooled connection after 30000ms",
      "2026-09-12T12:05:10Z [WARN] PostgreSQL slow query log: SELECT * FROM sessions WHERE token = $1 took 8420ms",
    ].join("\n"),
  },
  {
    id: "redis_latency",
    title: "Redis Cluster Saturation",
    service: "cache-gateway",
    env: "production",
    tag: "Cache & Network",
    logs: [
      "2026-09-12T12:10:00Z [WARN] Redis latency spike detected: P99 response time exceeded 250ms (baseline: 4ms)",
      "2026-09-12T12:10:02Z [ERROR] JedisConnectionException: Unexpected end of stream from redis-cluster-node-3:6379",
      "2026-09-12T12:10:04Z [ERROR] CircuitBreaker OPEN for Redis cache read operations - fallback to primary DB triggered",
      "2026-09-12T12:10:06Z [CRITICAL] 502 Bad Gateway rate surged by +340% over 2 minutes",
    ].join("\n"),
  },
  {
    id: "k8s_crashloop",
    title: "CrashLoopBackOff Deployment",
    service: "payment-worker",
    env: "staging",
    tag: "Kubernetes",
    logs: [
      "2026-09-12T12:15:01Z [INFO] Pulling image registry.internal/payment-worker:v2.4.1-patch",
      "2026-09-12T12:15:04Z [ERROR] ConfigurationError: Required environment variable STRIPE_API_SECRET is unset or empty",
      "2026-09-12T12:15:05Z [FATAL] Application failed to bootstrap. Exiting process with code 1",
      "2026-09-12T12:15:08Z [WARN] Back-off 40s restarting failed container payment-worker in pod payment-worker-8b4cf",
    ].join("\n"),
  },
];
