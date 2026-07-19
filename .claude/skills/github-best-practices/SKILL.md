---
name: github-best-practices
description: |
  GitHub and Git workflow best practices for LLM coding agents. Covers commit discipline, branching strategy, pull requests, code review, and merge hygiene. Use this skill whenever working with Git or GitHub — creating branches, writing commits, opening PRs, reviewing code, or setting up a repo. Especially important for multi-developer workflows, CI/CD integration, and any task involving git history or branch management. Invoke this skill for tasks like "commit my changes", "open a PR", "set up this repo", "create a branch", "review this diff", or anything touching version control.
---

# GitHub Best Practices

Guidelines for clean, collaborative Git/GitHub workflows. These apply whether you're the only developer or working across a team.

---

## 1. Commit Discipline

**Each commit should do one thing and be understandable on its own.**

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <short summary>

[optional body — why, not what]
[optional footer — breaking changes, issue refs]
```

Common types: `feat`, `fix`, `chore`, `refactor`, `test`, `docs`, `ci`

**Examples:**
```
feat(auth): add JWT refresh token rotation
fix(api): return 404 instead of 500 for missing users
chore(deps): bump requests from 2.28 to 2.31
refactor(cache): extract TTL logic into CachePolicy class
```

Rules:
- Subject line ≤72 characters, imperative mood ("add" not "added" or "adds")
- Body explains *why*, not *what* — the diff already shows what
- One logical change per commit. If you're writing "and" in the subject, split it.
- Never commit commented-out code, debug prints, or `TODO: fix this later` without a linked issue

**Atomic commits:** A commit should leave the repo in a working state. If tests were passing before, they should pass after each commit — not just at the end of the branch.

---

## 2. Branch Strategy

**Main is always deployable. Work happens on branches.**

Naming convention:
```
<type>/<short-description>
feat/user-authentication
fix/session-timeout-bug
chore/upgrade-node-18
docs/api-reference-update
```

Rules:
- Branch off `main` (or `develop` if the repo uses gitflow). Never work directly on `main`.
- Keep branches short-lived — ideally merged within a few days. Long-lived branches cause painful merges.
- Delete branches after merging. Stale branches are noise.
- One concern per branch. Don't bundle a bug fix with a feature — they're harder to review and harder to revert.

**Staying current:** Rebase your branch on `main` frequently (or before opening a PR) to minimize merge conflicts. Prefer `git rebase main` over `git merge main` to keep history linear — but never rebase shared/public branches.

---

## 3. Pull Requests

**A PR is a unit of review, not a dump of everything you did.**

Before opening:
- Rebase on the latest `main`
- Run tests locally — don't open a PR with known failures
- Self-review your own diff first. You'll catch half the issues.

PR description template:
```markdown
## What
[One paragraph: what does this change?]

## Why
[Why is this change needed? Link to issue if applicable]

## How
[Any non-obvious implementation decisions worth explaining]

## Test plan
[How did you verify this works?]
```

Rules:
- Keep PRs small. 200-400 lines of diff is ideal; 800+ is hard to review well.
- If a PR is getting large, split it: one PR for the refactor, one for the feature.
- Use **draft PRs** for work-in-progress — it signals "not ready" and still gives early visibility.
- Link related issues: `Closes #42` in the description auto-closes the issue on merge.
- Don't resolve review comments yourself — let the reviewer close them after seeing your response.

---

## 4. Code Review

**Reviews are about the code, not the author. Be specific and kind.**

As a reviewer:
- Approve when the code is good enough to ship, not when it matches your personal style
- Use prefixes to signal intent:
  - `nit:` — minor style point, take it or leave it
  - `question:` — genuine curiosity, not a required change
  - `suggestion:` — optional improvement
  - (no prefix) — required change before merge
- Ask questions before assuming. "Why did you choose X?" is better than "X is wrong"
- Review the *intent*, not just the implementation. Does this PR solve the right problem?

As an author:
- Respond to every comment, even if just "done" or "agreed, fixed"
- For disagreements, explain your reasoning — don't just revert silently
- If a review comment reveals a bug elsewhere, file a new issue rather than fixing it in this PR

---

## 5. Merge Strategy

**Choose a merge strategy and stick to it — consistency matters more than which one you pick.**

| Strategy | When to use |
|---|---|
| **Squash merge** | Feature branches — compresses all commits into one clean entry on `main`. Best for small features and bug fixes. |
| **Rebase merge** | When the branch has clean, meaningful commits you want preserved in `main` history. |
| **Merge commit** | Long-lived branches (release branches, hotfixes) where you want a clear record of the integration point. |

For most projects: **squash merge for features/fixes** is the safest default. It keeps `main` history readable and makes `git bisect` useful.

---

## 6. Protecting Main

**`main` is sacred. Never force-push it.**

Repository settings to configure:
- Require PRs before merging to `main` (no direct pushes)
- Require at least 1 approving review
- Require status checks to pass (CI must be green)
- Enable "Dismiss stale reviews when new commits are pushed"

If you accidentally push to `main` directly:
- Don't `git push --force` to fix it — that rewrites history everyone else has pulled
- Create a revert commit instead: `git revert <sha>` and push that

---

## 7. Secrets and Safety

**Secrets committed to git are compromised, even if you delete them in the next commit.**

- Never commit API keys, tokens, passwords, or private certificates — not even temporarily
- Use `.env` for local secrets and add `.env` to `.gitignore`
- Provide a `.env.example` with placeholder values so others know what variables are needed
- If you accidentally commit a secret: rotate it immediately, then clean the history (contact a repo admin)

`.gitignore` essentials to always include:
```
.env
*.env
.env.local
node_modules/
__pycache__/
*.pyc
.DS_Store
dist/
build/
```

---

## 8. CI Hygiene

**If CI is red, nothing else matters.**

- Never merge with failing CI — not even "it's just a flaky test"
- Keep CI fast (under 10 minutes) — slow CI gets ignored and worked around
- Fix broken tests immediately; don't let a failing test sit for days ("oh that always fails")
- Lint and format checks belong in CI, not code review comments

For GitHub Actions: keep workflow files in `.github/workflows/`. Name them by trigger and purpose: `ci.yml` for the main check, `release.yml` for publishing, `dependabot.yml` for dependency updates.
