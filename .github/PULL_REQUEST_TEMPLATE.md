<!--
Title must follow Conventional Commits, e.g.
    feat(monitoring): add phase imbalance rule
commitlint enforces this in CI.
-->

## What and why

<!-- What changed, and what problem it solves. The "why" matters more than the
     "what" — the diff already shows the what. -->

Closes #

## Type

- [ ] `feat` — new capability
- [ ] `fix` — bug fix
- [ ] `docs` — documentation only
- [ ] `refactor` — no behaviour change
- [ ] `perf` — performance
- [ ] `test` — tests only
- [ ] `build` / `ci` / `chore`

## Components touched

- [ ] Backend
- [ ] Frontend
- [ ] Edge collector / smart plugs
- [ ] Monitoring
- [ ] Database / migrations
- [ ] Documentation

---

## Checks

- [ ] `ruff`, `black --check` and `mypy` pass
- [ ] All six backend suites pass
- [ ] `npm run lint` and `tsc --noEmit` pass (if frontend touched)
- [ ] Documentation updated **in this PR**, not deferred
- [ ] `CHANGELOG.md` → `Unreleased` updated for anything user-visible

## The non-negotiable rules

<!-- See CONTRIBUTING.md. Each exists because breaking it caused an incident. -->

- [ ] **No hardware-specific logic entered the backend.** Device translation
      stays in the collector.
- [ ] **No existing measurement field changed meaning.** Historical data cannot
      be re-collected; a new `measurement_era` was added instead if needed.
- [ ] **Layering intact** — routers write no SQL, services know nothing of HTTP.

### If this touches `app/monitoring/`

- [ ] `tests/test_monitoring.py` sections 19–25 pass
- [ ] `tests/test_synthetic_deployment.py` passes
- [ ] The new or changed threshold is **outside** the normal operating range and
      derived from a physical rating
- [ ] It is gated on deployment state
- [ ] It has a sustain window and hysteresis
- [ ] It pages only if you would get out of bed for it; otherwise report-only

**Evidence for the threshold value:**

<!-- A distribution, a panel rating, or a percentile. "It seemed high" is not
     evidence. This platform once sent 1,386 Telegram messages in four days
     because a default was set inside the normal operating range. -->

### If this includes a migration

- [ ] A working `.down.sql` (or reversing `.py`) is included
- [ ] `migrations.runner --shadow` was run and invariants held
- [ ] Row counts and FK integrity verified before and after

**Is it reversible?** <!-- If no, this release is MAJOR. Say why a reversible
design was not possible. -->

---

## Verification

<!-- How you confirmed this works. Commands and output, not assertions. -->

```
```

## Screenshots

<!-- For UI changes: before and after, dark theme, 1600x1000 to match the
     existing gallery. See assets/screenshots/MANIFEST.md. -->

## Breaking changes

<!-- Or "None." Never omit this heading — a reviewer must be able to confirm
     the absence rather than infer it. If nodes must be updated in lockstep,
     say so here, first, in bold. -->

None.
