# 18. The job queue is the jobs table; workers are threads or processes that claim from it

Status: accepted. Refines ADR 0003.

## Context
Jobs ran as `BackgroundTasks` inside the API process that received them: a crash lost the job
until the sweeper marked it interrupted, and the work could not move to another machine process.
The backlog suggested RQ or Celery.

## Decision
1. **No broker.** The queue is the `jobs` table, which already holds every job and is shared by
   all processes (ADR 0003). A queued job has no lease. A **worker claims the oldest queued job
   with one conditional `UPDATE ... RETURNING`**: of any number of workers in any number of
   processes, exactly one gets it. The claim takes a lease, renewed while the engine runs.
2. **Leases protect running jobs only.** The sweeper marks a running job whose lease expired as
   `interrupted`. A waiting job never expires, however long the queue is.
3. **Workers are threads.** `WorkerPool` runs `PNVERIF_EMBEDDED_WORKERS` threads in each API
   process (default 2; 0 for an API that only enqueues) and `python -m app.main` runs
   `PNVERIF_WORKER_THREADS` threads in a process that has no HTTP server. Concurrency is the
   number of threads, per process and in total.
4. **Cancellation reaches the engine** (ADR 0016): `DELETE /v1/jobs/{id}` marks the job cancelled
   and kills its container, from whichever process receives it.
5. **Lost jobs are re-queued explicitly**: `POST /v1/jobs/{id}/retry` puts an interrupted job
   back in the queue; it answers 409 if an equivalent job is live (it holds the idempotency key).

## Consequences
- No new service to run, secure or monitor; the multi-process rule (`CLAUDE.md`, domain rule 9)
  holds: no state in memory that matters, no start-up order.
- Polling costs one indexed query per idle worker every `PNVERIF_WORKER_POLL_SECONDS`.
- SQLite limits this to one host. Several hosts need a server database behind the same ports,
  and the queue goes with it; a broker would then be reconsidered.
