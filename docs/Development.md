# Development

Getting the platform running locally, and the conventions that apply once it is.

---

## Requirements

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12 | The deployment host runs 3.12; 3.11+ should work |
| Node.js | 20+ | For the frontend build only |
| SQLite | 3.35+ | `sqlite3` CLI, for backups and inspection |
| git | 2.30+ | |

No Docker, no PostgreSQL, no message broker. The platform runs on a laptop.

---

## Setup

```bash
git clone https://github.com/dvaca0/energy-iot-platform.git
cd energy-iot-platform
```

### Backend

```bash
cd backend
python3 -m venv venv
venv/bin/python3 -m pip install --upgrade pip
venv/bin/python3 -m pip install -r requirements.txt

cp .env.example .env && chmod 600 .env    # optional keys may stay blank

# Build the schema from migrations — this is the supported path.
venv/bin/python3 -m migrations.runner --status
venv/bin/python3 -m migrations.runner --apply

venv/bin/python3 -m uvicorn app.main:app --reload --port 8010
```

Open `http://127.0.0.1:8010/docs` for the generated OpenAPI UI.

> [!IMPORTANT]
> Always run the backend with `backend/` as the working directory. `.env`,
> `runtime_platform_settings.json` and `energy_platform.db` are all resolved
> relative to it, and a wrong working directory fails **silently** — the
> platform starts with no credentials and no error.

Optional runtime settings:

```bash
cp runtime_platform_settings.example.json runtime_platform_settings.json
```

### Frontend

```bash
cd frontend
npm ci
npm run dev            # Vite dev server with HMR
```

Point it at your backend if it is not on the default host/port — the base URL
lives in `src/services/api.ts`.

### Getting data in

Fresh checkouts have an empty database. Three options:

| Option | How |
|---|---|
| **Synthetic campaign** *(recommended)* | `venv/bin/python3 -m tests.test_synthetic_deployment` drives the whole pipeline against a generated campaign including a real overload |
| **Post readings by hand** | `POST /api/v1/measurements/batch` with the payload from [Collector.md](Collector.md) |
| **Restore a backup** | See [Recovery.md](Recovery.md) |

---

## Testing

Six suites, written as plain-python assertions with **no test framework**,
because pytest is not installed on the deployment host and the tests must be
runnable there.

```bash
make test              # hermetic suites — 449 checks, no database needed
make test-integration  # suites that need the live production database
```

### Hermetic — run anywhere, and in CI

Each builds its own throwaway SQLite database under `/tmp`.

| Suite | Covers | Checks |
|---|---|--:|
| `test_monitoring` | Rules, severity, thresholds, alert-noise regression guards | 329 |
| `test_smart_plugs` | Shelly ingest, ownership, assignment, fleet state | 53 |
| `test_collector` | The measurement contract and `energy_source` handling | 49 |
| `test_synthetic_deployment` | The whole pipeline against a synthetic campaign with a real overload | 18 |

### Integration — need the live production database

Neither writes to it, but neither runs on a fresh checkout, so neither is in CI.

| Suite | Why it is not hermetic |
|---|---|
| `test_energy_aggregate` | Opens `SessionLocal()` against the production database directly |
| `test_deployment_lifecycle` | Copies production with the online backup API, then asserts there is exactly one `active` deployment — which depends on the current state of the fleet |

Making both hermetic is on the roadmap. Until then, a green CI run does not
cover rollup arithmetic or lifecycle transitions.

> [!IMPORTANT]
> If you touch **anything** in `app/monitoring/`, run `test_monitoring` sections
> 19–25 and `test_synthetic_deployment`. They assert that real faults still fire
> while known noise stays silent. A monitoring system that goes quiet because it
> stopped looking is worse than a noisy one.

**The frontend has no tests.** This is the largest quality gap in the
repository and is on the [roadmap](../README.md#roadmap).

---

## Code style

Enforced in CI; see [`.github/workflows/`](../.github/workflows/).

### Python

| Tool | Purpose | Config |
|---|---|---|
| **ruff** | Lint | `pyproject.toml` |
| **black** | Format, line length 100 | `pyproject.toml` |
| **isort** | Import order (black profile) | `pyproject.toml` |
| **mypy** | Type checking — **advisory**; the codebase is not yet fully annotated. See the rationale in `pyproject.toml`. | `pyproject.toml` |

```bash
cd backend
venv/bin/python3 -m ruff check app/ tests/ migrations/
venv/bin/python3 -m black --check app/ tests/ migrations/
venv/bin/python3 -m mypy app/
```

### TypeScript

```bash
cd frontend
npm run lint
npx tsc --noEmit
```

### Everything

Install the hooks once and the above runs automatically:

```bash
pip install pre-commit && pre-commit install
pre-commit run --all-files
```

---

## Conventions

### Layering

A **router** never writes SQL. A **service** never knows it is being called over
HTTP. Breaking either produces three implementations of the tariff arithmetic,
which is exactly what the current structure exists to prevent.

### The collector contract is not negotiable

The backend contains **no hardware-specific logic**. If a change requires
`app/services/` to know what an ADS1256 is, the translation belongs in the
collector. See [Collector.md](Collector.md).

### Comments explain why

The code says what it does. Comments earn their place by recording the reason —
usually the incident that produced the constraint. The existing comments in
`app/monitoring/` and `ml_engine.py` are the model.

### Documentation ships with the change

A behaviour change and its documentation belong in the same commit. Numbers in
docs are measured, not estimated, and the command that reproduces them is shown
beside them.

---

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/), enforced by
commitlint in CI.

```
feat(monitoring): add phase imbalance rule
fix(edge): clamp counter delta across a meter reset
docs(database): record the index-rename collision
```

Types: `feat` `fix` `docs` `style` `refactor` `perf` `test` `build` `ci` `chore`
`revert`.

Scopes: `backend` `frontend` `edge` `monitoring` `db` `docs` `ci` `deps`.

The body should say **why**. A commit that changes a threshold and does not
explain what evidence justified it will be sent back.

---

## Branching

```
main            always deployable
feat/*          features
fix/*           fixes
docs/*          documentation
```

Open a PR against `main`. CI must pass. See [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Working against production

If you have access to the live server, read [Deployment.md](Deployment.md)
first. Three things that will bite you:

> [!CAUTION]
> 1. **Never `cp` the database.** WAL mode; use `sqlite3 … ".backup"`.
> 2. **`frontend/` is production, `frontend-src/` is staging.** They differ only
>    by directory name.
> 3. **`SIGHUP` reloads the API only.** The monitoring scheduler is a separate
>    process and must be restarted separately.

---

## Project layout

```
energy-iot-platform/
├── backend/          FastAPI service, migrations, tests, ADRs
├── frontend/         React dashboard
├── edge/             smart-plug collector for the Raspberry Pis
├── monitoring/       scheduler deployment artefacts + heartbeat agent
├── docs/             this documentation
├── assets/           branding and screenshots
└── .github/          CI workflows, issue and PR templates
```
