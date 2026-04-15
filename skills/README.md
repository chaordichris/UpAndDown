# Agent Skills

A collection of behavioral skills for LLM coding agents. Each skill is a set of guidelines that can be loaded into an agent's context to reduce common mistakes and improve output quality.

## Skills

### `karpathy-coding`
Behavioral guidelines derived from Andrej Karpathy's observations on LLM coding pitfalls. Covers: thinking before coding, simplicity first, surgical changes, and goal-driven execution.

**Triggers on:** feature requests, bug fixes, refactors, code reviews, or any task involving writing or modifying code.

### `github-best-practices`
Git and GitHub workflow guidelines for clean, collaborative development. Covers: conventional commits, branching strategy, pull requests, code review, merge hygiene, branch protection, secrets safety, and CI hygiene.

**Triggers on:** any task involving git commits, branches, PRs, code review, or GitHub repository setup.

## Usage

Install a `.skill` file in your agent environment (Claude, Codex, or any agent that supports skill loading). The skill's description is used to decide when to invoke it — no manual configuration needed.

## Structure

```
skills/
├── karpathy-coding/
│   └── SKILL.md
├── github-best-practices/
│   └── SKILL.md
└── README.md
```
