# Instructions for AI coding assistants

## Commit authorship — non-negotiable

**Never add attribution for yourself to a commit message, a tag message, or a
pull request description.** Specifically, never emit:

- `Co-Authored-By: Claude ...` or any co-author trailer with an
  `@anthropic.com` address
- `🤖 Generated with Claude Code` or any equivalent generated-by line
- Any other trailer, footer or signature naming an AI assistant

Every commit in this repository is authored solely by the repository owner
(`dvaca0 <dvaca901@gmail.com>`). A co-author trailer makes GitHub render a
second author on every commit and misattributes the work. Sixteen commits had to
be rewritten and force-pushed on 2026-08-04 to undo exactly this.

Do not set `--author`, `GIT_AUTHOR_*` or `GIT_COMMITTER_*`. The repository's
`user.name` and `user.email` are already correct; let git use them.

Three layers enforce this — do not weaken any of them:

| Layer | Where |
|---|---|
| Assistant setting | `~/.claude/settings.json` → `attribution.commit: ""`, `attribution.pr: ""`, `includeCoAuthoredBy: false` |
| Repository hook | `.githooks/commit-msg` strips the trailer if anything adds it anyway |
| This file | The instruction itself |

Write the commit message body normally — a good "why" is still expected. Just
sign nothing.

## Everything else

Contribution rules, the five non-negotiable engineering constraints, the commit
message convention, and the testing requirements are in
[CONTRIBUTING.md](CONTRIBUTING.md). Read it before proposing a change.

Two that catch people most often:

- **Anything under `app/monitoring/`** requires the sensitivity checks
  (`make test`, plus `tests/test_monitoring.py` §19–25). A monitoring system
  that went quiet because it stopped looking is worse than a noisy one.
- **Never redefine an existing measurement field.** Historical data was stored
  under its current meaning and cannot be re-collected. Add a
  `measurement_era` instead.

Run `make check` before proposing anything — it runs exactly what CI runs.
