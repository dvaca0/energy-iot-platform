# Contributing

Thanks for looking at this. This is a research platform that runs against real
electrical infrastructure, which shapes what "a good contribution" means here:
correctness and reversibility matter more than velocity.

---

## Before you start

| Kind of change | Do this first |
|---|---|
| Bug fix | Open an issue, or reference an existing one |
| New feature | **Open an issue and agree the approach.** A large unsolicited PR is likely to be declined on scope alone |
| Documentation | Just send it |
| A monitoring threshold | Read [docs/Monitoring.md](docs/Monitoring.md) fully first — see below |
| Anything touching the measurement contract | Read [docs/Collector.md](docs/Collector.md) and [ADR-0007](backend/docs/adr/0007-canonical-measurement-model.md) |

---

## Setup

Full instructions: [docs/Development.md](docs/Development.md).

```bash
git clone https://github.com/dvaca0/energy-iot-platform.git
cd energy-iot-platform/backend
python3 -m venv venv && venv/bin/python3 -m pip install -r requirements.txt
cp .env.example .env
venv/bin/python3 -m migrations.runner --apply
venv/bin/python3 -m uvicorn app.main:app --reload --port 8010
```

```bash
cd frontend && npm ci && npm run dev
```

Install the hooks so formatting and linting run automatically:

```bash
pip install pre-commit && pre-commit install
```

---

## Workflow

1. Branch from `main`: `feat/`, `fix/`, `docs/`, `refactor/`, `ci/`.
2. Make the change. Keep it focused — one concern per PR.
3. Update documentation **in the same commit** as the behaviour it describes.
4. Run the checks below.
5. Open a PR and fill in the template.

### Checks

```bash
# Python
cd backend
venv/bin/python3 -m ruff check app/ tests/ migrations/
venv/bin/python3 -m black --check app/ tests/ migrations/
venv/bin/python3 -m mypy app/

# Tests — the four hermetic suites, 449 checks
make test

# The two that need the live production database, if you have one
make test-integration

# TypeScript
cd ../frontend && npm run lint && npx tsc --noEmit
```

---

## Rules that are not negotiable

These exist because breaking them has already caused a production incident.

### 1. The backend contains no hardware-specific logic

A collector translates its device into the canonical measurement model; the
platform stores and interprets that model and nothing else. If your change needs
`app/services/` to know what an ADS1256 is, the translation belongs in the
collector.

### 2. Alerting changes require the sensitivity checks

> [!IMPORTANT]
> A monitoring system that went quiet because it stopped looking is worse than
> one that is noisy.

Any change under `app/monitoring/` — especially a threshold — must be
accompanied by:

```bash
venv/bin/python3 -m tests.test_monitoring            # sections 19–25
venv/bin/python3 -m tests.test_synthetic_deployment  # real overload
```

They assert that real faults still fire while known noise stays silent. State in
the PR what evidence justified the new value. "It seemed high" is not evidence;
a distribution is.

Answer all four before proposing a new rule:

1. Is it gated on deployment state?
2. Is its threshold **outside** the normal operating range and derived from a
   physical rating?
3. Does it have a sustain window and hysteresis?
4. Would you get out of bed for it at 3 a.m.? If not, it is report-only.

### 3. Every migration is reversible

A `.down.sql` (or a reversing `.py`) is required. Shadow-run before applying:

```bash
venv/bin/python3 -m migrations.runner --shadow
```

An irreversible migration makes its release **MAJOR** and is a strong signal to
find a different design.

### 4. Never redefine an existing measurement field

Historical data has already been stored under the current meaning and cannot be
re-collected. Add a `measurement_era` instead. See
[docs/Versioning.md](docs/Versioning.md).

### 5. Layering

A router never writes SQL. A service never knows it is being called over HTTP.

---

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/), enforced by
commitlint in CI.

```
feat(monitoring): add phase imbalance rule
fix(edge): clamp counter delta across a meter reset
docs(database): record the index-rename collision
```

**Types:** `feat` `fix` `docs` `style` `refactor` `perf` `test` `build` `ci`
`chore` `revert`

**Scopes:** `backend` `frontend` `edge` `monitoring` `db` `docs` `ci` `deps`

The body should say **why**. A commit that changes a threshold without
explaining the evidence will be sent back.

---

## Documentation

- Diagrams are **Mermaid**, never images — they diff as text and cannot fall
  silently out of date.
- Figures are **measured**, and the command that reproduces them is shown
  beside them.
- A `> [!WARNING]` marks something that has actually gone wrong, not a
  hypothesis. Please keep that distinction.
- Comments explain **why**. The code already says what.

---

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Licence

Contributions are licensed under the [MIT Licence](LICENSE).
