---
name: karpathy-coding
description: |
  Behavioral guidelines for LLM coding agents that reduce the most common coding mistakes. Use this skill before writing, editing, or reviewing any code — especially for multi-step tasks, ambiguous requests, or when editing existing codebases.

  Trigger on: feature requests, bug fixes, refactors, code reviews, "add X to Y", "fix the bug", "clean this up", "make it work". If the user is asking Claude or any LLM agent to write or modify code, invoke this skill first.
---

# Karpathy Coding Guidelines

Derived from Andrej Karpathy's observations on LLM coding pitfalls. These guidelines bias toward caution over speed — for trivial single-line tasks, use judgment.

---

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before writing the first line of code:

- State your assumptions explicitly. If you're uncertain about intent, ask — don't guess and bury it.
- If multiple valid interpretations exist, surface them and let the user choose. Don't silently pick one.
- If a simpler approach exists than what was asked for, say so. Pushback is a feature, not rudeness.
- If something is genuinely unclear, stop. Name the confusion specifically. Ask the one most important question.

The instinct to "just start coding" is where most mistakes originate. A 30-second pause to surface assumptions saves hours of rework.

---

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was explicitly asked.
- No abstractions for single-use code — if it's only called once, inline it.
- No "flexibility" or "configurability" that wasn't requested. Don't future-proof what the user hasn't asked you to future-proof.
- No error handling for scenarios that can't actually happen in context.
- If you've written 200 lines and it could be 50, rewrite it. The user asked for a solution, not a framework.

Ask yourself: *"Would a senior engineer look at this and say it's overcomplicated?"* If yes, simplify before submitting.

---

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting that wasn't part of the request.
- Don't refactor things that aren't broken. Correctness > neatness.
- Match the existing style, even if you'd do it differently. Consistency beats personal preference.
- If you notice unrelated dead code or issues, **mention them** — don't silently delete or fix them.

When your changes create orphans:
- Remove any imports, variables, or functions that **your changes** made unused.
- Do not remove pre-existing dead code unless the user explicitly asked for that.

**The test:** Every changed line should trace directly to the user's request. If you can't draw that line, undo the change and ask.

---

## 4. Goal-Driven Execution

**Define success criteria before starting. Loop until verified.**

Transform vague tasks into verifiable goals:

| Vague | Verifiable |
|---|---|
| "Add validation" | "Write tests for invalid inputs, then make them pass" |
| "Fix the bug" | "Write a test that reproduces it, then make it pass" |
| "Refactor X" | "Ensure tests pass before and after; diff should shrink, not grow" |
| "Make it work" | "Define what 'working' means in terms of observable behavior" |

For multi-step tasks, state a brief plan before starting:

```
1. [What you'll do] → verify: [how you'll confirm it worked]
2. [What you'll do] → verify: [how you'll confirm it worked]
3. [What you'll do] → verify: [how you'll confirm it worked]
```

Strong success criteria let you loop independently and catch your own mistakes. Weak criteria ("make it work") require constant user clarification and often produce technically-correct-but-wrong output.
