# Security policy

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report privately through GitHub's
[Security Advisories](https://github.com/dvaca0/energy-iot-platform/security/advisories/new),
which creates a channel visible only to the maintainer.

If that is unavailable, email **dvaca901@gmail.com** with `SECURITY` in the
subject line.

### What to include

- What the issue is, and which component (backend, frontend, edge, monitoring)
- How to reproduce it
- What an attacker could achieve
- Any suggested fix

### What to expect

| | |
|---|---|
| Acknowledgement | Within **72 hours** |
| Initial assessment | Within **7 days** |
| Fix or mitigation plan | Communicated with the assessment |
| Credit | Offered in the release notes, unless you prefer otherwise |

This is a single-maintainer research platform, not a funded product. There is no
bug bounty. Reports are nonetheless taken seriously and answered.

---

## Supported versions

| Version | Supported |
|---|---|
| `main` | ✅ |
| Latest tagged release | ✅ |
| Older releases | ❌ |

Fixes land on `main` and in the next release.

---

## Known gaps — please read before reporting

These are **already known and documented**. Reporting them is welcome as
confirmation, but they are not new findings.

### The ingestion endpoints are unauthenticated

`POST /api/v1/measurements/batch`, `POST /api/readings` and
`POST /api/edge/heartbeat` accept a self-asserted `device_id`. The most serious
consequence is that **a forged heartbeat can suppress a real outage alert**.

Documented in [ADR-0002](backend/docs/adr/0002-upload-authorization.md) and
[docs/Security.md](docs/Security.md). Closing it is the highest-priority item on
the roadmap.

### CORS is fully permissive

`allow_origins=["*"]` with `allow_credentials=False`. There are currently no
cookies or sessions to protect. This must be tightened as part of adding
authentication, not afterwards.

### The frontend role selector is not an authorisation boundary

Roles shape what the UI displays. They are not enforced server-side, because the
server does not authenticate anyone.

### No enforced transport encryption

Nodes post over HTTP on a trusted site LAN. A deployment reachable from an
untrusted network needs TLS in front of the API.

Full posture, threat model and hardening checklist:
**[docs/Security.md](docs/Security.md)**.

---

## Secrets

The platform holds exactly three credentials, all in `backend/.env`, which is
git-ignored:

| Secret | Effect if absent |
|---|---|
| `GEMINI_API_KEY` | LLM narration disabled; all statistical models unaffected |
| `MONITORING_TELEGRAM_BOT_TOKEN` | Alerts recorded but not delivered |
| `MONITORING_TELEGRAM_CHAT_ID` | As above |

There is no database password — SQLite is a local file — and no session signing
key.

**If you believe a secret has been exposed in this repository**, report it
privately and it will be revoked immediately. A committed secret is compromised
the moment it reaches a remote; rewriting history is not sufficient, because
forks, clones and CI caches outlive a force-push.

### Verifying

```bash
git ls-files | grep -iE '\.env$|\.pem$|\.key$|secret|token|credential'
git log --all -p -- '**/.env' | head
```

---

## Scope

**In scope:** this repository's backend, frontend, edge collector and monitoring
code; its CI configuration; its documented deployment procedures.

**Out of scope:** third-party services (Google Gemini, Telegram, CFE), the
Raspberry Pi OS and its packages, Shelly device firmware, and any deployment's
own network configuration.
