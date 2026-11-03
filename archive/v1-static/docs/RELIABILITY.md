# Reliability

## Integration-Point Audit

| Dependency | Timeout | Circuit breaker | Bulkhead | Retry policy | Status |
|---|---|---|---|---|---|
| Whop entitlement API | 10s | Missing | Process pool only | None | P0 open: add breaker and bounded retry after session design |
| Odds provider | Provider-specific | Partial feed-age guard | Job/process boundary | Provider-specific | P1 verify end-to-end |
| News watcher | Dead-man threshold | Feed fails closed | Separate watcher | Scheduled poll | Guarded |
| Vercel static/data delivery | Browser fetch | Feed health guard | Static tier | Manual retry | Hardened: data no-store |
| Railway API | Request server | Missing | Process boundary | Platform restart | P1 |

## Query & Resource Findings

The service worker previously cached arbitrary successful GETs, including cache-busted data responses, allowing unbounded cache growth and stale market replay. It now caches only same-origin shell assets and never JSON/CSV. Production load, QPS, and retention are not yet measured. The pipeline-run endpoint needs ingress rate limiting and a single-flight job lock before broad operator access.

## Health Checks & Metrics

`/health/live` reports process liveness. `/health` and `/health/ready` fail with 503 when entitlement configuration, viewer output, or core slate data is absent. Railway and Docker use readiness for deploy health. Still required before paid launch: centralized exception capture, request rate/error/duration metrics, feed-age gauges, entitlement denial/error counters, and alerts based on user-visible symptoms.

## Deploy vs Release

Vercel preview/build remains separate from production alias promotion. Railway restarts failed processes and gates deploys on readiness. Rollback is deployment-level today. Feature flags, database expand-contract migrations, backup verification, and an incident rollback drill remain open before persistent paid-user data is introduced.
