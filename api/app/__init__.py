"""pn-llm-verif: REST API for verifying Petri nets with model-checking engines.

Onion architecture (see docs/architecture.md; enforced by import-linter). Dependencies point
inward only: ``main`` > (``api`` | ``infrastructure``) > ``application`` > ``domain``.
"""
