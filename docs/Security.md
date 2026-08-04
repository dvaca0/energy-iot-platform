# Security

This document states the platform's security posture honestly, including the
parts that are not yet good. A portfolio that presents an unauthenticated API as
"secured" is worth less than one that names the gap and shows it is understood.

For reporting a vulnerability, see [SECURITY.md](../SECURITY.md) at the
repository root.

---

## Threat model

**What this system protects:** electrical consumption data for university
buildings, the integrity of that data, and the reliability of the alerting that
depends on it.

**What it does not hold:** personal data, payment data, credentials to any other
system, or any ability to actuate electrical equipment. The platform is a
**meter, not a controller** — there is no code path that switches anything on or
off, including the smart plugs, whose RPC use is read-only.

**Deployment context:** a single application server, nodes behind ordinary
consumer NAT, an operator population of a handful of facilities staff.

---

## Known gaps

Stated first, because they are the most important thing on this page.

### 1. The ingestion endpoints are unauthenticated

> [!CAUTION]
> `POST /api/v1/measurements/batch`, `POST /api/readings` and
> `POST /api/edge/heartbeat` have **no authentication**. `device_id` is
> self-asserted.

Consequences, in order of severity:

| Consequence | Why it matters |
|---|---|
| **A forged heartbeat can suppress a real outage alert** | This is the worst of the three. An attacker — or a misconfigured test script — that posts heartbeats for a node makes a genuinely dead node look alive. The monitoring subsystem is only as trustworthy as the evidence it reads. |
| Forged measurements can be injected | Corrupts analytics and cost figures for a building |
| Node identity can be impersonated | Attribution becomes unreliable |

**Mitigating factors, which do not make it acceptable:** the server is not
published to the open internet, and `node_commission_states.may_upload`
constrains *which registered nodes* may write — but it does not verify that the
caller *is* that node.

**Status:** documented in
[ADR-0002](../backend/docs/adr/0002-upload-authorization.md). The intended fix is
a per-node shared secret or mTLS on the ingest path. **Not yet implemented.**
This is the single highest-priority item on the [roadmap](../README.md#roadmap).

### 2. CORS is fully permissive

```python
allow_origins=["*"], allow_credentials=False
```

Honest rather than dangerous *today*: there are no cookies, no sessions and no
credentials for a cross-origin request to steal. It becomes dangerous the moment
authentication is added, and tightening it must be part of that change, not a
follow-up.

### 3. The frontend login is not an authorisation boundary

The Settings screen offers a role selector. Roles shape **what the UI shows**;
they are not enforced server-side, because the server does not authenticate
anyone. Treat the UI's role model as presentation, not security.

### 4. No transport encryption is enforced

Nodes post over HTTP to the backend's port. On a trusted site LAN with an
outbound path this is a considered trade-off; it is not one that should survive
the platform being reachable from anywhere untrusted.

---

## Secret handling

### Where secrets live

| Secret | Location | Notes |
|---|---|---|
| `GEMINI_API_KEY` | `backend/.env` | Optional; absent ⇒ LLM narration disabled |
| `MONITORING_TELEGRAM_BOT_TOKEN` | `backend/.env` | Absent ⇒ alerts recorded but not delivered |
| `MONITORING_TELEGRAM_CHAT_ID` | `backend/.env` | |

**Nothing else in this system holds a credential.** There is no database
password (SQLite is a local file), no session signing key, and no third-party
integration beyond Gemini and Telegram.

### Rules

1. **`.env` is never committed.** It is git-ignored, and
   [`backend/.env.example`](../backend/.env.example) is the tracked template.
2. **Telegram credentials are deliberately in `.env`, not in
   `monitoring_config.json`** — specifically so they are never captured by a
   config backup or a support tarball.
3. **`chmod 600 backend/.env`.**
4. **A missing key disables its feature rather than failing the process.** This
   is a deliberate default: the platform degrades to "no LLM, no Telegram"
   rather than refusing to start and taking monitoring down with it.
5. **Never paste a token into a shell command.** It lands in `~/.bash_history`
   and in the process list, where any local user can read it.

### If a secret is exposed

```bash
# 1. Revoke at the source, immediately — before anything else.
#    Gemini:   https://aistudio.google.com/apikey
#    Telegram: @BotFather → /revoke

# 2. Issue a replacement and install it
$EDITOR backend/.env && chmod 600 backend/.env

# 3. Reload
kill -HUP $(systemctl show -p MainPID --value energy-platform-backend.service)
```

> [!WARNING]
> If a secret was ever **committed**, revoking it is mandatory and rewriting
> history is not sufficient. The value must be treated as compromised the moment
> it reaches a remote, because forks, clones, CI caches and GitHub's own
> unreachable-object retention all outlive a force-push.

### Verifying nothing leaked

```bash
# Anything sensitive in the tracked set?
git ls-files | grep -iE '\.env$|\.pem$|\.key$|secret|token|credential'

# Has a secret ever been committed?
git log --all -p -- '**/.env' | head

# Are the ignore rules doing their job?
git check-ignore -v backend/.env backend/energy_platform.db
```

---

## Data handling

| Property | Position |
|---|---|
| **Personal data** | None collected. Readings describe buildings, not people. |
| **Inference risk** | Fine-grained consumption data *can* reveal occupancy patterns for a small building. At panel level across a campus this is weak, but it is not zero, and it is the reason building-level data is not published. |
| **Retention** | Unlimited server-side; 7 days on the node buffer. |
| **Backups** | Contain the full dataset. Treat with the same care as the live database. |
| **LLM boundary** | Only computed aggregates are sent to Gemini, never raw series — and only when `LLM_ENABLED=1`. |

---

## Screenshots and documentation

Screenshots are published in this repository. Before committing one, check for:

- Real names or institutional email addresses beyond the generic `admin@ucol.mx`
- API tokens visible in a settings screen or a browser devtools panel
- Internal hostnames, public IP addresses, or MAC addresses
- Room numbers or anything identifying an individual's location

The same applies to hardware photographs — serial numbers, MAC labels and Wi-Fi
credentials on stickers are all common leaks. See
[`assets/screenshots/MANIFEST.md`](../assets/screenshots/MANIFEST.md).

---

## Dependencies

`pip-audit` and `npm audit` run in CI on every push and weekly; Dependabot
raises update PRs. See [`.github/workflows/`](../.github/workflows/).

```bash
cd backend && venv/bin/python3 -m pip_audit
cd frontend && npm audit
```

---

## Hardening checklist

For anyone deploying this beyond a trusted LAN, in priority order:

- [ ] **Authenticate the ingest endpoints** — per-node shared secret or mTLS
- [ ] Terminate TLS in front of the API; make HTTP redirect
- [ ] Replace `allow_origins=["*"]` with the actual frontend origin
- [ ] Add server-side authentication and enforce the role model
- [ ] Firewall 8010 so only nodes and the frontend host can reach it
- [ ] Rate-limit the ingest path
- [ ] Move backups off the application server
- [ ] Rotate the Gemini and Telegram credentials on a schedule
