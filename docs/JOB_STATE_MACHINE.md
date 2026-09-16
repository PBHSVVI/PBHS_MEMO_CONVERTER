# Job State Machine v1

## Teacher-facing states

| Internal state | Teacher display |
|---|---|
| `queued` | Waiting to start |
| `dispatched` | Starting |
| `processing` | Converting |
| `needs_review` | Review required |
| `rendering` | Preparing files |
| `complete` | Ready to download |
| `failed_retryable` | Conversion paused — retry available |
| `failed` | Conversion needs attention |

## Controlled transitions

```text
created
  |
  v
queued
  |
  v
dispatched
  |
  v
processing
  | \
  |  +--> failed_retryable --> dispatched
  |
  +--> needs_review
  |       |
  |       v
  |   correction_pending
  |       |
  |       v
  |   correction_confirmed
  |       |
  |       v
  +----- dispatched
  |
  v
rendering
  |
  v
complete
```

## Rules

1. Browser may create a user-owned `queued` job.
2. Browser may not arbitrarily set worker-controlled states.
3. Dispatch function performs `queued -> dispatched`.
4. Worker performs `dispatched -> processing`.
5. Deterministic/confidence gates decide `processing -> needs_review` or `processing -> rendering`.
6. Only confirmed correction content may alter canonical memo data.
7. Final deterministic validation must pass before `rendering`.
8. Rendering/glyph preflight must pass before `complete`.
9. Every transition creates an audit event.
10. Duplicate workflow dispatch must not create duplicate processing.

## Retry model

Retries preserve the same `job_id`, increment `attempt_count`, reuse cached successful work and never overwrite a confirmed teacher correction silently.
