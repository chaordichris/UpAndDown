# Agent Skills

Shared behavioral skills for LLM coding agents. The canonical, tool-agnostic
source lives in this `skills/` directory so Claude, Codex, and other agents can
all load the same instructions.

## Skills

### `karpathy-coding`
Behavioral guidelines derived from Andrej Karpathy's observations on LLM coding
pitfalls. Covers: thinking before coding, simplicity first, surgical changes,
and goal-driven execution.

**Triggers on:** feature requests, bug fixes, refactors, code reviews, or any
task involving writing or modifying code.

### `github-best-practices`
Git and GitHub workflow guidelines for clean, collaborative development. Covers:
conventional commits, branching strategy, pull requests, code review, merge
hygiene, branch protection, secrets safety, and CI hygiene.

**Triggers on:** any task involving git commits, branches, PRs, code review, or
GitHub repository setup.

### `marimo-notebook`
Reactive Python notebooks with marimo. Covers `.py` notebooks with `@app.cell`,
marimo CLI usage, UI components, layout, SQL integration, caching, state
management, notebook conversion, templates, and wigglystuff widgets.

**Triggers on:** marimo notebooks, reactive notebooks, interactive Python
notebooks, or Jupyter-to-marimo conversion.

### `model-evaluation`
Bayesian model comparison and predictive evaluation with ArviZ 1.1. Covers
LOO-CV, ELPD, stacking, model averaging, Bayes factors, and Pareto-k diagnostics.

**Triggers on:** model comparison, LOO, ELPD, stacking, Bayes factors,
cross-validation, predictive accuracy, or information criteria.

### `prior-elicitation`
Prior selection and prior predictive workflows for Bayesian models. Covers
constrained priors, PreliZ, expert priors, weakly informative priors, and prior
sensitivity analysis.

**Triggers on:** prior selection, prior predictive checks, PreliZ,
`find_constrained_prior`, constrained priors, or expert elicitation.

### `pymc-extras`
PyMC extras guidance for `pymc-extras` features. Covers splines,
distributional regression, R2D2/horseshoe priors, marginalization, and Laplace
approximation.

**Triggers on:** `pymc_extras`, `pmx`, splines, BSplineBasis, distributional
regression, GAMLSS, R2D2, horseshoe priors, marginalization, or Laplace fits.

### `pymc-modeling`
Bayesian statistical modeling with PyMC 6+, PyTensor 3+, and ArviZ 1.1+. Covers
model specification, inference, diagnostics, hierarchical models, GLMs,
GPs/HSGPs, BART, time series, mixtures, causal models, priors, and custom
likelihoods.

**Triggers on:** PyMC, PyTensor, ArviZ, Bayesian inference, MCMC, posterior
sampling, priors, model diagnostics, model comparison, or probabilistic models.

### `pymc-testing`
Testing PyMC models with pytest. Covers `pymc.testing.mock_sample`, fixtures,
structure-only tests, and slower posterior inference tests.

**Triggers on:** testing PyMC, pytest tests for Bayesian models, mock sampling,
model fixtures, or CI/CD for PyMC code.

## Layout

```
skills/                         # Canonical agent-agnostic source
├── karpathy-coding/
│   └── SKILL.md
├── github-best-practices/
│   └── SKILL.md
├── marimo-notebook/
├── model-evaluation/
├── prior-elicitation/
├── pymc-extras/
├── pymc-modeling/
├── pymc-testing/
└── README.md

.codex/skills/                  # Codex project mirror
└── <same skill folders>

.claude/skills/                 # Claude project mirror
└── <same skill folders>

*.skill                         # Packaged zip artifacts for import-oriented agents
```

## Provenance

- `karpathy-coding` and `github-best-practices` are local workspace skills.
- The Python analytics skills (`marimo-notebook`, `model-evaluation`,
  `prior-elicitation`, `pymc-extras`, `pymc-modeling`, and `pymc-testing`) were
  vendored from
  [`pymc-labs/python-analytics-skills`](https://github.com/pymc-labs/python-analytics-skills)
  at commit `a69c19530dfa2e3d89b4aba154b5abac0abe755e`.

## Maintenance

- Edit `skills/<skill-name>/SKILL.md` first.
- Mirror the same content to `.codex/skills/<skill-name>/SKILL.md` and
  `.claude/skills/<skill-name>/SKILL.md` in the same change.
- Regenerate the root `*.skill` package when the skill body changes.
- Keep the `name` and `description` frontmatter portable; those fields are the
  trigger surface for most agents.

Quick mirror check:

```bash
shasum -a 256 skills/*/SKILL.md .codex/skills/*/SKILL.md .claude/skills/*/SKILL.md
```
