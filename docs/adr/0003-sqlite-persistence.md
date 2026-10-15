# 3. SQLite for persistence

Status: accepted

## Context
Nets and jobs must survive restarts. The prototype runs locally (WSL2), but the design must not assume a single API process.

## Decision
SQLite in WAL mode, standard library only, behind the `NetRepository` and `JobRepository` ports.
Nets are stored with their original bytes and are immutable. Jobs carry an idempotency key with a
unique index on live jobs. Liveness uses leases (a job carries an expiry renewed by its owner);
any process may mark expired jobs as interrupted, so processes coordinate only through atomic
conditional updates, never through memory or start-up order.

## Consequences
- No server to run; easy backup (one file).
- Several API processes on one host are supported. Several hosts need a server database
  (same ports); SQLite on a network filesystem is not supported.
- Schema changes need a migration once real data exists (backlog).
- A server database can replace it later by implementing the same ports.
