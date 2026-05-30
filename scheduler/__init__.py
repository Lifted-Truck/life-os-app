"""Deterministic scheduling layer for Life OS.

Governing principle (SYSTEM.md -> Scheduling Layer):

    AI may interpret language. AI may not make scheduling decisions.

Nothing in this package may call an LLM. compile() and schedule() are pure,
deterministic, and unit-tested. Same inputs always yield the same plan.
"""
