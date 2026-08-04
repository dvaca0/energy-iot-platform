# Energy IQ — common tasks.
#
# Everything here is also written out longhand in docs/Development.md; this file
# exists so the commands are discoverable and hard to get subtly wrong (the
# backend, in particular, must run with backend/ as its working directory).
#
#     make help

PY  := backend/venv/bin/python3
NPM := npm --prefix frontend

# The five suites that run anywhere. test_deployment_lifecycle is excluded on
# purpose: it asserts against a copy of the live production database and cannot
# run on a fresh checkout. See docs/Development.md.
SUITES := monitoring collector energy_aggregate smart_plugs synthetic_deployment

.DEFAULT_GOAL := help
.PHONY: help setup dev build test lint format check docs-check api-docs clean \
        reload backup

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup:  ## Create the virtualenv, install backend and frontend dependencies
	python3 -m venv backend/venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r backend/requirements.txt
	$(PY) -m pip install ruff black isort mypy
	$(NPM) ci
	@test -f backend/.env || { cp backend/.env.example backend/.env; chmod 600 backend/.env; \
	  echo "Created backend/.env from the template — fill it in."; }

dev:  ## Run the backend with reload (frontend: make -j2 dev dev-ui)
	cd backend && venv/bin/python3 -m uvicorn app.main:app --reload --port 8010

dev-ui:  ## Run the Vite dev server
	$(NPM) run dev

build:  ## Build the frontend into frontend/dist (this IS the deploy)
	$(NPM) run build

test:  ## Run every suite that runs anywhere
	@fail=0; for t in $(SUITES); do \
	  printf "\033[36m%-24s\033[0m " "$$t"; \
	  if (cd backend && venv/bin/python3 -m tests.test_$$t >/tmp/eiq-$$t.log 2>&1); then \
	    echo "PASS"; else echo "FAIL — /tmp/eiq-$$t.log"; fail=1; fi; \
	done; exit $$fail

lint:  ## ruff, black --check, isort --check, eslint
	$(PY) -m ruff check backend/app backend/tests scripts
	$(PY) -m black --check backend/app backend/tests scripts
	$(PY) -m isort --check-only backend/app backend/tests scripts
	@echo "--- eslint (advisory; scoped to src/, as CI is) ---"
	-cd frontend && npx eslint src

format:  ## Apply black, isort and ruff --fix
	$(PY) -m isort backend/app backend/tests scripts
	$(PY) -m black backend/app backend/tests scripts
	$(PY) -m ruff check backend/app backend/tests scripts --fix

docs-check:  ## Verify every relative link and anchor resolves
	python3 scripts/check_links.py

api-docs:  ## Verify docs/API.md still matches the application
	$(PY) scripts/check_api_docs.py

check: lint test docs-check api-docs  ## Everything CI runs

backup:  ## Safe database backup — never use cp on a WAL database
	@mkdir -p backups
	@out="backups/energy_platform-$$(date +%Y%m%d_%H%M%S).db"; \
	  sqlite3 backend/energy_platform.db ".backup $$out"; \
	  sqlite3 "$$out" "PRAGMA integrity_check;"; \
	  echo "wrote $$out"

reload:  ## Graceful backend reload — no dropped connections, no root
	kill -HUP $$(systemctl show -p MainPID --value energy-platform-backend.service)
	@echo "Reloaded the API. The monitoring scheduler is a SEPARATE process —"
	@echo "restart it too if you changed app/monitoring/. See docs/Deployment.md."

clean:  ## Remove caches and build output
	find . -name __pycache__ -type d -prune -not -path "*/venv/*" -exec rm -rf {} +
	rm -rf .ruff_cache .mypy_cache frontend/dist /tmp/energy-platform-tests
