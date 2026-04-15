# ADR-001: Python as the implementation language

**Status:** Accepted  
**Date:** 2026-04-15

## Decision

Use Python 3.11+ as the sole implementation language.

## Context

The system needs to: call JSON APIs, query a relational database, do floating-point math on probabilities, and generate reports. No sub-millisecond latency is required for pre-tournament markets.

## Alternatives considered

- **Go:** Faster, statically typed, better concurrency. Overkill for pre-tournament; ecosystem for sports data work is thin.
- **R:** Strong for statistical work. Poor for production pipelines, API clients, and agentic development.

## Rationale

Python has the best combination of: ecosystem maturity (SQLAlchemy, pydantic, httpx), readability for agentic development, and familiarity across the data/quant community. Speed is not a constraint for pre-tournament workflows.

## Consequences

Live/in-play markets may require a performance reassessment at Phase 6+. If latency ever becomes critical, the hot path can be rewritten in Go behind the same interface.
