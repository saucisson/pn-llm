# 1. Record architecture decisions

Status: accepted

## Context
The code base must stay readable and evolvable, including when the people (and tools) working on it
change. The reasons behind a design disappear faster than the design itself.

## Decision
Each significant decision gets a short ADR in `docs/adr/` (context, decision, consequences),
numbered in order. A decision is changed by a new ADR that supersedes the old one, never by
rewriting history.

## Consequences
A small cost per decision; in exchange, anyone can find out why things are the way they are.
