# 5. Immutable, content-addressed nets

Status: accepted. The identity rule is superseded by ADR 0015 (identity is the hash of
the canonical net document, not of the PNML file); immutability and the parent link are unchanged.

## Context
Results must be reproducible and traceable to the exact net they were computed on.

## Decision
A net is identified by the hash of its PNML and never modified. A transformation (reduction,
unfolding) creates a new net linked to its parent.

## Consequences
Uploading the same file twice is a no-op; jobs refer to a stable id; caching is safe.
