# THESIS_TECHNICAL_EVIDENCE

Technical evidence dossier for the Energy Monitoring / Energy Intelligence
Platform (Universidad de Colima). Compiled **2026-08-13** by direct audit of:
the repository at `/home/manager/energy-platform`, the live SQLite database, the
running services, and two of the three edge nodes over SSH.

**This document is not thesis prose.** It is an evidence base. Nothing here is
estimated unless the word *estimate* appears. Where two sources disagree, both
are stated and the contradiction is labelled.

---

## Evidence Quality Legend

| Label | Meaning |
|---|---|
| **VERIFIED** | Directly observed by the auditor in the current implementation, live database, running process, or node filesystem on 2026-08-13. The verification command is given. |
| **DOCUMENTED** | Stated in project documentation. Not independently re-verified. May be stale. |
| **HISTORICAL** | True of an earlier version. Superseded. |
| **EXPERIMENTAL** | Prototype, bring-up, or bench work. Not production. |
| **PLANNED** | Intended, written down, not implemented. |
| **UNCERTAIN** | Insufficient evidence to classify. |
| **⚠ CONTRADICTION** | Two sources disagree. Both are reported; neither is silently chosen. |

---

## Executive summary of the audit

Six findings that change how the system should be described in a thesis. Each is
expanded in the relevant phase.

1. **⚠ The production nodes do not use the ADS1256.** N001 and N002 read a
   **Shelly Pro 3EM** over HTTP RPC. The ADS1256 + CT front end exists only on
   N003, and it is currently electrically dead. Multiple repository documents
   state the opposite. → §2.B, §Contradictions C-01.
2. **⚠ Ingestion is authenticated and enforced as of 2026-08-06/07.** README,
   `docs/Security.md`, `docs/Architecture.md` and ADR-0002 all still describe it
   as unauthenticated. → §2.E, C-02.
3. **The canonical measurement contract (ADR-0007) is specified but not
   emitted.** `energy_source` and `interval_energy_kwh` are `NULL` on all
   290,439 rows. No collector sends them. → §2.C, §7.
4. **The KMeans clustering result is not derived from KMeans.** The model is
   fitted, but its labels are discarded; cluster names come from fixed
   thresholds. → §2.H.
5. **N003's ADS1256 current channels are uncalibrated** (`CURRENT_SCALE = 1.0`)
   and its power factor is computed from **non-simultaneous** V and I sample
   arrays. → §2.B, §5, §7.
6. **The dataset is one instrumented node.** Of 290,439 readings, real
   production-attributed load from a real campus panel is N001 only. → §6.

---

# PHASE 1 — DOCUMENT INVENTORY

Search method (VERIFIED):

```bash
find /home/manager/energy-platform -name "*.md" -not -path "*/venv/*" -not -path "*/node_modules/*" -not -path "*/.git/*"
```

61 project Markdown files (excluding vendored library docs). Node filesystems
were searched separately (§1.7).

## 1.1 Repository root

| FILE | PURPOSE | CURRENT/HISTORICAL | THESIS RELEVANCE | IMPORTANT INFORMATION CONTAINED |
|---|---|---|---|---|
| `README.md` | Repository front door | CURRENT, but figures dated 2026-08-04 | **High** — headline numbers | 255,379 measurements / 39 rules / 90 routes / 12 migrations / 33 tables; 15 s sample, 45 s heartbeat, 7-day buffer; known-limitations table; roadmap; "ingesting continuously since May 2026". Several figures now stale — see §Contradictions. |
| `CHANGELOG.md` | Versioned history, Keep-a-Changelog | CURRENT to v1.2.0 (2026-08-04) | **Very high** — Phase 3 backbone | Releases 0.1.0 (2026-06-14 first measurements) → 1.2.0. Records the 1,386-Telegram-message incident, the two vacuously-passing test suites, three undeclared dependencies, the `energy_kwh` dual-meaning defect. |
| `CLAUDE.md` | AI-assistant contribution rules | CURRENT | Low (process) | Commit-attribution policy; two engineering constraints restated. |
| `CONTRIBUTING.md` | Contribution rules | CURRENT | Medium | "Five rules that are not negotiable, each of which exists because breaking it caused a production incident." |
| `SECURITY.md`, `CODE_OF_CONDUCT.md` | Community health | CURRENT | Low | — |
| `Makefile`, `pyproject.toml` | Build/quality gates | CURRENT | Medium | `make check` = ruff/black/isort + requirements check + 4 hermetic suites + link check + mermaid check + API-doc check. |

## 1.2 `docs/` — the whole-system documentation set (18 documents)

| FILE | PURPOSE | CURRENT/HISTORICAL | THESIS RELEVANCE | IMPORTANT INFORMATION CONTAINED |
|---|---|---|---|---|
| `docs/Architecture.md` | Whole-system tier view | CURRENT except §6 | **Very high** | Three tiers; four structural decisions (separate scheduler, buffer-before-upload, SQLite/WAL, no hardware logic in backend); the five concepts and their owners; ingestion sequence; "what is deliberately absent" (no containers, no broker, no ORM migration framework). |
| `docs/Database.md` | Data model | CURRENT except counts | **Very high** | Why SQLite; ER diagram; table groups; 12 migrations; index-collision-on-rename lesson; `NOT NULL` on `building_id`/`deployment_id`. |
| `docs/Backend.md` | Backend structure | CURRENT | **High** | Layering rules (router never writes SQL; service never knows HTTP); 20 routers; 11 services; `anomaly_engine` vs `app/monitoring/` distinction; `SIGHUP` reload. |
| `docs/Collector.md` | Edge measurement software | CURRENT as *contract*, ⚠ stale as *fact* | **Very high** | Two independent loops (15 s sample / 60 s sync); payload schema; `energy_source` rationale; hardware-family mapping; replay/attribution warning; **explicitly states the base collector is not in the repository**. |
| `docs/Hardware.md` | Physical layer | ⚠ partly contradicted | **High** | Fleet table; node block diagram; why a 24-bit ADC; installation procedure; panel ratings feed threshold resolution; failure modes ordered by real frequency; **BOM explicitly not recorded**. |
| `docs/Networking.md` | Topology and ports | CURRENT | **High** | Outbound-only property; ports 8010/5174/5175; node has no required inbound; failure behaviour table; fail2ban warning. |
| `docs/Monitoring.md` | Monitoring design + policy | CURRENT, rule count stale | **Very high** | 39 rules (now 42); rule distribution; the pipeline; **the four alerting principles and the incident numbers behind each**; threshold resolution chain; alert lifecycle state machine; extension checklist. |
| `docs/AI.md` | Analytics | CURRENT as description, ⚠ feature list wrong | **Very high** | Three sklearn models; data-scope filter; honesty guarantees; two different "anomaly" systems; LLM boundaries. |
| `docs/Smart-Plugs.md` | Sub-metering | CURRENT | **High** | Plugs are accessories of a deployment, never nodes; discovery only on the Pi; MAC as identity; read-only RPC. |
| `docs/Smart-Plug-Architecture.md` | Deep reference | CURRENT | Medium-High | Ownership model, buffer separation. |
| `docs/Deployment.md` | Production operation | CURRENT | Medium-High | Unit table; boot order; `-w 1` is a database constraint. |
| `docs/Recovery.md` | Backup/restore | CURRENT | **High** | `cp` produces a silently corrupt backup; restore procedure; **backups live on the application server** (largest durability gap). |
| `docs/Security.md` | Security posture | ⚠ **stale** | **High** | Threat model; "meter, not a controller"; known gaps — gap #1 is now closed, document not updated. |
| `docs/Fleet-Manifest.md` | Node inventory, drift detection | CURRENT (2026-08-07) | **Very high** | Per-node hardware/software/platform-state matrix; every ⚠ is drift; CT ratings 120/400/1000 A; `get_throttled` values; capabilities-and-honest-degradation table. |
| `docs/Energy-Node-Package.md` | Reference node build v2.1 | CURRENT | **High** | Compatibility matrix Pi 5 vs Pi 3B+; included services; `node.env` keys; layout; install/upgrade/verify/rollback procedures; fleet checksum `d9cc6138c8be60b273615d13`; **Pi 3B+ explicitly unsupported**. |
| `docs/Recovery.md`, `docs/Troubleshooting.md`, `docs/Development.md`, `docs/Versioning.md` | Operations | CURRENT | Medium | Versioning: four independently released components; "the measurement contract is the most consequential compatibility surface". |
| `docs/P2-Simplification-Audit.md` | Simplification audit 2026-08-07 | CURRENT | **High** | The headline finding: the "obviously redundant" service was load-bearing; D1/D2/D3 drift items; S1–S5 server items; explicit KEEP list. |
| `docs/API.md` | Route reference | CURRENT, CI-verified | Medium-High | Generated from the running OpenAPI schema; `scripts/check_api_docs.py` fails the build on an undocumented route. |
| `docs/diagrams/README.md` | 12 Mermaid system diagrams | CURRENT | **High** (figures) | Ready-made thesis figures. |
| `docs/prototype/README.md` | Phase-1 prototype provenance | HISTORICAL | Medium | The single-file React 18 prototype the app was migrated from on 2026-06-14; kept for provenance, not part of the app. |
| `docs/Runbook-Retention.md` | Storage retention | CURRENT | Low-Medium | Daily 03:30 cron; milestone backups never deleted. |
| `docs/deployments/*.md` (7 files) | Per-node smart-plug install reports, 2026-07-25 | HISTORICAL record | Medium | Auto-generated deployment reports for `energy-node-001`, `energy-node-002`, `ucol-UBU`. |

## 1.3 `backend/docs/` — ADRs and design records

| FILE | PURPOSE | CURRENT/HISTORICAL | THESIS RELEVANCE | IMPORTANT INFORMATION CONTAINED |
|---|---|---|---|---|
| `adr/0001-separate-identity-health-lifecycle-attribution.md` | Five concepts, five owners | CURRENT | **Very high** | Names four production defects by file and line (`dashboard.py:340`, `deployments.py:48`, `edge.py:64`, `alerts.py:55`). Predicts the KPI will change from 2 to 0 and says that is the fix, not a regression. |
| `adr/0002-upload-authorization.md` | Auth by commissioning, not lifecycle | ⚠ **status superseded** | **Very high** | Three ordered questions: authenticate → authorize → attribute. Says "authentication is phased… accepted and logged but not enforced". **That is no longer true.** Rejected alternatives: widen the status filter; per-node IP allowlist. |
| `adr/0003-explicit-measurement-context.md` | Context declared, never inferred | CURRENT | **Very high** | Six contexts and their distinguishing tests; the context×attribution matrix; **explicitly records that an earlier draft inferred context from attribution and was rejected in review**. |
| `adr/0004-immutable-timestamp-attribution.md` | Per-row attribution by `captured_at` | CURRENT | **Very high** | The `order_by(Deployment.id.desc())` defect; immutability scoped as "immutable at runtime, correctable only by supervised migration"; `BEFORE UPDATE` trigger. |
| `adr/0005-migration-invariants.md` | Migrations gated by invariants | CURRENT | **High** | Five-step runner; 15 (now 16) invariants; bounded-by-snapshot-id design; rollback ships with the change; `INV-15` timestamp reasoning. |
| `adr/0006-legacy-deployment-dates-non-authoritative.md` | Legacy metadata is not authoritative | CURRENT | **Very high** | The rows-inside-window table (N001 25,779 in / 75,903 out; N003 158 in / 123,459 out); building 8 is a development placeholder; N003's May–June data is real prototype acquisition that must not be back-attributed. |
| `adr/0007-canonical-measurement-model.md` | The measurement contract | CURRENT as spec, **not implemented** | **Very high** | The two eras of `energy_kwh` with their evidence; the five canonical fields; why interval energy beats cumulative (additive, immune to resets and gaps). |
| `ARCHITECTURE.md` | Definitive backend reference | CURRENT | **Very high** | The 16 invariants in full; attribution reason codes; migration philosophy (7 principles); recovery philosophy (5 layers); two SQLite specifics that cost real debugging. |
| `collector-contract.md` | Normative collector spec | CURRENT as spec | **High** | The contract the backend promises never to change. |
| `canonical-measurement-implementation.md` | M12 implementation record | CURRENT | Medium-High | How ADR-0007 was implemented server-side. |
| `deployment-integrity-design.md` / `-rev2.md` / `-final-review.md` | Deployment integrity design, three revisions | rev2 CURRENT; rev1 HISTORICAL | **High** | Shows a design that was revised twice under review — good thesis material on process. |
| `investigation-building-name-provenance.md` | Where building names came from | CURRENT | Medium-High | Provenance investigation of the placeholder-building problem. |
| `m8-cutover-package.md`, `m8-production-cutover-runbook.md` | The riskiest migration's runbook | HISTORICAL record | **High** | A 21 KB production cutover runbook — evidence of migration discipline. |
| `m11-backfill-validation.md`, `m13-api-lifecycle-review.md` | Post-migration validation | HISTORICAL record | **High** (Phase 5) | Validation evidence for migrations 11 and 13. |
| `migration-baselines/*.md` (2 files) | Pre-migration state snapshots | HISTORICAL record | Medium-High | The before-state of a production rebuild committed as record, not memory. |
| `smart-plugs-api.md` | Smart-plug API reference | CURRENT | Medium | Discovery payload contract; MAC-keyed upsert; `(smart_plug_id, timestamp)` uniqueness makes replay idempotent. |
| `migrations/README.md` | Migration runner usage | CURRENT | Medium | — |

## 1.4 `edge/` — edge components

| FILE | PURPOSE | CURRENT/HISTORICAL | THESIS RELEVANCE | IMPORTANT INFORMATION CONTAINED |
|---|---|---|---|---|
| `edge/CHANGELOG.md` | Smart-plug edge component, v1.0.0 → 1.2.0 | CURRENT | **High** | 1.2.0 (2026-07-25): health diagnostics, explicit ownership, upgrade-aware installer. 1.1.0: identify by **capability** not product name. Rollback notes per version. |
| `edge/HANDOFF-raspberry-pi.md` | Session handoff for the Pi integration | HISTORICAL record | **Very high** | Explicitly names this as "my University thesis project". Records the known plug MACs, the three node codes, "the Pis are behind NAT and push outbound only", the 5 min / 15 s plug schedule, read-only RPC, and — critically — *"Nothing about the existing Pi collector is known: it was never inspectable from the cloud server."* |
| `edge/DEPLOYMENT.md` | Smart-plug deploy notes | CURRENT | Medium | — |
| `edge/README-smart-plugs.md` | Pi-side install/behaviour reference | CURRENT | Medium-High | — |
| `edge/node/README.md` | Node package overview | CURRENT | Medium | — |
| `edge/node/net/README.md` | **Networking & maintenance subsystem** | CURRENT | **Very high** | Full architecture of `energy-node-netd`; layering with a pure, I/O-free decision layer; the one-fact collector boundary and its **fail-open** rule; the five-state machine; connectivity priority and `ethernet_is_uplink`; maintenance AP design; portal trust boundary; factory network reset scope; **46 unit tests**. |
| `edge/node/hardening/docs/node-hardening.md` | Hardening package 2.0.0 | CURRENT | **High** | 12 modules; capability tri-state (absent ≠ present-and-failing). |
| `edge/node/hardening/docs/node-rollout.md` | Rollout procedure | CURRENT | Medium-High | — |
| `edge/node/hardening/docs/recovery-validation.md` | **Recovery validation plan V1–V11** | **PLANNED — explicitly unexecuted** | **Very high** (Phase 5 & 7) | Opens: *"Nothing in this document has been executed."* Ground-truth table distinguishing power loss from brownout latch by RTC state; 11 experiments with prerequisites, method, risk and rollback; the decision point at V5 Phase B. |
| `edge/node/hardening/backend/README.md` | Server-side pieces of the hardening work | CURRENT | Medium | — |

## 1.5 `monitoring/`

| FILE | PURPOSE | CURRENT/HISTORICAL | THESIS RELEVANCE | IMPORTANT INFORMATION CONTAINED |
|---|---|---|---|---|
| `monitoring/README.md` (21.6 KB) | Monitoring operator guide, v1.1.0 | CURRENT | **Very high** | The largest single monitoring document; rule catalogue, config layering, operational procedures. |
| `monitoring/evidence/identity-collision-20260806_134531.md` | Root-cause: two producers publishing as N001 | HISTORICAL incident record | **Very high** | Proves same machine by PID/uptime/buffer-size discriminators; identifies an *old collector left in a backup directory* as producer 2; **discloses that the audit itself triggered the second window** by invoking a backup agent whose `--dry-run` flag it silently ignored. |
| `monitoring/evidence/filesystem-readonly-20260806_134531.md` | Root-cause: false read-only EMERGENCY | HISTORICAL incident record | **Very high** | `ProtectSystem=strict` puts the service in a private mount namespace where `/` genuinely *is* read-only. Verified with `nsenter`. Conclusion: *"the value is not wrong about the namespace — it is the wrong question."* |
| `monitoring/evidence/node03-audit-20260806_144255.md` | N003 full audit | CURRENT | **Very high** | The N001/N002 vs N003 difference table; hardware reality (no PMIC ADC, no usable I²C, SPI present); **the unit is named "ADS1256 Collector" but `poller.py` was converted to read a Shelly EM** — backups dated 2026-07-24 prove the conversion. |
| `monitoring/evidence/affected-rows-20260806_142730.md` | Read-only affected-row report | HISTORICAL record | **High** | 10,450 N001 rows + 4,499 N003 rows carrying attribution outside any operational window. |
| `monitoring/evidence/storage-inventory-before-20260807_131441.md` | Pre-retention storage state | HISTORICAL record | Medium | Root FS 86% used; 37 migration backups totalling 4.9 GB. |

## 1.6 `assets/`, `.github/`, `scripts/`

| FILE | PURPOSE | THESIS RELEVANCE | CONTENTS |
|---|---|---|---|
| `assets/screenshots/MANIFEST.md` | 15 UI screenshots + capture guidance | **High** (figures) | Also lists the **outstanding hardware photographs** — the one gap in the visual record. |
| `assets/branding/README.md` | Brand identity, contrast checked | Low | — |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR checklist | Low | — |
| `scripts/check_api_docs.py`, `check_links.py`, `check_requirements.py`, `gen_api_docs.py`, `retention.py` | CI gates + retention | Medium | Not Markdown, but they are what makes several documentation claims verifiable. |

## 1.7 Markdown files found **on the nodes** (VERIFIED 2026-08-13 over SSH)

Requested addition. Method: `find / -xdev -name "*.md"` on each node, excluding
OS package docs and assistant plugin trees.

**Access note (VERIFIED):** the Tailscale addresses `100.125.1.37`,
`100.98.67.31`, `100.79.227.108` **do not route from the application server** —
Tailscale is not installed there. Nodes were reached on their public NAT
addresses taken from `monitor_node_heartbeats.source_ip`.

| Node | Address used | SSH reachable | Result |
|---|---|---|---|
| **N001** | `148.213.168.238` (current) and `148.213.2.186` (previous) | **No** — port 22 filtered on both | **Not surveyed.** See §Open questions Q-11. |
| **N002** | `148.213.2.245` | Yes | Surveyed — 9 project `.md` files |
| **N003** | `148.213.2.153` | Yes | Surveyed — 2 project `.md` files |

### N002 — `energy-node-002`

| PATH ON NODE | REPOSITORY COUNTERPART | SHA-256 (24) | VERDICT |
|---|---|---|---|
| `/opt/energy-node/net/README.md` | `edge/node/net/README.md` | `21cada32aca23cb5` | **Byte-identical** |
| `/opt/energy-node/hardening/backend/README.md` | `edge/node/hardening/backend/README.md` | `099161d66b33c659` | **Byte-identical** |
| `/opt/energy-node/hardening/docs/node-hardening.md` | same path under `edge/node/` | `69b73f97a9a4ab72` | **Byte-identical** |
| `/opt/energy-node/hardening/docs/recovery-validation.md` | same | `020c68a4a8ea066f` | **Byte-identical** |
| `/opt/energy-node/hardening/docs/node-rollout.md` | same | `4c1fcf66e41c0f47` | **Byte-identical** |
| `/opt/energy-node/docs/README-smart-plugs.md` | `edge/README-smart-plugs.md` | `e34bc3cdb3276fe8` | **Byte-identical** |
| `/opt/energy-node/docs/CHANGELOG.md` | `edge/CHANGELOG.md` | `ea938ea3055c00f2` | **Byte-identical** |
| `/home/theblackdie/energy-node-net/README.md` | `edge/node/net/README.md` | `21cada32aca23cb5` | Byte-identical (staging copy) |
| `/home/theblackdie/energy-node-tools-disabled-20260720_200132/README.md` | — | `e3b0c44298fc1c14` | **Empty file** (zero bytes) |
| `/opt/energy-node/backups/recovery-manager-20260810_085923/hardening/{backend/README,docs/*}.md` | — | — | Pre-upgrade backup copies of the four hardening docs |

### N003 — `ucol-UBU`

| PATH ON NODE | REPOSITORY COUNTERPART | SHA-256 (24) | VERDICT |
|---|---|---|---|
| `/opt/energy-node/net/README.md` | `edge/node/net/README.md` | `21cada32aca23cb5` | **Byte-identical** |
| `/home/theblackdie/docs/README-smart-plugs.md` | `edge/README-smart-plugs.md` | `e34bc3cdb3276fe8` | **Byte-identical** |

### Conclusion for Phase 1 node survey — VERIFIED

**No node carries documentation that is not already in the repository.** Every
project `.md` file found on N002 and N003 is byte-identical to its repository
counterpart. The vendoring performed on 2026-08-10 (`chore(edge): vendor node
hardening and networking packages`) is complete and exact with respect to
documentation.

The **code** situation is different — see §2.C. The base collector
(`collector.py` on N001/N002, `poller.py` on N003) is **not** in the repository,
and that is the single largest provenance gap in the project.

---

# PHASE 2 — CURRENT SYSTEM AUDIT

State as of **2026-08-13**, verified against the running system.

## 2.A System architecture

### A.1 The path from physical measurement to user interface — VERIFIED

```
PHYSICAL          EDGE                          TRANSPORT      CORE                         SURFACE
─────────────────────────────────────────────────────────────────────────────────────────────────
3-phase           N001/N002:                    HTTP           FastAPI :8010                React 19
panel     ──CT──▶ Shelly Pro 3EM  ──HTTP RPC──▶ collector.py   POST /api/v1/measurements/    :5174
conductors        (the meter does the           15 s poll      batch                         (:5175 staging)
                   measuring)                        │              │
                                                     ▼              ├─ 1. authenticate (bearer)
                  local SQLite buffer                              ├─ 2. authorize (may_upload)
                  edge_buffer.db (WAL)                             ├─ 3. classify (context)
                  sync_status 0/1/2                                └─ 4. attribute (by captured_at)
                                                     │                     │
                                                60 s sync loop             ▼
                                                     │              energy_readings (SQLite WAL)
                  heartbeat ~50 fields               │                     │
                  60 s → /api/monitoring/heartbeat   │              ┌──────┴──────┐
                                                     │              ▼             ▼
                  Shelly Plug US Gen4 ×4             │        services/      monitoring
                  discovery 5 min / poll 15 s        │        cost_engine    scheduler
                  separate smart_plugs.db            │        ml_engine      (SEPARATE
                                                     │        anomaly_engine  PROCESS)
                                                     │        attribution        │
                  N003: ADS1256 ×2 + CT/V ───────────┘        reports            ▼
                       (front end dead)                            │        Telegram
                                                                   ▼        (durable outbox)
                                                              PDF / XLSX
```

**Verification commands:**

```bash
ps aux | grep -E "gunicorn|scheduler|static_server"
ss -lntp | grep -E "8010|5174|5175"
systemctl list-units --type=service | grep energy
curl -s http://127.0.0.1:8010/openapi.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['paths']))"
```

### A.2 Layers and components — VERIFIED

| Tier | Component | Process / unit | Language | Evidence |
|---|---|---|---|---|
| Edge | Measurement collector | `energy-node-collector` (N001/N002), `udec-edge` (N003) | Python 3.13 | `systemctl cat`, node filesystem |
| Edge | Networking supervisor | `energy-node-netd` | Python 3 | `edge/node/net/` |
| Edge | Maintenance portal | `energy-node-portal` | Python 3 | idem |
| Edge | Appliance console (tty1) | `energy-node-console` | Python 3 (urwid) | idem |
| Edge | Power/UPS logger | `energy-node-powerlog` | Python 3 | `edge/node/hardening/lib/powerlog.py` |
| Edge | Black-box recorder | `energy-node-blackbox` (oneshot) | Python 3 | `edge/node/hardening/lib/blackbox.py` |
| Edge | Recovery manager | `energy-node-recovery` (**N002 only**) | Python 3 | `edge/node/hardening/lib/recovery/` |
| Edge | Smart-plug source | in-collector threads | Python 3 | `edge/smart_plug_source.py` |
| Core | API + ingestion | `energy-platform-backend.service`, gunicorn `-w 1` + uvicorn worker, :8010 | Python 3.12 | `ps aux` PID 4147468 |
| Core | Monitoring scheduler | `flock … python3 -m app.monitoring.scheduler` | Python 3.12 | `ps aux` PIDs 2528252/2528253, running since Aug 07 |
| Core | Production static server | `energy-platform-frontend.service`, :5174 | Python 3 | `ps aux` PID 857256 |
| Core | Staging static server | `static_server_test.py`, :5175 | Python 3 | `ps aux` PID 1712654 |
| Core | Database | SQLite WAL, `backend/energy_platform.db` | — | 311.2 MB + 4.4 MB WAL |
| Surface | Dashboard | static React 19 build | TypeScript | `frontend/dist` |
| Surface | Alerts | Telegram bot `@ThesisIoT_bot` | — | `monitor_notification_outbox` |
| Surface | Reports | PDF (WeasyPrint) / XLSX / CSV | Python | `app/routers/reports.py`, 13 routes |

**Load-bearing structural decisions** (DOCUMENTED in `docs/Architecture.md` §2,
each VERIFIED as implemented):

1. The monitoring scheduler is a **separate OS process**, not a background task.
2. The edge buffer is written **before** any upload is attempted.
3. SQLite in WAL mode is a **considered choice**, not a PostgreSQL placeholder.
4. The backend contains **no hardware-specific logic**.

## 2.B Hardware / edge nodes

### B.1 The fleet — VERIFIED (`docs/Fleet-Manifest.md` 2026-08-07 + live DB + SSH 2026-08-13)

| | **N001** | **N002** | **N003** |
|---|---|---|---|
| Hostname | `energy-node-001` | `energy-node-002` | `ucol-UBU` |
| Board | Raspberry Pi 5 Model B Rev 1.1 | Raspberry Pi 5 Model B Rev 1.1 | **Raspberry Pi 3 Model B+ Rev 1.3** |
| OS / Python | Debian 13 (trixie) / 3.13.5 | idem | idem |
| Kernel | `6.18.34+rpt-rpi-2712` | idem | not surveyed |
| **Measuring device** | **Shelly Pro 3EM** `shellypro3em-a4f00fd05558` | **Shelly Pro 3EM 400 A** `shellypro3em400-ecc9ffe730f4` | **2 × ADS1256** (+ a Shelly EM code path, inactive) |
| Rated CT | 120 A | 400 A | 1000 A |
| UPS | Waveshare UPS HAT (SKU25567) | Waveshare UPS HAT (SKU25567) | HAT present, **not readable** |
| SPI devices | `spidev0.0`, `spidev0.1` | **none** | `spidev0.0`, `spidev0.1` |
| I²C buses | `i2c-1`, `i2c-13`, `i2c-14` | idem | **`i2c-2` only** (HDMI DDC; GPIO bus not enabled) |
| PMIC ADC (per-rail power) | yes | yes | **no** (Pi 3 has none) |
| `vcgencmd get_throttled` | `0x50000` | `0x50000` | `0x80000` |
| Collector path | `/opt/energy-node/app/collector.py` | idem, **byte-identical** | `/home/theblackdie/udec-edge/poller.py` |
| Collector SHA-256 (24) | `d9cc6138c8be60b273615d13` | `d9cc6138c8be60b273615d13` | n/a |
| Hardening package | 2.0.0, 12 modules | 2.0.0, 12 modules | **absent** |
| Commission state (live) | `commissioned` | `registered` | `registered` |
| `may_upload` | yes | **no** | **no** |
| Measurement context (live) | `infrastructure_validation` | `infrastructure_validation` | `infrastructure_validation` |
| Heartbeat producer | collector, v2.0.0 | collector, v2.0.0 | `poller.py`, `udec-edge-1.1.0` |
| Node role | **The only production-measuring node** | Standby by design | Prototype / ADS1256 development |

`get_throttled = 0x50000` on both Pi 5 nodes means **undervoltage and throttling
have occurred since boot** (sticky bits). `0x80000` on N003 means a soft
temperature limit has occurred. — VERIFIED, `docs/Fleet-Manifest.md`.

### B.2 ⚠ CONTRADICTION C-01 — what actually measures

**Claimed** (`README.md`, `docs/Hardware.md`, `docs/Architecture.md`,
`docs/Collector.md` §"Raw analogue front ends"):

> "Raspberry Pi nodes sample at 15 s through a 24-bit ADS1256 and non-invasive CT
> clamps." … "This is the path used by the production nodes."

**Observed** — VERIFIED 2026-08-13 by reading `/opt/energy-node/app/collector.py`
on N002 and `/opt/energy-node/config/node.env`:

```python
SHELLY_EM_URL  = f"http://{CONFIG['SHELLY_IP']}/rpc/EM.GetStatus?id=0"
SHELLY_SYS_URL = f"http://{CONFIG['SHELLY_IP']}/rpc/Sys.GetStatus"
```
```
NODE_ID=N002
SHELLY_IP=192.168.50.10
SHELLY_ID=shellypro3em400-ecc9ffe730f4
```

The canonical collector on the Pi 5 nodes contains **no ADC code at all**. It is
an HTTP client for a **Shelly Pro 3EM** three-phase energy meter on a private
Ethernet segment (`192.168.50.0/24`, meter at `.10`). N002 has **no `spidev`
device**, so it could not drive an ADC even if the code existed.

**The ADS1256 path exists only on N003.** `docs/Fleet-Manifest.md` and
`monitoring/evidence/node03-audit-20260806_144255.md` are correct; the
higher-level documents are not.

**Consequence for the thesis:** the instrument that produced essentially all
usable data is a **commercial three-phase meter**, and the custom ADS1256
acquisition chain is a **parallel prototype line** that has not yet produced
production data. Both are legitimate contributions — but they must not be
conflated.

### B.3 The Shelly Pro 3EM measurement path (N001, N002) — VERIFIED

| Property | Value | Evidence |
|---|---|---|
| Device | Shelly Pro 3EM (N001, 120 A CT) / Pro 3EM 400 A (N002) | `node.env`, Fleet Manifest |
| Interface | HTTP Gen2 RPC, `GET /rpc/EM.GetStatus?id=0` | `collector.py` |
| Segment | Private Ethernet `192.168.50.0/24`, meter at `.10`, node at `.2` | `node.env`, heartbeat `ip_address` |
| Poll interval | `POLL_INTERVAL=15` s | `node.env` |
| Sync interval | `SYNC_INTERVAL=60` s | `node.env` |
| Sync batch | `SYNC_BATCH_SIZE=100` | `node.env` |
| Timeouts | `SHELLY_TIMEOUT=5`, `CENTRAL_TIMEOUT=10`, `MAX_RETRIES=3` | `node.env` |
| Quantities | per-phase V, I, active/apparent power, PF, frequency; totals | `deployment_week.csv` header, DB columns |
| Backend URL | `http://148.213.1.15:8010` | `node.env` |
| Credential | `NODE_AUTH_TOKEN` in `node.env`, mode 600 | VERIFIED present |

The CT clamps are **part of the Shelly Pro 3EM installation**, not connected to
the Pi. The Pi does no analogue work on these nodes.

### B.4 The ADS1256 acquisition chain (N003) — VERIFIED by source, 2026-08-13

Read directly from `/home/theblackdie/udec-edge/` on N003. **This code is not in
the repository.**

**Module structure:**

```
udec-edge/
  poller.py                    main loop, buffer, sync, auth   (23,308 B, root-owned)
  sources/ads.py               instantiates 2 ADCs + engine; SOURCE selector
  drivers/ads1256.py           SPI register-level driver
  acquisition/voltage_sampler.py
  acquisition/current_sampler.py
  engine/measurement.py        per-phase measurement assembly
  processing/electrical.py     scaling, RMS, power, power factor
  processing/rms.py            DC removal, RMS, peak-to-peak
```

**Two ADS1256 devices** — VERIFIED, `sources/ads.py`:

| | Voltage ADC | Current ADC |
|---|---|---|
| SPI | `bus=0, device=0` (`spidev0.0`) | `bus=0, device=1` (`spidev0.1`) |
| DRDY | GPIO 22 | GPIO 25 |
| CS (manual) | GPIO 7 | GPIO 8 |
| PDWN | GPIO 27 | GPIO 24 |
| DRATE register | `0xD0` | `0xD0` |

**Driver configuration** — VERIFIED, `drivers/ads1256.py`:

| Property | Value |
|---|---|
| SPI mode | `0b01` (mode 1) |
| Chip select | `spi.no_cs = True` — CS driven manually via GPIO |
| Reference voltage | `VREF = 2.5` |
| Full scale | `raw × (2 × VREF / gain) / 8388607.0` (24-bit signed) |
| Registers used | `STATUS 0x00`, `MUX 0x01`, `ADCON 0x02`, `DRATE 0x03` |
| Commands | `WAKEUP 0x00`, `RDATA 0x01`, `RREG 0x10`, `WREG 0x50`, `SYNC 0xFC`, `RESET 0xFE`, `SELFCAL 0xF0`, `SDATAC 0x0F` |
| DRDY wait | `wait_drdy(timeout=1)` |

**Channel mapping** — VERIFIED, identical in both samplers:

| Phase | MUX byte | Differential pair |
|---|---|---|
| A | `0x01` | AIN0 / AIN1 |
| B | `0x23` | AIN2 / AIN3 |
| C | `0x45` | AIN4 / AIN5 |

**Sampling configuration** — VERIFIED, `engine/measurement.py`:

- `samples = 2500` per phase, per quantity, per measurement (default).
- Per 15 s cycle: 3 phases × 2 quantities × 2500 = **15,000 ADC reads**.
- **Voltage and current for a phase are acquired sequentially, not
  simultaneously** — `measure_phase()` calls `self.v.acquire_phase(...)` to
  completion, then `self.i.acquire_phase(...)`.

**Signal processing** — VERIFIED, `processing/electrical.py`:

```python
VOLTAGE_SCALE = {"A": 132.3452, "B": 130.4466, "C": 130.4163}
CURRENT_SCALE = {"A": 1.0, "B": 1.0, "C": 1.0}

def voltage_rms(samples, phase): return rms(remove_dc(samples)) * VOLTAGE_SCALE[phase]
def current_rms(samples, phase): return rms(remove_dc(samples)) * CURRENT_SCALE[phase]
def apparent_power(vrms, irms):  return vrms * irms
def real_power(vrms, irms, pf):  return vrms * irms * pf
def reactive_power(s, p):        return math.sqrt(max(0.0, s*s - p*p))
def power_factor(v_samples, i_samples):
    v, i = remove_dc(v_samples), remove_dc(i_samples)
    ...
    return sum(a*b for a, b in zip(v, i)) / (len(v) * vrms * irms)
```

**Four measurement limitations, all VERIFIED from this source:**

| # | Limitation | Evidence | Consequence |
|---|---|---|---|
| L-1 | **The voltage channels are calibrated per phase; the current channels are not.** | `CURRENT_SCALE = {A:1.0, B:1.0, C:1.0}` | `current_a` is the CT channel's RMS **in ADC volts**, not amperes. Every derived power figure inherits the error. |
| L-2 | **Power factor is computed from non-simultaneous samples.** | `measure_phase()` acquires all 2500 V samples, then all 2500 I samples | The V–I phase relationship is destroyed by construction. The correlation computed is not the electrical power factor. |
| L-3 | **Frequency is not measured.** | `sources/ads.py` emits `"frequency_a": 60.0` (and b, c) as literals | Any frequency figure attributed to N003 is a constant, not an observation. |
| L-4 | **A dead front end is indistinguishable from a zero reading.** | `wait_drdy()` only guards against DRDY stuck *high*; an absent board leaves DRDY *low* and returns immediately. `remove_dc()` + `rms()` turn a constant into exactly `0.0` | See B.5. |

The origin of the three `VOLTAGE_SCALE` constants (132.3452 / 130.4466 /
130.4163) is **not recorded in any file found**. → Q-03.

### B.5 N003's ADS1256 front end is electrically dead — VERIFIED 2026-08-13

Established in a prior session with the collector stopped for exclusive SPI
access, and corroborated by the live database today.

| Evidence | Value |
|---|---|
| `STATUS` register, both chips (bus0 dev0, bus0 dev1) | `0x00` — factory chip-ID nibble should be `0x3` |
| `MUX` / `ADCON` / `DRATE` read-back after writing `STATUS=0x30`, `DRATE=0xD0` | `0x00` — writes do not stick, MISO undriven |
| Raw codes, 400 samples × 3 phases × 2 ADCs | all constant `0`; `distinct = 1/400`; stdev `0.00` |
| Tracebacks in the node's entire log history | **zero** |

**Database corroboration** (VERIFIED, live query today):

| N003 era | Context | Rows | avg `power_kw` | avg `voltage` |
|---|---|---:|---:|---:|
| 2026-07-24 → 07-26 | `bench` | 3,335 | −0.0 | **128.64** |
| 2026-07-26 → 08-06 | `production` | 4,499 | −0.0 | **0.7956** |

The voltage channel was alive during bring-up and went to zero around
2026-07-26. **Exactly `0.0` voltage is the diagnostic**: genuinely idle mains
still reads ~127 V with current at the ~1e-5 A noise floor.

**Consequence:** the **7,217 rows currently buffered on N003 with
`sync_status = 0`** (2026-08-06 → 2026-08-13, VERIFIED by direct query of
`edge_buffer.db`) are **artifacts, not measurements**. They must not be uploaded.
Requires on-site work — the boards are unpowered or the ribbon is unseated.

### B.6 Smart plugs — VERIFIED (live DB, 2026-08-13)

| Property | Value |
|---|---|
| Model | **Shelly Plug US Gen4**, `S4PL-00116US` × 4 |
| Firmware | `1.7.99-plugusg4prod1` (all four) |
| MACs | `AC:EB:E6:F2:57:EC`, `AC:EB:E6:F2:83:08`, `AC:EB:E6:F6:53:88`, `AC:EB:E6:F2:91:B8` |
| Owning node | **all four claimed by N002** (`smart_plugs.node_id = 2`) |
| Protocol | Shelly Gen4 RPC over HTTP, **read-only** (`Shelly.GetDeviceInfo`, `Switch.GetStatus`, `WiFi.GetStatus`) |
| Discovery | every 5 min, **on the Pi only** |
| Poll | every 15 s |
| Identity key | MAC (not IP — DHCP moves them) |
| Buffer | separate SQLite file from `edge_buffer.db` |
| Assignment | only plug 3 (`AC:EB:E6:F6:53:88`) is assigned — building 8, deployment 5. The other three are **unassigned** |
| RSSI at audit | −39, −61, −31, −36 dBm |
| Temperature at audit | 51.6, 51.0, 39.7, 52.1 °C |

### B.7 What cannot be verified

| Item | Status |
|---|---|
| Bill of materials with part numbers | **Not recorded.** `docs/Hardware.md` states this explicitly. |
| Hardware photographs | **Absent.** Listed in `assets/screenshots/MANIFEST.md` with capture guidance; the images do not exist. |
| CT clamp make/model/ratio | **UNCERTAIN.** Only the rated currents (120/400/1000 A) are recorded. |
| N003 signal-conditioning circuit (burden resistors, bias network, voltage divider/transformer) | **UNCERTAIN.** No schematic in any file found. Only the resulting `VOLTAGE_SCALE` constants exist. |
| N001's current SSH-reachable state | **Not surveyed** — port 22 filtered on both known addresses on 2026-08-13. |
| Enclosure, PSU, mounting details | **DOCUMENTED only** (`docs/Hardware.md` block diagram), not verified. |

## 2.C Edge acquisition

### C.1 ⚠ The collector is not in the repository — VERIFIED

`docs/Collector.md` states it plainly:

> "**The base measurement collector — the ADS1256 sampling process itself — is
> not in this repository.** It is deployed and maintained directly on each Pi and
> has never been version-controlled centrally."

VERIFIED true, and broader than stated: **neither** collector is in the
repository — not `collector.py` (N001/N002, Shelly) nor `poller.py` (N003, ADS).
The repository contains only the smart-plug source, the integration shim, the
heartbeat agent, the hardening package and the networking package.

This is the top item on the project roadmap and the single largest provenance
gap. For the thesis it means: **the measurement software's source of truth is a
device, not a repository** — precisely the property the platform's own migration
discipline exists to avoid.

### C.2 Collector architecture (N001 / N002) — VERIFIED by source

`/opt/energy-node/app/collector.py`, SHA-256 `d9cc6138c8be60b273615d13`,
byte-identical on both Pi 5 nodes.

**Two deliberately independent loops:**

| Loop | Period | Property |
|---|---|---|
| Sample | 15 s | Reads the Shelly, writes the local buffer. **Never touches the network path to the backend.** |
| Sync | 60 s | Drains the buffer in batches of 100. **Never blocks sampling.** |

**The buffer is written before any upload is attempted.** That single ordering
choice is what makes a backend outage a delay rather than a data loss.

**Three integration boundaries, all VERIFIED in the source header:**

1. **Heartbeat** — imported from the hardening package at
   `/opt/energy-node/hardening/lib`, deliberately stdlib-only. *"If the package
   is absent the collector still runs; it simply cannot publish a heartbeat, and
   says so loudly rather than failing to start."*
2. **Networking** — `from energy_node_netstate import network_available`. The
   collector learns **one fact** and never learns *how* connectivity is achieved.
   Falls back to `return True` if the module is absent.
3. **Smart plugs** — `SmartPlugSource` started as daemon threads inside the same
   process, with its own separate SQLite file.

**Configuration** (`/opt/energy-node/config/node.env`, mode 600) — VERIFIED:

| Key | N002 value |
|---|---|
| `NODE_ID` | `N002` |
| `SHELLY_IP` / `SHELLY_ID` | `192.168.50.10` / `shellypro3em400-ecc9ffe730f4` |
| `DB_PATH` | `/opt/energy-node/database/edge_buffer.db` |
| `CENTRAL_API_URL` | `http://148.213.1.15:8010` |
| `POLL_INTERVAL` / `SYNC_INTERVAL` | `15` / `60` |
| `SHELLY_TIMEOUT` / `CENTRAL_TIMEOUT` | `5` / `10` |
| `SYNC_BATCH_SIZE` / `MAX_RETRIES` | `100` / `3` |
| `NODE_AUTH_TOKEN` | present (redacted) |

> ⚠ **Known defect, DOCUMENTED and VERIFIED in source:**
> `CONFIG = {"NODE_ID": os.getenv("NODE_ID", "N001"), …}` — a node with a missing
> or unreadable `node.env` **claims to be N001**. `docs/Energy-Node-Package.md`
> flags this: authentication contains the blast radius (a mismatched credential
> is refused `403 subject_mismatch`), but the default should be a hard failure.

### C.3 Measurement source abstraction

| Node | Abstraction | Status |
|---|---|---|
| N001 / N002 | **None.** The Shelly HTTP call is inline in `collector.py`. | CURRENT |
| N003 | A real `sources/` package selected by `SOURCE` env var (`ads` default, `shelly` alternative), with `drivers/` → `acquisition/` → `engine/` → `processing/` layering | CURRENT, EXPERIMENTAL |
| Hardening pkg | `sensors.discover()` with `SENSOR_KIND` pinning | CURRENT |

**The cleanest source abstraction in the project lives on the node that is least
supported.** N003's layering is the seed of a real driver abstraction; the
production nodes have none.

> ⚠ **Trap, DOCUMENTED:** `SENSOR_KIND` blank means auto-detect, and
> `sensors.discover()` prefers whichever source is *reachable*. When N002's
> Shelly died for two hours, discovery fell through to the smart plugs and
> reported the sensor **PASS** while the primary meter was dead. Always pin
> `SENSOR_KIND`.

### C.4 The measurement schema — the central contradiction

**Specified** (ADR-0007 / `collector-contract.md`) — the canonical model:

| Field | Meaning | Required |
|---|---|---|
| `power_kw` | Instantaneous active power at the sample instant | **yes** |
| `interval_energy_kwh` | Energy attributable to this sample's interval | **yes** |
| `interval_seconds` | Length of that interval | **yes** |
| `energy_source` | `measured` / `counter_delta` / `power_integral` | **yes** |
| `meter_energy_kwh` | Device's cumulative register — reconciliation only | no |

**Observed** — VERIFIED, live database:

```sql
SELECT energy_source, COUNT(*) FROM energy_readings GROUP BY 1;
-- (None, 290439)
SELECT COUNT(*) FROM energy_readings WHERE interval_energy_kwh IS NOT NULL;
-- 0
```

**⚠ CONTRADICTION C-03: `energy_source`, `interval_energy_kwh` and
`interval_seconds` are NULL on 100% of rows. No collector emits the canonical
contract.**

The backend implements the model (migration 012, `measurement_eras`); the edge
does not produce it. Energy is still integrated by the platform as
`power_kw × POLL_INTERVAL / 3600` — the **nominal** interval rather than the
elapsed time.

The `measurement_eras` table is what makes the legacy `energy_kwh` column
interpretable — VERIFIED, live:

| id | node | window | semantics | evidence recorded in the row |
|---|---|---|---|---|
| 1 | N001 | → 2026-07-03 15:32:39 | `cumulative_counter` | monotonic 17,283.82 → 26,259.24 kWh over 19 days; **0.0 % negative deltas** |
| 2 | N001 | 2026-07-25 00:01:01 → | `interval_energy` | `energy_kwh = power_kw × 15.000/3600` to zero relative error; **51.6 % negative deltas** |
| 3 | N003 | (all) | `absent` | `energy_kwh` NULL on all rows |
| 4 | N002 | (all) | `absent` | no readings yet |

This table is strong thesis material: it is the schema **recording what a column
meant at the time it was written**, rather than pretending the meaning never
changed.

### C.5 Local buffering, SQLite, WAL, sync, retry, offline — VERIFIED

| Property | Value | Evidence |
|---|---|---|
| Buffer file | `/opt/energy-node/database/edge_buffer.db` (N001/N002); `/home/theblackdie/udec-edge/edge_buffer.db` (N003) | node filesystem |
| Journal mode | WAL | `.db-wal` present, 4.2 MB on N003 |
| Table | `measurements` | direct query |
| `sync_status` | `0` = pending, `1` = sent, `2` = discarded | node inspection |
| Retention | rows pruned after **7 days** once confirmed sent | `docs/Collector.md` |
| Retry | every 60 s, indefinitely | `SYNC_INTERVAL` |
| Offline behaviour | accumulate locally; **nothing is dropped** | design |
| N002 buffer at audit | `last_buffered_readings = 23,517` | `monitor_node_heartbeat_latest` |
| N003 buffer at audit | 7,217 pending, 128,095 sent | direct query of `edge_buffer.db` |
| N003 buffer file size | 54.6 MB | `ls -la` |

> ⚠ **Live unbounded defect — sync head-of-line block.** DOCUMENTED and
> VERIFIED. `sync_pending()` takes the oldest row and `break`s on any rejection
> that is not the 400 "no active deployment" case. **One permanently-rejected row
> halts the entire queue forever.** Only the 400 case discards (`sync_status=2`);
> a 403 `registered` retains and blocks. This is why N002's buffer grows without
> bound (~5,700 rows/day) — and no alert fires, because a `registered` node is
> `is_monitored = 0`, which is correct.

### C.6 Heartbeat — VERIFIED

| Property | Value |
|---|---|
| Canonical endpoint | `POST /api/monitoring/heartbeat` (authenticated) |
| Legacy endpoint | `POST /api/edge/heartbeat` (unauthenticated, still mounted) |
| Cadence | 60 s (`HEARTBEAT_INTERVAL=60` in `hardening.conf`) — **note: `README.md` and `docs/Architecture.md` say 45 s** ⚠ C-04 |
| Payload | ~50 fields |
| Producer version | `2.0.0` (N001, N002); `udec-edge-1.1.0` (N003) |
| Live status at audit | all three nodes `online=1`, `missed_beats=0` |
| Legacy negotiation | `CANONICAL_MARKER = "last_sync"`; a `last_sync` key in the canonical response disables the node's own legacy publishing, cached in `/opt/energy-node/state/heartbeat_negotiation.json` |

Notable fields: `undervoltage`, `throttled`, `filesystem_readonly`,
`cpu_temperature_c`, `disk_percent`, buffer depth, `latency_ms`, `collector_pid`,
`sqlite_size_mb`, `uptime_seconds`, `ads_ok` (N003).

**`nodes.last_sync` is the single liveness source.** Every API caller that says
"online" reads it (`is_node_online`, `dashboard.online_nodes`, `metrics/live`,
`infra`, `deployments.node_online`).

Four properties are kept independent by design — DOCUMENTED and VERIFIED:

```
ALIVE  ≠  AUTHORIZED TO UPLOAD  ≠  MEASURING  ≠  DEPLOYED
```

A `registered` node may legitimately be `online=true, may_upload=false, not
measuring, not deployed` — which is exactly N002's current state.

### C.7 Deployment-aware behaviour — VERIFIED

The collector is **not** deployment-aware, deliberately. It uploads whatever it
buffered; the backend decides attribution. Historically ingestion *was* gated on
`Deployment.status`, and completing a campaign silently stopped data collection
(ADR-0001, ADR-0002). That coupling was removed.

The one residual behaviour: a 400 "no active deployment" response causes the
collector to log *"pre-deployment reading(s) discarded safely"* and set
`sync_status=2`. — DOCUMENTED; **this is not a bug**.

### C.8 Error handling and logging — VERIFIED

| Property | Value |
|---|---|
| Log destinations | stdout (→ journald) **and** `FileHandler("edge_node.log")` |
| Format | `%(asctime)s [%(levelname)s] %(message)s`, level INFO |
| ⚠ Defect | `edge_node.log` is opened at a **relative path** and is **never rotated** — 25.2 MB on N003 at audit, duplicating journald |
| Dead-sensor handling | a failed read logs and increments an error counter; the loop continues |
| ⚠ Defect | on N003 an *absent* ADC produces `0.0` with **no error at any layer** (§B.4 L-4) |

### C.9 systemd units — VERIFIED

**N001 / N002** (Energy Node Package v2.1):

| Unit | Responsibility | Type |
|---|---|---|
| `energy-node-collector` | **Sole** measurement, sync and heartbeat producer | long-running |
| `energy-node-netd` | Networking supervisor; `Type=notify`, watchdog 120 s, `StartLimitIntervalSec=0` | long-running |
| `energy-node-portal` | Maintenance portal (user `energy-net`, `CAP_NET_BIND_SERVICE` only) | long-running |
| `energy-node-console` | tty1 appliance console | long-running |
| `energy-node-powerlog` | UPS / power telemetry recorder | long-running |
| `energy-node-blackbox` | Crash / black-box recorder | oneshot at boot |
| `energy-node-recovery-arm` | Arms recovery | oneshot at boot |
| `energy-node-recovery` | **Recovery Manager — N002 only** | long-running |
| `energy-node-selfheal.timer` | 2-min check, **inert unless `RECOVERY_SELF_HEAL=1`** | timer |
| `energy-node-verify.timer` | Nightly package checksum verification | timer |
| `energy-node-heartbeat` | Legacy standalone agent — **absent on N001, disabled on N002** | retired |

Collector sandboxing (VERIFIED, and the cause of a false alarm — §5):
`ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`,
`ReadWritePaths=/opt/energy-node`.

> ⚠ **Defect, DOCUMENTED:** `energy-node-collector.service` sets
> `StartLimitBurst=20` / `StartLimitIntervalSec=300`, so **20 crashes in 5
> minutes leaves it `failed` permanently** with no reboot escalation. `netd`
> deliberately sets `StartLimitIntervalSec=0`; the collector does not. It also
> has no `sd_notify`/`WatchdogSec`, so a wedged-but-alive collector is invisible.

**N003** — VERIFIED from `systemctl cat udec-edge`:

```
Description=UdeC Edge Node — ADS1256 Collector
WorkingDirectory=/home/theblackdie/udec-edge
ExecStart=/usr/bin/python3 /home/theblackdie/udec-edge/poller.py
EnvironmentFile=/etc/energy-node/node-auth.env
Environment=SHELLY_IP=192.168.1.190
Environment=SHELLY_ID=N003
Environment=DB_PATH=/home/theblackdie/udec-edge/edge_buffer.db
Environment=POLL_INTERVAL=15
Environment=SYNC_INTERVAL=60
```

System Python, no venv, no sandboxing, configuration inline as `Environment=`.
`SOURCE` is **not** set, so `poller.py` defaults to `SOURCE="ads"` — the ADS path
is the active one, which is why its readings are zeros.

> ⚠ **Naming trap:** the unit description says "ADS1256 Collector" but the file
> also contains a full Shelly EM path. Backups `poller.py.ads_backup_*` dated
> 2026-07-24 show the conversion history. The description is unreliable.

### C.10 Relevant paths, classes and functions

| Concern | Location |
|---|---|
| Canonical collector | `/opt/energy-node/app/collector.py` (**node only**) |
| N003 collector | `/home/theblackdie/udec-edge/poller.py` (**node only**) |
| ADS1256 driver | `udec-edge/drivers/ads1256.py` → class `ADS1256` (**node only**) |
| Samplers | `udec-edge/acquisition/{voltage,current}_sampler.py` → `VoltageSampler`, `CurrentSampler` |
| Measurement engine | `udec-edge/engine/measurement.py` → `MeasurementEngine.measure_phase(phase, samples=2500)` |
| Signal processing | `udec-edge/processing/electrical.py`, `processing/rms.py` |
| Source selector | `udec-edge/sources/ads.py` → `fetch_ads_status()` |
| Smart-plug source | `edge/smart_plug_source.py` → class `SmartPlugSource` (**in repo**) |
| Collector shim | `edge/integrate_collector.py` (**in repo**) |
| Heartbeat agent | `monitoring/edge/node_heartbeat.py` (**in repo**) |
| Hardening lib | `edge/node/hardening/lib/{telemetry,heartbeat,sysinfo,ups,sensors,doctor,selftest,blackbox,powerlog,enconfig,tristate,i2cbus,version}.py` |
| Recovery manager | `edge/node/hardening/lib/recovery/{pipeline,daemon,probes,ledger,bootstate,selfheal,watchdog,rtc_wake,gpio_wake,ups_wake,relay,external_watchdog,explain}.py` |
| Networking | `edge/node/net/` |

## 2.D Networking

### D.1 The property that makes this deployable — VERIFIED

**Every connection is initiated outbound from the node.** No inbound port is
forwarded to any Raspberry Pi for the platform to work.

This is why smart-plug discovery runs **on the Pi**: a central scanner would need
inbound reach into every site and would forfeit exactly this property.

| Direction | Purpose |
|---|---|
| Node → server :8010 | Measurement batches (60 s), heartbeats (60 s) |
| Node → plugs on LAN | Shelly Gen4 RPC polling |
| Node → Shelly Pro 3EM on `192.168.50.10` | Meter polling (15 s) |
| **Inbound to node** | **None required by the platform** |

### D.2 Normal Wi-Fi operation and interface roles — VERIFIED

| Interface | Role |
|---|---|
| `eth0` | **Private Shelly sensor segment** `192.168.50.0/24` (meter `.10`, node `.2`). Carries **no default route.** |
| `wlan0` | Campus Wi-Fi uplink, **campus DHCP public address** |

`interfaces.ethernet_is_uplink` resolves the ambiguity — DOCUMENTED:

| Mode | Behaviour |
|---|---|
| `auto` *(default)* | Ethernet becomes uplink **only when it carries a default route**; otherwise recognised as the sensor segment and Wi-Fi keeps the uplink role |
| `always` | Ethernet always wins when the link is up |
| `never` | Ethernet is never an uplink |

**"Online" means it can reach its default gateway or its backend.** Internet
access is reported but not required — a campus LAN behind a filtering proxy is
still a usable network.

### D.3 The networking subsystem `energy-node-netd` — CURRENT

Architecture (DOCUMENTED in `edge/node/net/README.md`, package VERIFIED present
and running on N001/N002/N003):

- **`netd` is the only component that mutates network state.** Portal and console
  are unprivileged pure clients over a control socket
  `/run/energy-node/netd.sock` (0660 `root:energy-net`).
- **Strict downward layering**, with a **pure decision layer** (`evaluator`,
  `statemachine`) that performs no I/O — time arrives as a parameter, so every
  transition is unit-testable without a radio.
- **One published fact** at `/run/energy-node/network-state.json`.
- **Fail-open:** if the state file is missing or stale, `network_available()`
  returns `True`. *"A collector that stopped trying because the monitor died
  would turn a networking fault into a data-loss fault."*

**State machine:**

```
BOOT ─────────────────────────────▶ ONLINE
  │ boot_grace elapsed                ▲ ▲
  ▼                                   │ │
CONNECTING ───────────────────────────┘ │
  │ connect_grace elapsed                │
  ▼                                      │
OFFLINE_BUFFERING ─────────────────────▶─┤ (uplink restored)
  │ offline_before_ap elapsed             │
  ▼                                       │
MAINTENANCE_AP ──▶ RECOVERING ───────────┘
```

No transition requires a reboot; every state has a path back to `ONLINE`.

**Timings** (defaults, DOCUMENTED):

| Key | Default (s) | Meaning |
|---|---|---|
| `boot_grace` | 45 | let NetworkManager settle |
| `connect_grace` | 60 | how long `CONNECTING` may last |
| `offline_before_ap` | 180 | continuous offline before raising the AP |
| `stable_before_ap_down` | 60 | uplink stability before AP teardown |
| `monitor_interval` | 10 | evaluation cadence |
| `ap_min_uptime` | 120 | AP stays up at least this long |
| `retry_backoff_initial` / `_max` | 15 / 300 | reconnect backoff bounds |

### D.4 Access-point fallback — CURRENT

| Property | Value |
|---|---|
| Raised on | first boot with no Wi-Fi, invalid credentials, no saved network in range, or offline longer than `offline_before_ap` (180 s) |
| SSID | `EnergyNode-N001` / `-N002` / `-N003`, unique passphrase per node |
| Portal | `http://192.168.66.1` |
| Mechanism | NetworkManager `ap` mode with `ipv4.method=shared` (own DHCP/DNS via `dnsmasq-base`) — **no hostapd or dnsmasq config to maintain** |
| Profile | `autoconnect=no`, priority `-999` — it comes up because the supervisor decided so, never because NetworkManager picked it |
| Teardown | automatic once an uplink is stable for `stable_before_ap_down`, unless pinned by an operator |
| Self-heal | after `ap_min_uptime`, if no operator is associated, the AP drops briefly to look for known networks |
| Subnet choice | `192.168.66.0/24` — **`192.168.50.0/24` is deliberately avoided** because it is the Shelly sensor segment |

**Not a captive portal:** `/generate_204` is answered honestly rather than
hijacked. **Trust boundary:** status pages readable from anywhere the portal is
reachable; *mutating* actions restricted to `portal.trusted_networks`. The portal
is unauthenticated **by design** — a technician at a dead node must not need a
password — so the boundary is *where you connect from*.

### D.5 NetworkManager integration and local management — CURRENT

All state changes go through `nmcli`; NetworkManager itself is untouched and
integrated rather than replaced. Three operator interfaces:

1. **Web portal** — server-rendered HTML, one inline stylesheet, ~30 lines of
   vanilla JS. No framework, no build step, no external asset.
2. **Appliance console on tty1** (urwid) — replaces the login prompt; login
   prompts remain on Alt+F2…F6.
3. **`netdctl` CLI** — `status`, `scan`, `saved`, `connect`, `forget`,
   `priority`, `ap start|stop`, `diagnostics`, `logs`, `restart networking`,
   `factory-network-reset`.

**Factory network reset** is deliberately narrow: deletes **Wi-Fi client profiles
only**. Preserved: the SQLite buffer and every measurement, all logs, node
identity, subsystem configuration, Ethernet profiles, and the AP profile.
Deleted profiles are exported to
`/var/lib/energy-node-net/network-reset-backups/<timestamp>/` first.

### D.6 Tailscale — ⚠ important nuance

| Node | Tailscale address |
|---|---|
| N001 | `100.125.1.37` |
| N002 | `100.98.67.31` |
| N003 | `100.79.227.108` |

**Tailscale is installed on the nodes but NOT on the application server** —
VERIFIED. `100.64.0.0/10` goes out the server's default gateway and dies.
Installing it needs root. All server→node work uses **public NAT addresses**.

Deployment of *networking* changes is done over Tailscale from a machine that has
it, because Tailscale stays reachable while the underlying Wi-Fi changes.

### D.7 Reaching a node — VERIFIED 2026-08-13

| Node | Public NAT address (today) | SSH :22 | Note |
|---|---|---|---|
| N001 | `148.213.168.238` | **filtered** | Previously `148.213.2.186` (2026-08-10) and `148.213.168.238` (2026-07-26). Addresses move. |
| N002 | `148.213.2.245` | open | passwordless `sudo` |
| N003 | `148.213.2.153` | open | `sudo` needs a password; **fail2bans on one wrong password** |

**These addresses are campus DHCP public addresses on `wlan0`, not static.** When
a node is unreachable, get its current address from the platform:

```sql
SELECT node_code, source_ip, received_at FROM monitor_node_heartbeats
ORDER BY id DESC LIMIT 5;
```

Neither `nodes.ip_address` (stale Tailscale `100.64.1.x`) nor the heartbeat's own
`ip_address` field (`192.168.50.2` — the sensor segment, identical on every node)
can reach anything.

### D.8 Failure and recovery behaviour — DOCUMENTED

| Failure | Effect | Recovery |
|---|---|---|
| Site loses internet | Nodes buffer locally, up to 7 days | Automatic; buffer replays |
| Server unreachable | Same; sync retries every 60 s | Automatic |
| Node loses LAN | No plug polling; panel measurement continues | Automatic |
| Server down | No ingestion, no dashboards, **no alerting** | Restart; nodes replay |
| Telegram unreachable | Alerts recorded; delivery retried from the durable outbox | Automatic — nothing discarded |
| Node offline > 180 s | Maintenance AP raised | Operator joins AP |

**The pattern throughout: network failures cause delay, not loss.** The one
exception is a site outage longer than seven days.

### D.9 Current vs planned

| Capability | Status |
|---|---|
| Outbound-only operation | **CURRENT** |
| `netd` supervisor, portal, console, `netdctl` | **CURRENT**, on all three nodes |
| Maintenance AP fallback | **CURRENT** |
| Health-driven Wi-Fi selection + two-tier whitelist | **CURRENT** (commit `4a72fb0`, 2026-08-11) |
| Recovery Manager (service remedy → reboot → SAFE MODE) | **CURRENT on N002 only.** N001 untouched. |
| TLS on the API | **PLANNED** — `docs/Networking.md` "if you deploy this elsewhere" |
| Tailscale on the application server | **PLANNED** (needs root) |
| Retirement of `/api/edge/heartbeat` | **PLANNED** — audit item D3, blocked on whole-fleet collector convergence |

> ⚠ **N003 runs two Wi-Fi managers at once** — DOCUMENTED: `energy-node-netd`
> *and* the legacy `energy-node-wifi-fallback` (root,
> `/usr/local/lib/energy-node/wifi_fallback.py`). Both can mutate NetworkManager
> and raise an AP; netd's design requires exactly one mutator. Its NM profiles
> also all sit at autoconnect-priority 0 (N001 uses 30/60), with two duplicate
> profiles for the same SSID.

---

## 2.E Backend

### E.1 Framework and process model — VERIFIED

| Property | Value | Evidence |
|---|---|---|
| Framework | **FastAPI** (`University Energy Intelligence Platform API`, OpenAPI version `0.1.0`) | live `/openapi.json` |
| Server | `gunicorn app.main:app -k uvicorn.workers.UvicornWorker **-w 1** -b 0.0.0.0:8010 --timeout 120` | `ps aux` |
| Python | 3.12 (`backend/venv`) | venv path |
| Unit | `energy-platform-backend.service`, runs as `manager` | `systemctl` |
| Reload | `kill -HUP $(systemctl show -p MainPID --value energy-platform-backend.service)` — graceful, no root | DOCUMENTED + prior verification |
| Routes | **85 paths / 90 operations** | live OpenAPI schema |
| ORM | SQLAlchemy | `app/db/models.py` |
| CORS | `allow_origins=["*"], allow_credentials=False` | `app/main.py` |

**`-w 1` is a database constraint expressed in the process model**, not a
resource decision. SQLite has one writer.

### E.2 Architecture and layering — VERIFIED

```
backend/
├── app/
│   ├── main.py            assembly, CORS, router registration
│   ├── db/                models, session, seeding, lifecycle, scope, node_auth, commissioning
│   ├── routers/           20 routers — the HTTP surface
│   ├── services/          domain logic — no HTTP, no ORM session management
│   ├── monitoring/        self-contained monitoring subsystem
│   └── static/            institutional assets
├── migrations/            hand-rolled runner, 14 versions applied
├── tests/                 6 suites, plain-python assertions
└── docs/                  7 ADRs + the definitive backend reference
```

Two rules, DOCUMENTED and enforced by convention:

- **A router never writes SQL directly.**
- **A service never knows it is being called over HTTP.**

This is why one cost engine backs the dashboard, the PDF report and the
monitoring rules without three implementations of the tariff arithmetic.

Two consequences of `app/main.py`, DOCUMENTED:

1. **The working directory matters.** `.env`, `runtime_platform_settings.json`
   and `energy_platform.db` all resolve relative to `backend/`. A wrong working
   directory fails **silently** — the platform starts with no credentials and no
   error.
2. **Importing `app.monitoring` registers every rule** and makes the `monitor_*`
   tables known to SQLAlchemy — but the API process **never creates them**. Table
   creation belongs to the scheduler, so the API can never alter the monitoring
   schema as a side effect of a reload.

### E.3 API structure — VERIFIED (live OpenAPI, 2026-08-13)

| Prefix | Ops | Responsibility |
|---|---:|---|
| `/api/monitoring` | 14 | Monitoring subsystem API, canonical heartbeat intake |
| `/api/reports` | 13 | PDF / XLSX / CSV generation |
| `/api/deployments` | 9 | Installation-campaign lifecycle |
| `/api/org` | 8 | Delegations, campuses, organizational units |
| `/api/smart-plugs` | 7 | Shelly fleet |
| `/api/nodes` | 6 | Node inventory, commissioning, health summary |
| `/api/metrics` | 6 | Live and historical electrical metrics |
| `/api/settings` | 3 | Runtime platform settings |
| `/api/ai-center`, `/api/buildings`, `/api/cost`, `/api/data-explorer`, `/api/readings` | 2 each | Analytics, inventory, cost, ad-hoc query, legacy ingest |
| `/api/ai`, `/api/alerts`, `/api/anomalies`, `/api/dashboard`, `/api/edge`, `/api/infra`, `/api/mining`, `/api/v1` | 1 each | — |
| `/health` | 1 | Liveness |

`docs/API.md` is **generated from the running OpenAPI schema and verified in
CI** — `scripts/check_api_docs.py` fails the build when a route exists that the
document does not describe, or vice versa.

### E.4 Ingestion — the one path that must never be wrong

**Three ingestion endpoints — VERIFIED live:**

| Endpoint | Purpose | Auth |
|---|---|---|
| `POST /api/v1/measurements/batch` | Batch measurement ingest (N003, and the canonical path) | **enforced** |
| `POST /api/readings` | Legacy single/batch reading ingest (N001, N002) | **enforced** |
| `POST /api/monitoring/heartbeat` | Canonical heartbeat (~50 fields) | **enforced** |
| `POST /api/edge/heartbeat` | Legacy heartbeat (3 fields) | **unauthenticated, still mounted** |

**Four questions, asked in order, never conflated** — VERIFIED in
`app/services/ingest_gate.py`:

```
payload ─▶ authenticate ─▶ authorize ─▶ classify ─▶ attribute ─▶ store
           bearer token    commission    node's      resolver     always
           vs              state         declared     over        (never
           auth_token_hash may_upload    context      captured_at  reject)
```

Once authenticated and authorized, **data is always stored and never rejected.**
A reading that cannot be attributed is stored unattributed. *"Rejection destroys
evidence; classification preserves it."*

### E.5 ⚠ CONTRADICTION C-02 — authentication is implemented and enforced

**Claimed** — `README.md` "Known limitations", `docs/Security.md` "Known gaps
#1", `docs/Architecture.md` §6, `CHANGELOG.md` v1.2.0 "Known gaps", ADR-0002
"Consequences":

> "Ingestion endpoints are unauthenticated. `device_id` is self-asserted. A
> forged heartbeat can suppress a real outage alert. **Not yet implemented.**"

**Observed** — VERIFIED 2026-08-13:

1. `backend/monitoring_config.json` (modified 2026-08-13 14:04):
   ```json
   {"node_auth": {"mode": "enforce", "exempt_nodes": []}}
   ```
2. `app/db/node_auth.py` exists — SHA-256 token hashing, `secrets.token_urlsafe(32)`,
   constant-time comparison via `hmac`, `issue_token()`, `extract_token()` accepting
   `Authorization: Bearer` **and** `X-Node-Token`.
3. `app/services/ingest_gate.py` exists — `authenticate_node()` / `authorize()` /
   `classify()` / `admit()`.
4. Migration **013 `node_identity_enforcement`** applied 2026-08-06 13:46:49.
5. `nodes.auth_token_hash` and `auth_token_issued_at` are **populated for all
   three nodes**.
6. Table `node_identity_violations` holds **12,278 rows** of refusals.
7. `POST /api/readings` from N002 returns 403 in real time (violations logged
   seconds before the audit).

**Conclusion: the documentation is stale, not the system.** The single most
prominent "known limitation" in the repository was closed on 2026-08-06/07 by
commit `1db4fe4 feat(security): authenticate node identity and gate every ingest
path`. **Any thesis text drawn from the README on this point would be wrong.**

**Live evidence of enforcement** — VERIFIED, `node_identity_violations`:

| claimed node | violation | endpoint | rows | first | last |
|---|---|---|---:|---|---|
| N003 | `unauthenticated` | `/api/v1/measurements/batch` | 5,985 | 2026-08-06 14:19 | 2026-08-13 13:58 |
| N002 | `not_authorized` | `/api/readings` | 4,822 | 2026-08-07 13:54 | 2026-08-13 14:53 |
| N002 | `unauthenticated` | `/api/readings` | 1,413 | 2026-08-06 14:19 | 2026-08-07 13:53 |
| N003 | `not_authorized` | `/api/v1/measurements/batch` | 50 | 2026-08-13 14:03 | 2026-08-13 14:53 |
| N002 | `unauthenticated` | `/api/monitoring/heartbeat` | 5 | 2026-08-06 13:52 | 2026-08-06 13:55 |
| N001 | `unauthenticated` | `/api/readings` | 2 | 2026-08-06 14:20 | 2026-08-06 14:21 |
| N001 | `subject_mismatch` | `/api/monitoring/heartbeat` | 1 | 2026-08-06 13:57 | — |
| N001 | `unknown_credential` | `/api/monitoring/heartbeat` | 1 | 2026-08-06 13:57 | — |

This table is **strong empirical evidence** for the thesis: it shows the auth
transition happening in production, with N003 moving from `unauthenticated` (401)
to `not_authorized` (403) on 2026-08-13 when its credential was installed.

**One enforcement policy, asked never re-derived** — DOCUMENTED design rule:
`node_auth.enforcement_applies_to(node_code, config)` is the *only* place
`node_auth.mode` and `node_auth.exempt_nodes` are combined. The bug it replaces:
`exempt_nodes: ["N003"]` was honoured only by `/api/monitoring/heartbeat`; both
ingest paths passed `mode` through as a bare boolean and dropped the exemption.
Regression tests in `tests/test_monitoring.py` §3g compare routes **against each
other**, so a new route that re-derives the policy fails regardless of which way
it diverges.

### E.6 Services — VERIFIED (`backend/app/services/`)

| Service | LOC | What it owns |
|---|---:|---|
| `ml_engine.py` | 496 | RandomForest forecasting, IsolationForest anomalies, KMeans building profiles, anomaly grouping |
| `attribution.py` | 364 | **Pure, stateless, deterministic** resolver: reading → deployment by `captured_at` |
| `anomaly_engine.py` | 334 | Threshold-rule anomalies (power factor, over-current, night consumption, demand spike) |
| `ingest_gate.py` | 259 | The single gate: authenticate → authorize → classify → attribute |
| `cost_engine.py` | 174 | CFE **GDMTH** tariff arithmetic — the only place a rate is applied |
| `model_confidence.py` | 69 | Backtesting-based forecast confidence (MAPE) |
| `cfe_scraper.py` | — | Scrapes published CFE tariffs (imports `playwright` at module load) |
| `deployment_ops.py` / `deployment_scope.py` | — | Lifecycle transitions; analytics scope filter |
| `energy_aggregate.py` / `energy_delta.py` | — | Rollups, local-date bucketing, interval-energy reconciliation |
| `platform_settings.py` | — | Layered runtime settings from `runtime_platform_settings.json` |
| `gemini_engine.py` | — | Optional LLM narration, fully disabled by `LLM_ENABLED=0` |

> **`anomaly_engine` and `app/monitoring/` are not the same thing.**
> `anomaly_engine` powers the **Anomalies screen** and reads UI display
> thresholds. `app/monitoring/` decides **whether to wake a human** and derives
> its thresholds from physical ratings. Conflating them was the direct cause of
> the alert-noise incident.

### E.7 Testing — VERIFIED by execution, 2026-08-13

```bash
make test              # 4 hermetic suites — no database needed
make test-integration  # 2 suites that read the live production database
```

| Suite | Checks (measured today) | Hermetic | Covers |
|---|---:|:--:|---|
| `test_monitoring` | **404 passed / 0 failed** | ✅ | Rules, severity, thresholds, alert-noise regression guards, auth-policy parity (§3g) |
| `test_smart_plugs` | **53 passed / 0 failed** | ✅ | Shelly ingest, ownership, assignment, fleet state |
| `test_collector` | **49 passed / 0 failed** | ✅ | The measurement contract and `energy_source` handling |
| `test_synthetic_deployment` | **18 passed / 0 failed** | ✅ | The entire pipeline against a synthetic campaign with a real overload |
| `test_energy_aggregate` | — | ❌ reads production | Rollup and interval-energy arithmetic |
| `test_deployment_lifecycle` | — | ❌ copies production | Status transitions, exclusivity, attribution windows |

**Total hermetic: 524 checks, all passing.** ⚠ `README.md` and `docs/Backend.md`
say **449** (329 for `test_monitoring`) — stale by 75 checks. C-05.

Written as **plain-python assertions with no test framework**, because *pytest is
not installed on the deployment host* and the tests must be runnable there.

Sections **19–25** of `test_monitoring`, and all of `test_synthetic_deployment`,
are **sensitivity checks**: they assert real faults still fire (missing phase,
overload, power loss, PF collapse) while known noise stays silent.

## 2.F Database

### F.1 Engine and scale — VERIFIED 2026-08-13

| Property | Value |
|---|---|
| Engine | **SQLite, WAL mode** |
| Path | `backend/energy_platform.db` |
| Size | **311.2 MB** + 4.4 MB WAL |
| Tables | **34** |
| `energy_readings` | **290,439 rows**, 2026-05-13 → live |
| Migrations applied | **14** |

⚠ C-06: `README.md` and `docs/Database.md` state 255,379 readings / 33 tables /
12 migrations, read on 2026-08-04. Now 290,439 / 34 / 14.

**Why SQLite** — DOCUMENTED, a considered choice:

| Fits | Costs |
|---|---|
| One writer (ingest), many readers (dashboards, reports, monitoring) — the WAL sweet spot | Concurrent writes serialise |
| ~290k rows, ~311 MB — inside SQLite's comfortable range | Scaling past one application server means a real migration |
| No second process to operate, monitor, back up or fail independently | No network access; the DB is local to the API host |
| Backups are a single file | **`cp` produces a silently corrupt backup** |

> **`cp`, `rsync`, `tar` and filesystem snapshots all produce a torn backup that
> looks valid and fails on restore.** Backups must use SQLite's online backup
> API: `sqlite3 energy_platform.db ".backup out.db"`.

### F.2 Conceptual structure

Five concerns, five owners, **no owner reads another's state to answer its own
question** (ADR-0001):

| Question | Owner | Source of truth |
|---|---|---|
| Does this node exist? Is it authorised to upload? | `Node` | `nodes`, `node_commission_states` |
| Is it healthy right now? | Monitoring (derived, never stored on `Node`) | `monitor_node_heartbeat_latest` |
| Is it operationally installed somewhere? | `Deployment` | `deployments`, `deployment_statuses` |
| Which building does this measurement belong to? | `EnergyReading` | `deployment_id`, `building_id`, resolved by `captured_at` |
| What does this number actually mean? | Semantics | `measurement_contexts`, `measurement_eras` |

**Organisation hierarchy** — VERIFIED:

```
delegations (5) ──▶ campuses (10) ──▶ organizational_units (72)
                         └─────────▶ buildings (3) ──▶ electrical_panels (3)
                                            └──────────▶ deployments (4)
```

**Measurement chain:**

```
nodes (3) ──▶ deployments (4) ──▶ energy_readings (290,439)
                    │                     │
              buildings (3)         measurement_contexts (7)
              electrical_panels (3) measurement_eras (4)
```

**Sub-metering chain (deliberately separate):**

```
smart_plugs (4) ──▶ smart_plug_readings (152,493)
```

**Table groups — VERIFIED live row counts:**

| Group | Table | Rows |
|---|---|---:|
| **Measurement** | `energy_readings` | 290,439 |
| | `measurement_contexts` | 7 |
| | `measurement_eras` | 4 |
| | `energy_semantics` | 4 |
| **Sub-metering** | `smart_plug_readings` | 152,493 |
| | `smart_plugs` | 4 |
| **Monitoring** | `monitor_server_heartbeats` | 25,764 |
| | `monitor_node_heartbeats` | 19,941 |
| | `monitor_alert_events` | 3,713 |
| | `monitor_notification_outbox` | 2,196 |
| | `monitor_alerts` | 675 |
| | `monitor_node_heartbeat_latest` | 3 |
| **Security** | `node_identity_violations` | 12,278 |
| **Identity & authorisation** | `node_commission_transitions` | 8 |
| | `node_commission_states` | 4 |
| | `nodes` | 3 |
| | `node_commission_events` | 2 |
| **Lifecycle** | `deployment_status_transitions` | 6 |
| | `deployment_statuses` | 5 |
| | `deployments` | 4 |
| **Organisation** | `organizational_units` | 72 |
| | `campuses` | 10 |
| | `delegations` | 5 |
| | `buildings` | 3 |
| | `electrical_panels` | 3 |
| **Tariff** | `tariff_periods` | 7 |
| **Migration artefacts** | `energy_readings_pre_m4` | 225,594 |
| | `m5_attribution_backup` | 123,696 |
| | `schema_migrations` | 14 |
| | `sqlite_stat1` | 12 |
| | `nodes_pre_m7` / `deployments_pre_m3` / `m5_node_context_backup` / `migration_markers` | 3 / 2 / 3 / 2 |

**Note:** `energy_readings_pre_m4` (225,594 rows) is the **pre-rebuild rollback
table** retained under the "rename, never drop" principle. It is not live data.

### F.3 Reference tables — VERIFIED, full contents

**`measurement_contexts`** — semantics are *columns*, so a new context is one
`INSERT`:

| code | `counts_in_analytics` | `may_attribute` | description |
|---|:--:|:--:|---|
| `production` | **1** | **1** | Real load on a real panel during a real campaign |
| `commissioning` | 0 | **1** | On-site verification before a campaign goes active |
| `infrastructure_validation` | 0 | 0 | Node powered and collecting for platform validation, **with no operational deployment**. Real measurements, retained for diagnostics, never attributed, never counted |
| `bench` | 0 | 0 | Hardware bring-up on a desk; the instrument is under test, not a load |
| `laboratory` | 0 | 0 | Controlled acquisition on a real load, outside any campaign |
| `calibration` | 0 | 0 | Measured against a reference instrument or a known source |
| `simulation` | 0 | 0 | Synthetic or replayed data; no physical sensor involved |

`infrastructure_validation` was added by **migration 014** (2026-08-06) — it is
the newest and most operationally significant context.

**`deployment_statuses`:**

| code | `allows_attribution` | `is_operational` | `is_terminal` | `is_exclusive` |
|---|:--:|:--:|:--:|:--:|
| `planned` | 0 | 0 | 0 | 0 |
| `installing` | 0 | **1** | 0 | **1** |
| `active` | **1** | **1** | 0 | **1** |
| `completed` | **1** | 0 | **1** | 0 |
| `cancelled` | 0 | 0 | **1** | 0 |

**`node_commission_states`:**

| code | `may_upload` | `is_monitored` | `is_terminal` | meaning |
|---|:--:|:--:|:--:|---|
| `registered` | 0 | 0 | 0 | Known but not verified in the field. Uploads refused; **silence is expected** |
| `commissioned` | **1** | **1** | 0 | Verified and in service. The only uploading state. **Silence is an alarm** |
| `suspended` | 0 | **1** | 0 | Uploads deliberately revoked (fault, security, theft). Still installed, still monitored |
| `decommissioned` | 0 | 0 | **1** | Retired. History retained, silence expected |

`is_monitored` is what reconnected alerting to reality — **no deployment
transition can reach it.**

**`tariff_periods` — CFE GDMTH, seven rows, VERIFIED:**

| period | hours | MXN/kWh |
|---|---|---:|
| base | 00–06 | 1.0375 |
| intermediate | 06–09 | 1.8463 |
| **peak** | **09–13** | **2.0789** |
| intermediate | 13–16 | 1.8463 |
| **peak** | **16–18** | **2.0789** |
| intermediate | 18–22 | 1.8463 |
| base | 22–24 | 1.0375 |

Plus `fixedCharge: 252.5` MXN in `runtime_platform_settings.json`. Source
recorded as *"JUN-26 · Centro Occidente"*, Colima, division CENTRO OCCIDENTE,
scraped from the CFE GDMTH page. Local timezone `America/Mexico_City`.

### F.4 `energy_readings` — the central table

**Columns (24) — VERIFIED:**

```
id · node_id · deployment_id · building_id · electrical_panel_id · context
timestamp · ingested_at
voltage · current · power_kw · energy_kwh · power_factor · frequency_hz
phase_a_voltage · phase_b_voltage · phase_c_voltage
phase_a_current · phase_b_current · phase_c_current
interval_energy_kwh · interval_seconds · meter_energy_kwh · energy_source
```

- `timestamp` = when the measurement was **taken** (`captured_at`).
- `ingested_at` = when the server **received** it.
  They are separate because a replayed buffer delivers week-old measurements
  seconds ago — **and attribution depends on the former**.
- The last four columns are the ADR-0007 canonical fields: **all NULL** (§C.4).
- `building_id` and `deployment_id` are **`NOT NULL`** in the pre-M4 design;
  making them nullable required the full 12-step rebuild that migration 004 is.

**Indexing:** hot paths are time-range scans per node and per deployment;
indexes cover `(node_id, timestamp)` and `(deployment_id, timestamp)`.
`sqlite_stat1` is populated (12 rows) — `ANALYZE` has been run.

### F.5 Migrations — VERIFIED, all 14 applied, none rolled back

| # | Name | Applied |
|---:|---|---|
| 001 | `placeholder_buildings` | 2026-07-26 21:54 |
| 002 | `node_identity_authorization` | 2026-07-26 22:00 |
| 003 | `deployment_lifecycle` | 2026-07-26 22:06 |
| 004 | `rebuild_energy_readings` *(Python, 12 steps, 225k rows)* | 2026-07-26 22:30 |
| 005 | `backfill_measurement_context` | 2026-07-26 22:40 |
| 006 | `analytics_scope_and_contamination_window` | 2026-07-26 22:56 |
| 007 | `node_commissioning_lookup` | 2026-07-26 23:03 |
| 008 | `physical_ratings_and_node_transitions` | 2026-07-29 14:43 |
| 009 | `deployment_status_exclusivity` | 2026-07-30 22:17 |
| 010 | `deployment_operational_timestamps` *(Python)* | 2026-07-30 22:22 |
| 011 | `deployment_integrity_protections` | 2026-07-30 22:33 |
| 012 | `canonical_measurement_model` | 2026-07-31 19:11 |
| 013 | `node_identity_enforcement` | 2026-08-06 13:46 |
| 014 | `infrastructure_validation_context` | 2026-08-06 14:17 |

Every row carries a `checksum` and a `backup_path` — **each migration's own
restore point**, e.g.
`backups/db/energy_platform-20260726_222956-pre-004-up.db`. Milestone backups
(`pre-NNN-up`) are never deleted by retention.

**Seven of the fourteen were applied on a single evening (2026-07-26)** — the
architecture redesign.

**The migration engine** (`migrations/runner.py`) performs, in order:
online backup → invariant snapshot → apply in one transaction → re-check
invariants → record, **or roll back automatically**.

**Sixteen invariants** (`migrations/invariants.py`) — the full catalogue:

| # | Guarantee |
|---|---|
| 01 | No reading that existed before a step is missing after it |
| 02 | **No measured value ever changes — never waivable** |
| 03 | Attribution changes only in a step that declares it |
| 04 | Every reading names a node that exists |
| 05 | Node codes are unique |
| 06 | Deployment status is a legal value |
| 07 | Context is a legal value |
| 08 | A reading with a deployment also names a building |
| 09 | Non-production data is never attributed |
| 10 | Attribution never points at a deleted row |
| 11 | No reading dated more than a day ahead |
| 12 | Reference tables never shrink unexpectedly |
| 13 | The rebuild rollback table survives until cleanup |
| 14 | Every foreign key resolves (`PRAGMA foreign_key_check`) |
| 15 | `captured_at` never changes without an explicit waiver |
| 16 | `(id, node_id, captured_at)` identical: no duplicate, reordered or reassigned id |

Waivers: `allow_attribution_change`, `allow_timestamp_change`,
`allow_node_change`, `allow_building_change`, `allow_deployment_change`. An
**unrecognised waiver aborts the run before the backup is taken.**

**Every reading-level invariant is bounded by `id <= max_reading_id` captured at
snapshot time** — because the Pis write every 15 seconds while migrations run, a
naive "row count unchanged" check would fail for an innocent reason and pass for
a guilty one.

**Two SQLite specifics that cost real debugging** — DOCUMENTED, both hard-won:

1. `ALTER TABLE RENAME` **rewrites foreign keys in *other* tables** to follow the
   renamed table. Set `PRAGMA legacy_alter_table=ON` during a rebuild, or the
   rollback table silently becomes the live parent.
2. **A renamed table keeps its indexes under their original names.** Drop them
   before creating the new ones or the `CREATE INDEX` collides — mid-rebuild of a
   225k-row table.

**Migration philosophy — seven principles** (ARCHITECTURE.md §12): rollback ships
with the change · prove the rollback · prove the restore · rename, never drop ·
additive first · semantics as data · invariants catch what review cannot.

## 2.G Frontend

### G.1 Stack and deployment — VERIFIED

| Property | Value |
|---|---|
| Framework | **React 19** + TypeScript + Vite |
| Charts | Recharts |
| HTTP | axios, single client at `src/services/api.ts` (233 lines) |
| State | **local React state + polling.** No Redux, no React Query, no WebSocket |
| Polling | 3 s (live monitoring), 30 s (dashboards) |
| Styling | **No CSS framework.** Inline `style={{}}` objects + token objects |
| Production | `frontend/` → `frontend/dist`, served by `static_server.py` on **:5174** |
| Staging | `frontend-src/` → `frontend-src/dist`, `static_server_test.py` on **:5175** (git-ignored) |
| Deploy | `npm run build` **is** the release — `Cache-Control: no-store`, no restart |
| Language | **Interface Spanish; code, comments and docs English.** No i18n framework |
| `src/App.tsx` | **2,532 lines** — most screens live here |

Styling token sources: `src/styles/theme.ts`, `src/components/smartplugs/styles.ts`,
the `T` object in `src/pages/PageSettings.jsx`, and `src/index.css` (the CSS
custom properties the token objects mirror).

**Dead code — VERIFIED unreachable from `main.tsx`:** `src/app.css`,
`src/components/common.tsx`, `src/components/ui/*` (`Badge.tsx`, `Card.tsx`,
`MetricCard.tsx`), `src/pages/CostAnalytics.tsx`, and the empty
`src/components/charts/`.

**The only fully extracted feature module** is `src/components/smartplugs/`
(`SmartPlugCard`, `SmartPlugAssignDialog`, `SmartPlugFilters`,
`SmartPlugStatusBadge`, `SmartPlugSummary`, `SmartPlugDashboardWidget`,
`useSmartPlugs`, `styles.ts`, `types.ts`) — the model for the refactor the
frontend needs.

### G.2 The 13 modules — VERIFIED from `src/App.tsx` navigation array

| # | `id` | Label (Spanish, as shipped) | What it currently does |
|---:|---|---|---|
| 1 | `dashboard` | **Dashboard Ejecutivo** | Executive KPIs: live cost against the GDMTH tariff, tariff-period breakdown, weekly trend, anomaly cards, smart-plug widget |
| 2 | `campus` | Mapa de Campus | Geographic node placement across campuses |
| 3 | `buildings` | Edificios | Building inventory and instrumentation coverage |
| 4 | `deployments` | **Despliegues** | Installation-campaign lifecycle: create, activate, complete; technician form that can create a building + panel inline |
| 5 | `live` | Monitoreo en Vivo | V, A, kW, PF, Hz and buffer depth at **3 s** refresh |
| 6 | `cost` | Análisis de Costo | GDMTH base/intermediate/peak breakdown; CFE scraper status |
| 7 | `ai` | **Centro IA / Forecasting** | Forecast with an explicit confidence basis; `trained: false` is **shown, not hidden**; anomaly list; cluster assignments |
| 8 | `mining` | Minería de Datos | Clustering and pattern analysis |
| 9 | `dataExplorer` | Explorador de Datos | Ad-hoc query over the raw series, with an explicit `?context=` axis |
| 10 | `reports` | Reportes | PDF / XLSX / CSV generation for people who will not log in |
| 11 | `infra` | Infraestructura | Node health, heartbeat state, buffer depth |
| 12 | `smartplugs` | Smart Plugs | Fleet state, per-outlet power, building assignment, unassigned count |
| 13 | `settings` | Configuración | Thresholds, retention, tariff, AI toggles → `runtime_platform_settings.json` |

Plus a **login screen** with demo authentication and role-based page permissions.

> ⚠ **The frontend login is not an authorisation boundary** — DOCUMENTED in
> `docs/Security.md`. Roles shape **what the UI shows**, not what the API allows.

**Data Explorer's building list is derived, not stored** — DOCUMENTED design
rule: `/api/data-explorer/options` joins `buildings → energy_readings` filtered
to `scope.analytic_contexts`. A building appears **iff it owns at least one
production reading**. Never hardcode a building here.

### G.3 Known frontend gaps — VERIFIED

| Gap | Detail |
|---|---|
| **No test suite** | Backend has 6 suites; the React app has **none**. The largest quality gap in the repository. |
| `App.tsx` monolith | 2,532 lines; 12 of 13 screens are not extracted |
| ESLint | 36 pre-existing findings, advisory |
| Dead code | `components/ui/*`, `common.tsx`, `app.css`, `CostAnalytics.tsx` |
| No accessibility audit | Contrast checked; keyboard navigation and ARIA **not** |
| No screenshots capturable on the server | Playwright Chromium present but **cannot start** — `libatk-1.0.so.0`, `libatk-bridge-2.0.so.0`, `libatspi.so.0`, `libasound.so.2`, `libgbm.so.1`, `libXcomposite.so.1`, `libXdamage.so.1`, `libXfixes.so.3`, `libXrandr.so.2` all absent; installing them needs root |

## 2.H Analytics / AI

### H.1 Algorithm inventory — VERIFIED by reading `app/services/ml_engine.py`

#### A1 — Demand/cost forecasting

| Field | Value |
|---|---|
| **ALGORITHM** | `RandomForestRegressor(n_estimators=120, random_state=42, min_samples_leaf=1)` |
| **PURPOSE** | Forecast tomorrow's / this week's / this month's **cost in MXN** |
| **INPUT DATA** | `build_hourly_dataset(db, hours_back=168)` → hourly-aggregated `cost_mxn`, scope-filtered to `counts_in_analytics` contexts. Features are **`[hour_of_day, weekday]` only — two integers** |
| **OUTPUT** | `{model, trained, reason, tomorrow_mxn, week_mxn, month_mxn, confidence, points[]}` |
| **IMPLEMENTATION FILE** | `backend/app/services/ml_engine.py` → `random_forest_forecast(db)` (lines 117–221) |
| **STATUS** | **CURRENTLY USED** — `/api/ai-center`, AI Centre screen |

**Four honest caveats, all VERIFIED in source:**

1. ⚠ **C-07 — the documented feature set does not exist.** `docs/AI.md` claims
   *"hour of day and day of week, lagged demand, rolling means"*. The code builds
   `X.append([dt.hour, dt.weekday()])`. **There are no lags and no rolling
   means.**
2. **The forecast is clamped, not free.** `tomorrow = min(max(rf_tomorrow, 0.65 ×
   recent_daily_avg), 1.35 × recent_daily_avg)` — the RF output is bounded to
   ±35 % of a trailing 24-hour average *"para evitar sobreproyección"*. In
   practice this means the model's contribution is bounded to a ±35 % correction
   on a moving average.
3. **Week and month are multiplication, not modelling:** `week = tomorrow × 7`,
   `month = tomorrow × 30`.
4. **The `confidence` returned by this function is a dispersion heuristic**, not
   an error measure: `min(0.85, max(0.45, 1 − std(y)/mean(y)))`. The real
   backtested figure comes from a different function (A4).

**Untrained fallbacks, VERIFIED:** no rows → `trained: false` with everything
zero; fewer than 12 aggregated hours → conservative hourly average with
`confidence = 0.35` and `trained: false`.

#### A2 — Anomaly detection (unsupervised)

| Field | Value |
|---|---|
| **ALGORITHM** | `IsolationForest(n_estimators=120, contamination=0.08, random_state=42)` on `StandardScaler`-normalised features |
| **PURPOSE** | Find intervals unlike the rest of the node's behaviour |
| **INPUT DATA** | Same 168 h scope-filtered dataset. **7 features:** `power_kw`, `current`, `voltage`, `power_factor`, `delta_kwh`, `hour`, `weekday` |
| **OUTPUT** | Up to the **last 8** flagged intervals with `score`, a Spanish title, detected/expected values, severity and colour |
| **IMPLEMENTATION FILE** | `ml_engine.py` → `isolation_forest_anomalies(db)` (lines 227–320) |
| **STATUS** | **CURRENTLY USED** — AI Centre |

**Caveat, VERIFIED:** the *label* comes from IsolationForest, but the **title and
severity come from fixed thresholds** applied afterwards (`power_factor <
minPowerFactor` → "Factor de potencia bajo"; `current > maxCurrent` → "Corriente
elevada"; `hour < 6 and power_kw > 5` → "Consumo nocturno anómalo"; otherwise
"Patrón eléctrico atípico"). `contamination=0.08` **fixes the anomaly rate at
8 % by construction** — it will always find anomalies.

Minimum 20 samples, else `trained: false`.

#### A3 — Building load-profile clustering

| Field | Value |
|---|---|
| **ALGORITHM** | `KMeans(n_clusters=min(4, n_buildings), random_state=42, n_init=10)` on `StandardScaler`-normalised features |
| **PURPOSE** | Group buildings by load profile |
| **INPUT DATA** | Per-building SQL aggregate over `CLUSTER_WINDOW_DAYS`, **production contexts only**: `avg_power`, `peak_power`, `avg_current`, `avg_pf`, `cv` (coefficient of variation, recovered from the first two moments as `sqrt(E[x²] − E[x]²)`). Requires ≥ 5 rows and non-null power per building |
| **OUTPUT** | Named clusters with member building lists |
| **IMPLEMENTATION FILE** | `ml_engine.py` → `kmeans_building_clusters(db)` (lines 323–435) |
| **STATUS** | **CURRENTLY USED but structurally inert — see below** |

> ⚠ **C-08 — the KMeans labels are computed and then discarded.** VERIFIED:
>
> ```python
> labels = model.fit_predict(Xs)
> for label, meta, row in zip(labels, metadata, features):
>     avg_power, peak_power, avg_current, avg_pf, cv = row
>     if avg_pf < minPowerFactor:   cluster_name = "Bajo Factor de Potencia"
>     elif cv < 0.15:               cluster_name = "Carga Constante"
>     elif peak_power > 50:         cluster_name = "Alta Demanda"
>     else:                         cluster_name = "Uso Variable"
>     grouped[cluster_name].append(meta["name"])
> ```
>
> **`label` is never read inside the loop.** The grouping key is a four-way
> if/elif on fixed thresholds. The output labelled *"Cluster ML generado con
> K-Means"* is **rule-based, not KMeans-derived.** The model is fitted and its
> result unused.
>
> This must not be presented in a thesis as unsupervised clustering of building
> load profiles.

**Additional constraint:** with only **3 buildings** in the database (one of them
a placeholder), `k = min(4, n) = 3` at best and the exercise is degenerate
regardless.

Fewer than 2 qualifying buildings → `trained: false`, *"Se requieren al menos 2
edificios con lecturas reales."*

#### A4 — Forecast confidence (backtesting)

| Field | Value |
|---|---|
| **ALGORITHM** | Rolling-origin backtest of a **3-day moving average**; MAPE → confidence |
| **PURPOSE** | Give the UI a defensible confidence figure instead of an asserted one |
| **INPUT DATA** | 30 days of **local-date** daily cost from `energy_aggregate.hourly_energy` |
| **OUTPUT** | `{confidence, confidence_pct, method, samples, mape}` |
| **IMPLEMENTATION FILE** | `backend/app/services/model_confidence.py` → `real_forecast_confidence(db)` |
| **STATUS** | **CURRENTLY USED** |

**Caveat, VERIFIED:** `predicted = mean(values[i-3:i])` — this backtests a
**3-day moving average**, *not* the RandomForest. It is an honest measure of how
predictable the series is; it is **not** the forecaster's own error.
Fewer than 7 complete daily points → `confidence: None` with an explicit reason.

Its docstring records two deliberate corrections: days are **local** days (it
used to group by UTC, so its days were offset by six hours from every other daily
figure), and the delta spanning local midnight is counted rather than dropped.

#### A5 — Anomaly event grouping

| Field | Value |
|---|---|
| **ALGORITHM** | Gap-based temporal merge |
| **PURPOSE** | Turn 160 consecutive anomalous intervals into **one 40-minute event** |
| **INPUT** | Scored anomaly items |
| **OUTPUT** | Merged events |
| **IMPLEMENTATION FILE** | `ml_engine.py` → `group_anomaly_events(items, max_gap_minutes=10)` |
| **STATUS** | **CURRENTLY USED** |

Same lesson as the alerting policy, applied to analytics.

#### A6 — Threshold-rule anomalies (the "Anomalies" screen)

| Field | Value |
|---|---|
| **ALGORITHM** | Fixed threshold rules with ACTIVE/RESOLVED lifecycle |
| **PURPOSE** | Operator-facing anomaly surface with historical resolution |
| **INPUT DATA** | `energy_readings` + `platform_settings` thresholds |
| **RULES** | `power_factor < minPowerFactor` (0.90) · `current > maxCurrent` (200 A) · **night consumption** (`NIGHT_POWER_KW`, hours < 6) · **demand spike** (`avg_power × 1.35`) |
| **OUTPUT** | Anomaly records with `threshold`, detected value, first-breach and resolution timestamps |
| **IMPLEMENTATION FILE** | `backend/app/services/anomaly_engine.py` → `detect_node_anomalies()`, `detect_all_anomalies()`, `_demand_spike()` |
| **STATUS** | **CURRENTLY USED** — Anomalies screen |

**Lifecycle, VERIFIED in the module docstring:** `ACTIVE` = the newest reading in
scope still violates the threshold; otherwise resolved, with the resolution
instant found by `_first_reading_after()`.

> ⚠ **Known limitation, in the source comments:** *"platform is UTC-6, so 'night'
> is currently offset by six hours."*

#### A7 — Power-factor detection

**There is no dedicated power-factor algorithm.** Power factor appears in four
independent places — VERIFIED:

| Where | Mechanism | Threshold |
|---|---|---|
| `anomaly_engine` | fixed rule | `minPowerFactor` = 0.90 from `platform_settings` |
| `ml_engine` IsolationForest | one of 7 features; then a fixed rule names the finding | 0.90 |
| `ml_engine` KMeans | one of 5 features; also the first branch of the naming if/elif | 0.90 |
| `app/monitoring/metrics.py` `electrical.power_factor` | **paging rule** with sustain, hysteresis and severity routing | derived; report-only below CRITICAL |

The design principle is explicit: *"Power factor 0.89 is noise; 0.55 is a fault on
the same metric."*

#### A8 — LLM narration

| Field | Value |
|---|---|
| **ALGORITHM** | Google Gemini, `GEMINI_MODEL=gemini-2.0-flash` |
| **PURPOSE** | Narrative prose **over figures the statistical layer has already computed** |
| **IMPLEMENTATION FILE** | `backend/app/services/gemini_engine.py` |
| **STATUS** | **OPTIONAL, gated by `LLM_ENABLED`** |

**Boundaries enforced by construction — DOCUMENTED:** the LLM **never computes a
number**; `LLM_ENABLED=0` disables every call with no loss of capability; no
measurement data is sent beyond the aggregates needed for the summary; a missing
`GEMINI_API_KEY` disables the feature rather than failing the process.

> **The forecasting is not an LLM wrapper.** The models are scikit-learn, they
> run on the server, and the language model is a presentation layer that can be
> switched off.

### H.2 The scope filter — the most important analytics mechanism

`app/db/scope.py` is the **single enforcement point**. Every analytics call site
uses it; `db.query(EnergyReading)` appears in **zero** analytics paths.

Two independent exclusions:

1. **Context** — `measurement_contexts.counts_in_analytics`. Only `production`
   qualifies today.
2. **Building metadata** — `buildings.is_placeholder`. Excludes the *building*
   from building-level breakdowns without discarding measurements that may be
   perfectly real.

Enforced **structurally, not per query**: invariant `INV-09` makes it impossible
for a non-production reading to carry a building. *"A future analytics call site
cannot reintroduce contamination by forgetting a filter."*

Deliberately **not** scoped: `/api/infra` and node-inventory counts in reports —
a node on the bench is still a node that is alive.

> **The single worst source of wrong analytics in this platform's history** was
> building profiles trained on bench data — *"a model confidently describing the
> load profile of a building that was never measured."* The `ml_engine` source
> carries the comment at the exact line: *"123k noise-floor rows shared a
> building with real load."*

**Cost figures were never contaminated** — VERIFIED: every cost path filters
`energy_kwh IS NOT NULL`, and N003 reported `NULL` on all 123,617 of its rows.
The exposure was in ML profiles, `anomaly_engine` and `metrics`.

### H.3 Honesty guarantees — VERIFIED as implemented

| Guarantee | Mechanism | Verified |
|---|---|:--:|
| A model with insufficient history reports `trained: false` | Explicit guards in every model function; **the UI shows this state** | ✅ |
| Minimum 7 days before a forecast is offered | `ai.minHistoryDays = 7` | ✅ |
| Confidence is backtested, not asserted | `model_confidence.py` | ✅ (but see A4 caveat) |
| Clustering requires enough operational buildings | Guard in `kmeans_building_clusters` | ✅ |
| Anomalies are grouped, not enumerated | `group_anomaly_events(max_gap_minutes=10)` | ✅ |
| Bring-up data never reaches a model | `scope.analytic_contexts` + `INV-09` | ✅ |

**Models are trained on request, not on a schedule** — at this data volume
training takes seconds, and it removes an entire class of "the model is stale"
bugs. `*.joblib` is already git-ignored for the day that changes.

### H.4 What is NOT claimed

- No demonstrated forecast accuracy against held-out data beyond the moving-average
  MAPE of A4.
- No demonstrated energy saving, cost reduction or operational improvement
  attributable to the platform.
- No comparison against any baseline forecaster.
- No validation of the anomaly detector against labelled faults.
- No cross-validation, no hyper-parameter search. All parameters
  (`n_estimators=120`, `contamination=0.08`, `k=min(4,n)`) are fixed constants.

## 2.I Alerting

### I.1 The subsystem — VERIFIED

| Property | Value |
|---|---|
| Code | `backend/app/monitoring/` |
| Version | 1.1.0 |
| Process | **separate OS process**, `flock -n /tmp/energy-platform-monitoring.lock … -m app.monitoring.scheduler` |
| Running since | 2026-08-07 (PIDs 2528252/2528253), 489 CPU-minutes at audit |
| Supervisor | `monitoring/run-monitoring.sh` + a `@reboot` crontab entry. The proper systemd unit exists but **needs root to install** |
| Tables | 6, in their own namespace. **No existing table is modified** |
| API | `/api/monitoring` — 14 routes |
| Tests | `tests/test_monitoring.py`, **404 checks** |

**Three reasons it is a separate process** — DOCUMENTED, each concrete:
an in-process scheduler would **multiply alerts** if gunicorn moved off `-w 1`;
it **could not report a backend crash** because it would die with it; a backend
`SIGHUP` must not restart monitoring.

> **Never `pgrep -f "app.monitoring.scheduler"` from a shell** — the pattern
> matches the invoking shell's own command line. Read the PID from
> `backend/monitoring_watchdog.json`.

### I.2 Rules — VERIFIED, 42 registered

```bash
grep -rhoE '@rule\("[a-z_.]+"' backend/app/monitoring/*.py | cut -d'"' -f2 | sort
```

⚠ C-09: documentation says **39**; the current count is **42**.

| Subsystem | Count | Rules |
|---|---:|---|
| **Server** | 15 | `cpu`, `memory`, `swap`, `disk`, `disk_full`, `filesystem_readonly`, `load`, `iowait`, `temperature`, `services`, `failed_units`, `time_sync`, `reboot_required`, `kernel`, `firewall` |
| **Electrical** | 10 | `implausible`, `voltage`, `frequency`, `current`, `power_factor`, `phases`, `consumption`, `no_consumption`, `reverse_energy`, `ups` |
| **Node** | 7 | `heartbeat`, `resources`, `power`, `storage`, `connectivity`, `collector`, `measurements` |
| **Security** | 4 | `unknown_node`, `duplicate_node_identity`, `unauthenticated_producer`, `certificates` |
| **Network** | 3 | `internet`, `dns`, `tailscale` |
| **Backend** | 1 | `api` |
| **Database** | 1 | `health` |
| **Smart plug** | 1 | `availability` |
| **Total** | **42** | |

Note `server.firewall` and `security.certificates` are registered under
`Subsystem.SECURITY`. The three `security.*` node rules
(`duplicate_node_identity`, `unauthenticated_producer`, `unknown_node`) were
added by the identity work of 2026-08-06/07.

Module layout: `config.py` (layered typed config: defaults →
`monitoring_config.json` → env) · `severity.py` · `models.py` · `storage.py` ·
`rules.py` (registry + engine — **the extension point**) · `health.py` ·
`heartbeat.py` · `metrics.py` · `thresholds.py` · `lifecycle.py` · `alerts.py` ·
`notifications.py` · `channels/telegram.py` · `scheduler.py` · `router.py` ·
`history.py` · `status.py`.

**Extension model:** a rule is added by writing one `@rule`-decorated function —
registration is automatic. A channel is added by implementing
`NotificationChannel` and adding one line to `build_channels()`.

### I.3 Thresholds — physical reality, not statistics

Resolution order — DOCUMENTED and VERIFIED as implemented:

```
deployment panel / breaker rating
      └─ absent ─▶ node CT rating
            └─ absent ─▶ learned baseline (operational deployments only, min 500 samples)
                  └─ insufficient ─▶ conservative fallback
```

> **A learned baseline may NEVER exceed the physical ceiling.** Otherwise it
> learns an overload as normal and stops reporting it — the failure mode where
> the monitoring system is quiet *precisely because* something is wrong.

> **Do not inherit `runtime_platform_settings.json` for alerting.** Those values
> (`maxCurrent: 200`, `minPowerFactor: 0.90`, `demandSpike: 25`) are **UI display
> defaults**, and they were the direct cause of the worst noise. Colouring a
> chart and paging a human are different decisions.

⚠ **The physical-rating columns are all NULL today** — VERIFIED: `nodes.ct_max_current_a`,
`nominal_voltage_v`, `phase_count`, `warning_current_a`, `critical_current_a`,
`emergency_current_a`, `sustained_seconds` are NULL on all three nodes, and the
equivalent columns on `deployments` are NULL on all four deployments. Migration
008 created them; **nobody has entered the values.** Every threshold therefore
resolves to a learned baseline or the fallback. → Q-05.

### I.4 The alerting policy — the four principles and their evidence

> **The first production run sent 1,386 Telegram messages in four days** — 697 on
> one day, 73 in a single hour. The policy was rebuilt on 2026-07-29 from the
> actual message history.

The standard it is tuned to: *"if I receive this at 3 a.m., would I actually get
out of bed?"*

| # | Principle | The failure that produced it |
|---|---|---|
| 1 | **Gate on deployment state first.** Read `node_commission_states` (`is_monitored`, `may_upload`) and `deployment_statuses` (`is_operational`). Never invent a parallel lifecycle model. | **98 % of the noise — 1,288 of 1,312 messages — came from nodes with no operational deployment.** |
| 2 | **Never set a threshold inside the normal operating range.** | The **200 A default sat at N001's 94th percentile** and produced **962 messages** on its own. |
| 3 | **Require persistence and hysteresis.** | **404 of 472 alerts lasted under two minutes.** Without hysteresis, a value oscillating on a threshold sends two messages per crossing forever. |
| 4 | **Route by "would this page someone", not by whether it is true.** Most rules are report-only; they break out and page at CRITICAL. | Power factor 0.89 is noise; 0.55 is a fault on the same metric. |

**Two additional design rules, both learned from concrete false alarms:**

- **Capacity is two axes, never a timer.** `server.disk` reports on df's
  denominator (`used/(used+avail)`, **not** `used/total`) plus a days-to-full
  projection, and takes the worse of the two. Its `max_severity` is set to its own
  computed severity so the duration ladder cannot raise it. *Time-driven
  escalation of a slow trend produced an EMERGENCY and 71 notifications for a disk
  with three weeks of headroom.*
- **Guard every threshold rule against the noise floor.** Idle meters report
  ~1e-5 A and ~−1e-9 kW; naive comparisons produced a permanent CRITICAL
  imbalance and a phantom "reverse power flow".

**`Finding.max_severity`** caps duration escalation for **persistent states**
(node awaiting commissioning, node in standby, chronic electrical imbalance) and
also suppresses their hourly reminders, so EMERGENCY stays meaningful.

**Checks with no data source on this deployment report `unavailable` rather than
passing** — UPS, TLS certificates, tailscale, ufw, server temperature, git
commit. *Reporting `False` for a capability a board does not have is a lie the
monitoring system will act on.*

### I.5 Alert lifecycle — VERIFIED

```
Evaluating → Pending (condition true)
Pending → Evaluating (cleared early) | → Firing (sustain window held)
Firing → Deduplicated (identical alert open, occurrence counted)
Firing → ReportOnly (INFO/WARNING) → hourly report only
Firing → Outbox (CRITICAL/EMERGENCY) → retried until delivered → Open
Open → Escalated (still true after escalation window) → Open
Open → Resolving (condition absent) → Open (reappeared) | → Resolved (absent for full hysteresis)
```

`monitor_alerts` columns (VERIFIED): `alert_id`, `fingerprint`, `rule_id`,
`subsystem`, `severity`, `initial_severity`, `peak_severity`, `status`, `title`,
`summary`, `node_code`, `campus`, `building`, `deployment`, `hostname`, `metric`,
`current_value`, `expected_value`, `created_at`, `last_seen_at`, `escalated_at`,
`acknowledged_at`, `acknowledged_by`, `resolved_at`, `duration_seconds`,
`last_notified_at`, `notification_count`, `occurrence_count`, `context`.

Severity ladder: `INFO → WARNING → ERROR → CRITICAL → EMERGENCY`.

### I.6 Live alert history — VERIFIED, `monitor_alerts` (675 rows)

**674 resolved, 1 open** (`node.filesystem_readonly_contradiction`, WARNING).

| Finding code | Severity | Count |
|---|---|---:|
| `electrical.current` | WARNING | **423** |
| `electrical.current` | CRITICAL | 56 |
| `node.undervoltage` | ERROR | 30 |
| `electrical.consumption_spike` | WARNING | 25 |
| `node.undervoltage` | CRITICAL | 17 |
| `electrical.power_factor` | WARNING | 16 |
| `smart_plug.offline` | WARNING | 14 |
| `node.undervoltage` | **EMERGENCY** | 10 |
| `electrical.current_imbalance` | CRITICAL | 7 |
| `node.heartbeat_lost` | WARNING | 7 |
| `node.filesystem_readonly` | **EMERGENCY** | 4 |
| `node.filesystem_readonly_contradiction` | WARNING | 4 (1 open) |
| `security.identity_violation` | **EMERGENCY** | 4 |
| `backend.api_latency` | WARNING | 3 |
| `network.internet` | ERROR | 3 |
| `node.heartbeat_lost` | EMERGENCY | 3 |
| `node.heartbeat_never` | WARNING | 3 |
| `node.measurements_stale` | EMERGENCY | 3 |
| `electrical.current_imbalance` | WARNING | 3 |
| `security.duplicate_node_identity` | CRITICAL | 2 |
| `security.unauthenticated_producer` | WARNING | 2 |
| `server.cpu` | CRITICAL / WARNING | 2 / 2 |
| `network.dns` | ERROR / CRITICAL | 2 / 1 |
| *(21 further codes)* | various | 1 each |

**`electrical.current` alone accounts for 480 of 675 alerts (71 %)** — the
signature of principle 2 (a threshold inside the normal operating range) in the
historical record.

Also present, each exactly once: `electrical.reverse_energy`,
`electrical.voltage_imbalance`, `electrical.voltage_low` (EMERGENCY),
`node.buffer`, `node.clock_drift`, `node.latency`, `node.no_measurements`,
`node.spi`, `node.standby`, `backend.api`.

### I.7 Notification pipeline — VERIFIED

| Property | Value |
|---|---|
| Channel | **Telegram**, bot `@ThesisIoT_bot`, private chat |
| Credentials | `backend/.env`, mode 600 — `MONITORING_TELEGRAM_BOT_TOKEN`, `MONITORING_TELEGRAM_CHAT_ID` |
| Mechanism | **durable outbox** (`monitor_notification_outbox`) that never discards a message |
| Retry | `attempts`, `next_attempt_at`, `last_error`, `dedupe_key` columns |
| **Delivered** | **2,165** (2026-07-26 16:32 → 2026-08-13 14:50) |
| **Failed** | **31** (all within 2026-07-29 13:44 → 14:23 — a single 39-minute window) |
| Report | hourly platform status report covering the whole platform |
| Self-monitoring | the scheduler detects and reports its own downtime |

The 31 failures clustered in one 39-minute window on 2026-07-29 — the day the
alerting policy was rebuilt — and **nothing was lost**: the outbox retained them.

### I.8 Heartbeat/node alerting vs legacy alerting

- `monitoring/heartbeat.py` iterates **every node unconditionally** — correctly
  decoupled from deployment state. A node that is uninstalled but should be alive
  is still reported.
- The legacy `routers/alerts.py` iterates only nodes whose commission state has
  `is_monitored`, and is therefore **silent by design** for `registered` nodes.

**Two rule classes** — DOCUMENTED:

| Class | Applies to | Examples |
|---|---|---|
| **Liveness** | every monitored node, whatever it is measuring | heartbeat age, buffer growth, reading staleness |
| **Electrical quality** | **only** nodes declaring `production` | power factor, frequency, imbalance |

*"A bench rig reads ~1e-5 A and PF 0.00 by design; judging it against production
thresholds produces a permanent false alarm and trains the operator to ignore the
panel."*

### I.9 Suppression behaviour, restated

| Mechanism | Effect |
|---|---|
| Deployment gate | No operational deployment → rule reports *"cannot evaluate"*, never alerts |
| Commission gate | `is_monitored = 0` → silence is expected, not an alarm |
| Sustain window | Condition must hold before notifying |
| Hysteresis | Condition must be absent before resolving |
| Report-only routing | INFO/WARNING → hourly report only; CRITICAL/EMERGENCY → Telegram |
| `Finding.max_severity` | Caps duration escalation and suppresses hourly reminders for persistent states |
| Noise-floor guards | Idle-meter values do not trip electrical rules |
| `unavailable` verdict | A check with no data source reports unavailable, never a pass |

**Verifying a change is mandatory** — the sensitivity checks
(`tests/test_monitoring.py` §19–25 and `tests/test_synthetic_deployment.py`)
assert real faults still fire while known noise stays silent. *"A monitoring
system that went quiet because it stopped looking is worse than one that is
noisy."*

## 2.J Deployment model — the core abstraction

### J.1 What a deployment is

A **deployment is a temporary installation campaign**: this node, measuring this
panel in this building, over this time window. It is the join between hardware
and place, and it is what makes the instrumentation *portable* — a small number
of nodes can characterise many buildings by moving between them.

### J.2 The chain

```
NODE  ──(1:N)──▶  DEPLOYMENT  ──(N:1)──▶  BUILDING
                       │                      │
                       └──(N:1)──▶ ELECTRICAL_PANEL
                       │
                       └──(1:N)──▶ ENERGY_READINGS
                                    (resolved by captured_at, written once)
```

A reading's `deployment_id`, `building_id` and `electrical_panel_id` are **stamped
at ingest and never re-derived on read.**

### J.3 The lifecycle

```
planned ──▶ installing ──▶ active ──▶ completed
   │            │             │
   └────────────┴─────────────┴──────▶ cancelled
```

| Status | `allows_attribution` | `is_operational` | `is_terminal` | `is_exclusive` | Treatment |
|---|:--:|:--:|:--:|:--:|---|
| `planned` | no | no | no | no | Scheduled; no hardware in the field |
| `installing` | no | **yes** | no | **yes** | Technician on site; verification readings may be taken |
| `active` | **yes** | **yes** | no | **yes** | Verified and measuring. Readings in range are attributed here |
| `completed` | **yes** | no | **yes** | no | Campaign ended. **Still attributes its own historical readings** |
| `cancelled` | no | no | **yes** | no | Called off. Attributes nothing |

**Three properties that matter:**

1. **`completed` still attributes.** A campaign that ended does not stop owning
   what it measured. This is why "archived" is a display concept, never a data one.
2. **There is no transition out of `completed` or `cancelled`.** Reopening would
   retroactively change attribution, so a **new deployment is created instead.**
3. **`is_exclusive`** (migration 009) means at most one `installing`/`active`
   deployment per node at a time.

`end_date IS NULL` means **open-ended, not missing.**

### J.4 Attribution — VERIFIED in `app/services/attribution.py`

**Pure, stateless, deterministic, idempotent. No I/O, no clock, no globals, no
mutable cache.**

```
resolve(state, node_id, captured_at) ─▶ Decision(deployment, building, panel,
                                                 context, reason, flags)
```

For each measurement **independently** — never per batch — find the deployment
where `node_id` matches, the measurement's own timestamp falls in the window, and
the status allows attribution.

| Outcome | Reason code |
|---|---|
| Exactly one match | `ATTRIBUTED_IN_WINDOW` |
| Node has no deployments | `NO_MATCHING_DEPLOYMENT` |
| Deployments exist, none covers the timestamp | `OUTSIDE_DEPLOYMENT_WINDOW` |
| Covering deployment cannot attribute | `DEPLOYMENT_NOT_ATTRIBUTING` |
| **More than one covers it** | **`MULTIPLE_MATCHES` — attributes nothing** |
| Node declares a non-attributable context | `BENCH_NODE`, `LABORATORY_NODE`, `INFRASTRUCTURE_VALIDATION_NODE`, … |
| Node may not upload | `NODE_MAY_NOT_UPLOAD` |

Flags are **additive and never change attribution**: `PLACEHOLDER_BUILDING`,
`MISSING_BUILDING`, `MISSING_PANEL`, `OPEN_ENDED_DEPLOYMENT`.

**Three design invariants:**

- **Attribution follows `captured_at`, never upload time.** The resolver is never
  given the ingestion instant, so it cannot depend on it even by accident.
- **Ambiguity is a result, not a tiebreak.** Overlapping windows produce
  `MULTIPLE_MATCHES` and no attribution. The resolver never silently chooses.
- **The resolver is an ingest-time function.** It reads the node's *current*
  declared context — right for new readings, wrong for history. **It must never
  be run as a backfill over stored rows.**

**Immutability:** a `BEFORE UPDATE` trigger on `energy_readings` aborts any
statement touching `node_id`, `deployment_id`, `building_id`,
`electrical_panel_id` or `context`. Scoped precisely as *"immutable at runtime;
correctable only by supervised migration"* — a migration that must correct
attribution drops the trigger, acts within a backed-up reversible step declaring
the `allow_attribution_change` waiver, and reinstates it. **Measured values are
immutable under all circumstances, with no waiver** (`INV-02`).

### J.5 Context gates attribution *before* deployments

VERIFIED in `attribution.resolve()`:

```python
if context not in state.attributable_contexts:   # {production, commissioning}
    return Decision(None, None, None, context, INFRASTRUCTURE_VALIDATION_NODE)
```

**A node declared `infrastructure_validation` attributes nothing no matter what
its deployment says.** This caused a real defect: deployment 7 was activated on
N001 on 2026-08-13 and attributed **nothing**, because nothing in the platform
ever wrote `nodes.measurement_context` — only readers existed.

**Fixed 2026-08-13:** `deployment_ops` now maintains it — `activate()` →
`MEASURING_CONTEXT` (`production`); `complete()`/`cancel()` → `STANDBY_CONTEXT`
(`infrastructure_validation`) when no other operational deployment remains.
`_stop_measuring` only rewinds a node the lifecycle itself set to production, so
a deliberate `bench`/`laboratory` declaration is never clobbered.
`current_deployment(db, node_id, exclude_id=...)` answers *"is anything else still
running?"* without depending on flush ordering.
Tests: `tests/test_deployment_lifecycle.py` § *"the lifecycle keeps
nodes.measurement_context true"*.

### J.6 ⚠ Two legitimate meanings of "active deployment"

| | Source | Means |
|---|---|---|
| `deployments.status == 'active'` | `app/db/lifecycle.py`, `deployment_statuses` | **administrative** — what an operator declared |
| `telemetry_state` | `app/services/deployment_scope.py` | **observed** — a reading landed within 5 min |

They are **deliberately different**: a `completed` campaign can still be
ingesting — deployment 5 did for weeks. Do not add a third meaning. The Dashboard
selector that rendered the second one as an "ACTIVE/ARCHIVED" badge was removed
on request, because two different questions rendered identically is how they get
confused.

### J.7 The four deployments — VERIFIED live, 2026-08-13

| id | node | building | panel | declared window | status | readings owned | window of owned readings |
|---:|---|---|---|---|---|---:|---|
| **4** | N001 | 8 *Edificio de prueba* (**placeholder**) | 8 *Tablero Principal* | 2026-06-14 → open | `completed` | **118,620** | 2026-06-14 21:57 → 2026-07-30 21:09 |
| **5** | N003 | 8 *Edificio de prueba* (**placeholder**) | 8 *Tablero Principal* | 2026-06-14 → 2026-06-21 | `completed` | **4,499** | 2026-07-26 22:40 → 2026-08-06 14:18 |
| **6** | N001 | 9 *Edificio Principal Prueba* | 9 *Centro de Datos* | 2026-07-30 → 2026-08-07 | `completed` | **22,443** | 2026-07-30 21:09 → 2026-08-06 14:18 |
| **7** | N001 | 10 *Edificio Principal 2.0* | 10 *SITE* | 2026-08-13 → 2026-08-22 | **`active`** | **170** | 2026-08-13 14:18 → 14:52 |

Deployment 7's note (in Spanish, as entered by the operator): *"Despliegue
temporal para comparación de cargas en periodos de ingreso."* — **a temporary
deployment for comparing loads during enrolment periods.** This is the deployment
model being used for its intended purpose.

**All three buildings are `is_user_defined = 1`, created from the technician
deployment form.** Building 8 is `is_placeholder = 1`.

**All physical-rating columns on all four deployments are NULL** —
`panel_main_breaker_a`, `ct_max_current_a`, `nominal_voltage_v`, `phase_count`,
`warning_current_a`, `critical_current_a`, `emergency_current_a`,
`sustained_seconds`.

### J.8 ⚠ Known attribution defects, pre-existing and deliberately not fixed

| Defect | Evidence | Status |
|---|---|---|
| **Deployments 5 and 6 own readings after their `closed_at`.** Deployment 5 closed 2026-06-21 but owns rows to 2026-08-06; deployment 6 closed 2026-08-03 but owns rows to 2026-08-06. | Live query | **HISTORICAL, left alone deliberately.** The old pre-resolver pipeline stamped a batch with the node's newest deployment regardless of `captured_at`. The current resolver cannot produce this. **Fixing it would mutate historical attribution** — ask before touching. |
| **Deployment 5 owns 4,499 rows of N003 `production`-classified data with `power_kw ≈ 0` and `voltage ≈ 0.8 V`** — from the dead ADS front end (§B.5). | Live query + `affected-rows-20260806_142730.md` | **Live data-quality defect.** These rows are attributed to a real building and classified `production`. → Q-06. |
| **10,450 N001 rows carry deployment 6 / building 9 attribution outside any operational window**, 2026-08-03 21:57 → 2026-08-06 14:18, avg 0.017 kW. | `affected-rows-20260806_142730.md` | Documented, read-only report; **no row was mutated.** |
| **Only ~25 % of N001's readings fall inside deployment 4's originally declared window.** | ADR-0006 | **Handled** — `end_date` set to NULL (open-ended) rather than stranding the data. |
| **`Node.status` is a stale third vocabulary** (`online`/`offline`/`available`) that disagrees with `last_sync`. | Live: N003 shows `status='offline'` while `last_sync` is 60 s old and `monitor_node_heartbeat_latest.online = 1` | Known wart; **every consumer already recomputes health** rather than trusting it. |

---

# PHASE 3 — DEVELOPMENT HISTORY

Reconstructed from `CHANGELOG.md`, `edge/CHANGELOG.md`, the ADRs, the migration
table (`schema_migrations.applied_at` — machine timestamps, not narrative),
`git log`, and the incident evidence files.

**Dating confidence.** Migration timestamps and git commit dates are VERIFIED.
Changelog dates are DOCUMENTED. Anything before 2026-06-04 (the first commit) is
reconstructed from data timestamps only and is marked as such.

**Timeline overview:**

| Date | Event | Source |
|---|---|---|
| **2026-05-13 14:20:15** | **First measurement in the platform** (N003) | `MIN(energy_readings.timestamp)` — VERIFIED |
| 2026-05-29 | `deployment_week.csv` written on N003 (22.6 MB export) | file mtime on node — VERIFIED |
| 2026-06-04 | Repository `Initial commit` | `git log` — VERIFIED |
| 2026-06-14 | React migration; first N001 series; v0.1.0 | `git log` + DB — VERIFIED |
| 2026-06-14 → 06-19 | 59 frontend commits: connect every screen to the real API | `git log` — VERIFIED |
| 2026-06-19 | v0.2.0 platform surface complete | CHANGELOG — DOCUMENTED |
| 2026-06-20 21:51 | N003's prototype series ends | DB — VERIFIED |
| 2026-07-03 15:32:39 | N001's `energy_kwh` semantics change (counter → interval) | `measurement_eras` — VERIFIED |
| 2026-07-20 | `energy-node-tools` disabled on N002 | node filesystem — VERIFIED |
| 2026-07-24 17:16 | N003 converted **from** ADS1256 **to** Shelly, then back | `poller.py.*_backup_*` mtimes — VERIFIED |
| 2026-07-25 | Smart plugs land; edge v1.2.0; v0.3.0 | CHANGELOG + DB — VERIFIED |
| **2026-07-26 21:54 → 23:03** | **Seven migrations in one evening — the architecture redesign** | `schema_migrations` — VERIFIED |
| 2026-07-26 → 07-29 | Monitoring's first production run: **1,386 Telegram messages in 4 days** | CHANGELOG + outbox — DOCUMENTED |
| 2026-07-29 14:43 | Migration 008; alerting policy rebuilt; v1.1.0 | `schema_migrations` — VERIFIED |
| 2026-07-30 22:17–22:33 | Migrations 009, 010, 011 — deployment integrity | VERIFIED |
| 2026-07-31 19:11 | Migration 012 — canonical measurement model (ADR-0007) | VERIFIED |
| 2026-08-01 | **43 h 37 m node outage** — brownout latch | `recovery-validation.md` — DOCUMENTED |
| 2026-08-04 | Repository published; v1.2.0; CI; 16 commits rewritten | `git log` — VERIFIED |
| **2026-08-06 13:46 / 14:17** | **Migrations 013, 014 — authentication enforced** | `schema_migrations` — VERIFIED |
| 2026-08-06 | Identity-collision and filesystem-readonly root causes | evidence files — VERIFIED |
| 2026-08-07 | N002 converged onto the canonical collector (D2); retention; simplification audit | `git log` — VERIFIED |
| 2026-08-10 | Node packages vendored into git; Recovery Manager core | `git log` — VERIFIED |
| 2026-08-11 | SAFE MODE proven end-to-end on a live node | `git log` — VERIFIED |
| **2026-08-13** | N003 credential installed (401→403); deployment 7 activated; `measurement_context` lifecycle fix | violations table + DB — VERIFIED |

---

## T1 — Initial measurement concept → Shelly-based acquisition

| | |
|---|---|
| **BEFORE** | No platform. The question was whether a campus panel could be instrumented cheaply enough to move the instrument between buildings. |
| **PROBLEM** | A campus receives **one electricity bill**. It does not say which building caused it, which hour was expensive, whether a fault is developing, or what next week will cost. |
| **DECISION** | Measure at the **panel** with a commercial three-phase meter (**Shelly Pro 3EM**) read by a Raspberry Pi over HTTP, rather than building an analogue front end first. |
| **AFTER** | Continuous three-phase acquisition at 15 s from 2026-05-13. `deployment_week.csv` (VERIFIED on N003, 22.6 MB, 120,103 data rows) is the artefact of that first campaign: per-phase V, I, active/apparent power, PF, frequency, plus totals. |
| **CURRENT STATUS** | **CURRENT.** This is still how N001 and N002 measure. |

**Evidence:** `deployment_week.csv` header and first rows, VERIFIED on N003
2026-08-13; `nodes.hardware_kind = 'shelly'` for N001/N002; `collector.py`
`SHELLY_EM_URL`.

## T2 — Edge collector: buffer before upload

| | |
|---|---|
| **BEFORE** | A poller that read the meter and posted. A backend outage lost data. |
| **PROBLEM** | The backend is a single server on a campus network. Outages are normal, not exceptional. |
| **DECISION** | **Two independent loops.** Commit every sample to a local SQLite buffer *before* any upload is attempted; drain the buffer on a separate 60 s loop. |
| **AFTER** | A backend outage delays data instead of losing it, up to 7 days. `sync_status` 0/1/2 tracks each row. This is what makes an otherwise alarming operation safe: **ingestion may block for minutes during a migration with no consequence beyond a deeper buffer.** |
| **CURRENT STATUS** | **CURRENT**, on all three nodes. |

**Cost, VERIFIED:** the sync loop has a **head-of-line block** — one permanently
rejected row halts the queue forever. N002's buffer stood at 23,517 rows at
audit; N003's at 7,217 pending.

## T3 — Frontend: static prototype → React application

| | |
|---|---|
| **BEFORE** | `2026-06-phase1-prototype.html` — a **single-file React 18 prototype** loading React from a CDN. |
| **PROBLEM** | Not maintainable, not offline-capable, not covered by dependency auditing, and not connected to real data. |
| **DECISION** | Migrate to React 19 + Vite + TypeScript on **2026-06-14**. First commit: *"Phase 1 - Claude dashboard successfully migrated to React"*. |
| **AFTER** | 59 commits over five days, each connecting one screen to a real API: KPIs, hourly cost chart, buildings, nodes, AI insights, deployment form, organization API, live monitoring, metrics, anomalies, data explorer, login, settings, CFE scraper status. |
| **CURRENT STATUS** | **CURRENT.** The prototype is retained in `docs/prototype/` for provenance, and was **moved out of `frontend/public/`** in v1.2.0 because the production static server was publishing it on the same origin as the live dashboard. |

**Evidence:** `git log --reverse` VERIFIED; `docs/prototype/README.md`.

## T4 — Smart plugs: sub-metering as a separate concern

| | |
|---|---|
| **BEFORE** | Only panel-level measurement. *"Which building"* was answerable; *"which outlet"* was not. |
| **PROBLEM** | A panel total cannot tell a facilities manager which appliance to act on. |
| **DECISION** | **Shelly Plug US Gen4 as accessories of a deployment, never as Energy Nodes.** Separate tables, separate buffer file, separate API prefix. Discovery and polling **only on the Pi**. |
| **AFTER** | 4 plugs, 152,493 readings (VERIFIED live). Ownership is explicit — the first node to report a plug claims it. Identity is the **MAC**, not the IP. RPC is **read-only**: the platform is a meter, not an actuator. |
| **CURRENT STATUS** | **CURRENT.** Edge component v1.2.0. |

**Why separate tables:** *"A node measures a panel; a plug measures an outlet
downstream of that panel. Summing them would double-count. Keeping them in
separate tables makes that mistake structurally impossible rather than a rule
someone has to remember."*

**Evolution within the component** — VERIFIED, `edge/CHANGELOG.md`:

| Version | Change |
|---|---|
| 1.0.0 | Initial Gen4 RPC source |
| 1.1.0 | **Identify by capability, not product name** — a device registers only if it answers `Shelly.GetDeviceInfo`, exposes a controllable `Switch` at id 0, and reports both instantaneous power and cumulative energy |
| 1.2.0 | `health()` API + `smart-plug-health` CLI; `source_state` table so health is readable from another process; **explicit ownership** replacing last-writer-wins; MAC/duplicate/timestamp validation; upgrade-aware idempotent installer |

## T5 — The architecture redesign of 2026-07-26 — the pivotal transition

**This is the most important transition in the project's history.**

| | |
|---|---|
| **BEFORE** | Four distinct concepts collapsed into **two database columns**, `Node.last_sync` and `Deployment.status`. |
| **PROBLEM** | Four production defects, each named by file and line in ADR-0001: <br>• `routers/dashboard.py:340` reported `active_deployments` as the count of nodes whose `last_sync` was recent — **the `Deployment` table was never consulted**. <br>• `routers/deployments.py:48` replaced stored lifecycle with an `effective_status` derived from node connectivity, so a completed campaign on a live node reported as active, and an active campaign on an unplugged node reported as historic. <br>• `routers/edge.py:64` gated ingestion on `Deployment.status`, so **completing a campaign silently stopped data collection** — already forcing a hotfix that widened the filter to `("active","completed")`. <br>• `routers/alerts.py:55` iterated only active deployments; with every deployment `completed`, that endpoint emitted **nothing at all**. <br><br>Shared cause: *"connectivity, authorization and campaign stage were being read from whichever column happened to be nearby."* |
| **ALTERNATIVES CONSIDERED** | Keep the derived `effective_status` and rename it — **rejected**, the problem is the derivation, not the name. |
| **DECISION** | **Five concepts, five owners, no shared columns.** No entity reads another's state to answer its own question. |
| **AFTER** | Migrations 001–007 applied in ~70 minutes (21:54 → 23:03). Runtime health became a **derived projection**, never a stored column on `Node`. |
| **CURRENT STATUS** | **CURRENT.** Extended by migrations 008–014. |

**Accepted consequence, stated in advance:** *"The dashboard KPI changes value:
`active_deployments` will read 0 where it read 2, because there are genuinely
zero active deployments. **This is the bug being fixed, not a regression.**"*

The API contract was preserved so the existing frontend bundle needed no rebuild.

**Four sub-transitions landed in the same evening:**

### T5.1 Explicit measurement context (ADR-0003)

| | |
|---|---|
| **BEFORE** | Bench measurements taken during ADS1256 integration were stored **indistinguishably** from production data and flowed into building metrics, model training and anomaly detection. |
| **PROBLEM** | *"There was no way to ask 'is this reading real site data?' because nothing recorded the answer."* |
| **ALTERNATIVE CONSIDERED AND REJECTED IN REVIEW** | **Infer context from attribution** — a reading with no covering deployment is bench data. Rejected because a genuine production node whose deployment was simply never created would be **silently relabelled `bench` and vanish from every KPI with no error anywhere.** |
| **DECISION** | `energy_readings.context`, `NOT NULL`, default `production`. Taken from `nodes.measurement_context`, operator-set and authoritative. A payload may **narrow** it but never **widen** it to `production`. |
| **AFTER** | Migration 005 backfilled 123,696 rows (`m5_attribution_backup`). Exclusion is enforced **structurally** by `INV-09`, not per query. Bench data remains stored, queryable and exportable via `?context=`. |
| **CURRENT STATUS** | **CURRENT**, extended by migration 014 (`infrastructure_validation`). |

### T5.2 Timestamp-based attribution (ADR-0004)

| | |
|---|---|
| **BEFORE** | `routers/edge.py:60-68` selected the attribution deployment with `.order_by(Deployment.id.desc()).first()` — **the newest** — and stamped every measurement in the batch with it. |
| **PROBLEM** | The edge buffer holds ~19,000 rows and replays after an outage. A node buffering across a deployment change writes historical data into the new campaign's building. **Silent and permanent.** *"This was not in the original audit; it was found while verifying it."* |
| **DECISION** | Resolve **per measurement, independently**, from the measurement's own `captured_at`. Write once, at ingest. No read path re-derives attribution. Immutable at runtime via a `BEFORE UPDATE` trigger. |
| **AFTER** | The replay defect is structurally impossible. Historical data is stable under deployment edits. |
| **CURRENT STATUS** | **CURRENT.** The pre-resolver damage (§J.8) was deliberately **not** retro-fixed. |

### T5.3 Migration invariants (ADR-0005)

| | |
|---|---|
| **BEFORE** | *"No Alembic, no git repository, and schema changes had previously been made by hand with timestamped `.bak` files."* |
| **PROBLEM** | *"The failure modes that matter here do not raise exceptions. A migration that drops rows, silently rewrites a measured value, or orphans readings from their node completes successfully and reports nothing."* And: 225,000+ readings that **cannot be regenerated**. |
| **ALTERNATIVE** | Alembic — **rejected**; its autogeneration would not have caught the index-collision-on-rename problem. |
| **DECISION** | A five-step runner with online backup, invariant snapshot, transactional apply, re-check, and automatic rollback. 15 (now 16) invariants, every reading-level one **bounded by `id <= max_reading_id`** so concurrent 15 s ingestion cannot cause a false failure or mask a real loss. |
| **AFTER** | 14 migrations applied, **none rolled back**. Each retains its own restore point. Baselines and shadow reports for the riskiest steps are committed. |
| **CURRENT STATUS** | **CURRENT.** |

### T5.4 Legacy metadata declared non-authoritative (ADR-0006)

| | |
|---|---|
| **BEFORE** | Adopting timestamp attribution exposed that the deployment metadata **did not describe reality**: N001 had 25,779 rows inside its window and **75,903 (75 %) outside**; N003 had 158 inside and **123,459 (99.9 %) outside**. |
| **PROBLEM** | Under strict timestamp attribution against the declared windows, every reading N001 produced from then on would land **unattributed**. |
| **DECISION** | Three separate calls: legacy dates are **non-authoritative** (deployment 4's `end_date` → NULL, open-ended); the placeholder building is **retained and flagged** (`buildings.is_placeholder`) rather than deleted; N003's prototype data is **de-attributed, not reclassified as production** (`laboratory` for May–June, `bench` for the July bring-up). |
| **AFTER** | N001's ongoing measurement is attributed rather than stranded. Building-level analytics exclude placeholders; fleet totals still count the energy, flagged as not attributable to a real site. |
| **CURRENT STATUS** | **CURRENT.** |

**The distinction this ADR draws is subtle and thesis-worthy:** *"A placeholder
building is not the same as non-production data. N001's readings are real
measurements of a real load; what is unreliable is **the label on where they were
taken.** Treating them as non-production would discard valid data to fix a
metadata error, so `is_placeholder` is a separate axis from `context`."*

## T6 — Monitoring: from nothing, to too much, to a policy

| | |
|---|---|
| **BEFORE** | No systematic monitoring. Node health was inferred from `last_sync`. |
| **PROBLEM** | *"Is everything healthy; if not, what broke, where, since when, how bad is it, and what should I check first?"* had no answer. |
| **DECISION** | A self-contained monitoring subsystem in its **own process**, with its **own six tables**, modifying **no existing table**. |
| **AFTER (first run)** | **1,386 Telegram messages in four days.** 697 on one day, 73 in one hour. The user's verdict: it *"would destroy their trust in the channel entirely."* |
| **CURRENT STATUS** | v1.1.0, 42 rules, 2,165 messages delivered over 18 days — **an average of ~120/day across the whole period, dominated by the first four days.** |

### T6.1 The alerting policy rebuild — 2026-07-29

| | |
|---|---|
| **BEFORE** | Rules inherited `runtime_platform_settings.json` (the UI display defaults) as alert thresholds. No deployment gating, no sustain window, no hysteresis, no routing by consequence. |
| **PROBLEM** | Quantified from the actual message history: **98 % of noise from undeployed nodes** (1,288/1,312); **the 200 A default sat at N001's 94th percentile** and produced 962 messages alone; **404 of 472 alerts lasted under two minutes**. |
| **DECISION** | The four principles (§I.4), plus: derive thresholds from **physical reality**, and **never let a learned baseline exceed the physical ceiling**. |
| **AFTER** | Most rules became report-only, escalating at CRITICAL. Alerting stopped reading `runtime_platform_settings.json` entirely. |
| **CURRENT STATUS** | **CURRENT.** Guarded by sensitivity checks (§19–25 + `test_synthetic_deployment`) so it cannot go quiet by going blind. |

**The strongest single sentence in the project's engineering record:**
*"A monitoring system that went quiet because it stopped looking is worse than one
that is noisy."*

## T7 — The canonical measurement model (ADR-0007) — 2026-07-31

| | |
|---|---|
| **BEFORE** | `energy_kwh` had **two meanings over the platform's life**, and nothing in the schema recorded which: a cumulative lifetime register until 2026-07-03 15:32:39, and per-interval energy from 2026-07-25. |
| **PROBLEM** | *"Every consumer computes `current − previous`, which is correct for the first and meaningless for the second. **Dashboard KPIs are ~400× low.**"* The root cause is not the arithmetic — *"one column carried two meanings."* |
| **EVIDENCE (recorded in `measurement_eras`)** | Counter era: monotonic 17,283.82 → 26,259.24 kWh over 19 days, **0.0 % negative deltas**. Interval era: `= power_kw × 15.000/3600` to zero relative error, **51.6 % negative deltas**. |
| **DECISION** | Five canonical fields, `interval_energy_kwh` as **the** analytics quantity; `meter_energy_kwh` for reconciliation only; **`energy_source` mandatory**. Legacy `energy_kwh` resolved **per era** rather than redefined. |
| **WHY INTERVAL, NOT CUMULATIVE** | Cumulative needs reset detection, needs ordered adjacency, contributes nothing on the first reading of a window, and turns a data gap into one enormous false delta. Interval energy is **additive** — `SUM()` is the answer — and is immune to resets and gaps. |
| **AFTER** | Migration 012 added the columns and the `measurement_eras` table. |
| **CURRENT STATUS** | ⚠ **Backend-complete, edge-incomplete.** All four canonical columns are **NULL on 290,439 rows**. No collector emits them (§C.4). |

**Why `energy_source` is mandatory** — the clearest statement of the project's
epistemics: *"`interval_energy_kwh: 0.0517` is **unfalsifiable** without it. With
it, a reader knows whether the number came from a meter or from arithmetic — and
therefore what its error characteristics are."*

## T8 — Repository, CI and public release — 2026-08-04

| | |
|---|---|
| **BEFORE** | Code on a server. No git repository. Timestamped `.bak` files as version control. Two nested legacy repos for the frontend. |
| **PROBLEM** | The deployed platform could not be reproduced from any source of truth, and nothing had ever been built on a clean machine. |
| **DECISION** | One repository, published to GitHub, with the frontend's 59 commits **rewritten under a `frontend/` path prefix and merged** so `git log frontend/` still reaches 2026-06-14. |
| **AFTER** | v1.2.0. 18 documents, 12 Mermaid diagrams, 15 screenshots, six CI workflows, community health files, `pyproject.toml`/pre-commit/commitlint. **No application behaviour changed.** |
| **CURRENT STATUS** | **CURRENT.** Legacy nested repos moved to `~/energy-platform-legacy-git/` as a safety net. |

**What the first CI run exposed — VERIFIED, four classes of defect that only a
clean machine could find:**

| Defect | Detail |
|---|---|
| **Two test suites were passing vacuously** | Both fixtures predated migration 010's `activated_at`/`closed_at`. Setting only `status` meant no deployment was ever found — so `test_synthetic_deployment` read the node as having no operational deployment and every electrical rule was *correctly* suppressed. **The suite whose entire purpose is to prove monitoring did not go quiet was itself not exercising that path.** After the fix: 5 passed/6 failed → **18 passed/0 failed**; `test_smart_plugs` 52/1 → **53/0**. |
| **The suites could only run on the deployment host** | Every one hardcoded `/home/manager/energy-platform`. Paths now derive from `__file__`. |
| **Three undeclared dependencies** | `google-genai` (requirements named the *legacy* SDK `google-generativeai`, which does not provide `from google import genai`); `playwright` (imported at module load by `cfe_scraper.py`, which the router graph pulls in); `psutil` (used by the 15 server health rules). All three were present in the deployment venv, **so nothing ever failed there.** `scripts/check_requirements.py` now walks every import and fails the build on an undeclared one. |
| **Three Mermaid diagrams did not parse** | A semicolon in a sequence-diagram message is a statement separator; the text truncated mid-parse and would have rendered on GitHub as a raw code block. |

**Also in this release:** 16 commits had to be rewritten and force-pushed to
remove AI co-author trailers, invalidating the v1.2.0 tag and release draft. Three
enforcement layers now prevent recurrence.

## T9 — Node identity and ingest authentication — 2026-08-06/07

**The transition that closed the project's most-cited limitation.**

| | |
|---|---|
| **BEFORE** | `POST /api/v1/measurements/batch`, `/api/readings`, `/api/edge/heartbeat` and `/api/monitoring/heartbeat` **accepted a self-asserted `device_id`.** `nodes.auth_token_hash` existed from migration 002 but was **unused by every ingest path**. |
| **PROBLEM (empirical, not theoretical)** | On 2026-08-06 **two different producers published heartbeats as N001** — a v2.0.0 collector and a v1.0.0 agent. Root cause: *"an old collector left in a backup directory that anyone can execute, against an endpoint with no identity check."* The two producers **disagreed** on `filesystem_readonly` and `disk_percent`, so the platform's own health picture depended on which arrived last. |
| **ALTERNATIVES CONSIDERED (ADR-0002)** | Keep deployment gating and widen the accepted statuses — **rejected**, does not scale and still couples collection to administration. Per-node IP allowlist — **rejected**: *"the Pis are behind NAT on dynamic public addresses, and an allowlist authenticates a network location rather than a device."* |
| **DECISION** | Bearer token, `secrets.token_urlsafe(32)`, stored **only as SHA-256**, compared in constant time, shown **once** at issuance. Three deliberately distinct outcomes: `authenticated` / `subject` / `violation`. **A credential that authenticates as a different node than the one claimed is impersonation, not an authentication failure** — always 403, in either mode. |
| **AFTER** | Migration 013 (2026-08-06 13:46). `node_identity_violations` table. `mode: "enforce"`, `exempt_nodes: []`. **12,278 violations recorded**, all correct refusals. |
| **CURRENT STATUS** | **CURRENT and ENFORCED** — and **contradicted by five repository documents** (§E.5, C-02). |

**The design lesson, VERIFIED in the module docstring:** *"Identity is a
credential the node presents, never an attribute of the request. Specifically
**never the source address**: three nodes here share two public NAT addresses,
those addresses change, and on 2026-08-06 two different producers published as
N001 from one address. Anything derived from the network path is a hint, not an
identity."*

**A follow-on bug worth recording:** `exempt_nodes: ["N003"]` was honoured only by
`/api/monitoring/heartbeat`; both ingest paths passed `mode` through as a bare
boolean and dropped the exemption — so **N003 looked exempt while all 5,958 of its
uploads took 401**. The fix removed the `enforcing: bool` parameter entirely, so
the policy cannot come apart at a call site. Regression tests compare routes
*against each other*.

**Completed 2026-08-13:** N003's credential installed; it now authenticates and
takes **403** (`registered`, `may_upload=0`) — correct — and reads `online` again.
Its ~7,200 buffered rows are retained.

## T10 — Fleet convergence — 2026-08-07

| | |
|---|---|
| **BEFORE** | N002's collector was **12 days behind** N001's and lacked the canonical heartbeat call entirely (`grep -c '_hb_heartbeat.publish'` → N001: 1, N002: 0). N002 produced **zero** v2.0.0 beats; its "Heartbeat OK" lines were the *legacy* 3-field post. |
| **PROBLEM** | The simplification audit expected `energy-node-heartbeat.service` on N002 to be dead duplication. **It was the opposite** — it was N002's *only* canonical heartbeat source. **Deleting the "duplicate" would have blinded N002's monitoring.** |
| **DECISION** | Upgrade the collector first (D2), verify, *then* retire the legacy agent (D1). Make the collector **node-agnostic** — the startup banner changed from a literal `N001` to `CONFIG["NODE_ID"]`, which is what makes a fleet-wide checksum meaningful. |
| **AFTER** | One byte-identical collector, SHA-256 `d9cc6138c8be60b273615d13`, on both Pi 5 nodes. **Buffer preservation proved**: 5,660 → 5,671 pending, 34,357 discarded unchanged, total 40,017 → 40,028 — growth only, nothing discarded by the restart. Legacy unit disabled, files **retained for rollback** until the soak completes. |
| **CURRENT STATUS** | **CURRENT.** N003 remains unconverged and is explicitly out of scope for the package. |

**The audit's own headline conclusion:** *"The debt is not a redundant service,
it is **collector version drift between two nodes that should be identical**."*

## T11 — Node hardening, networking and recovery — 2026-08-10/11

| | |
|---|---|
| **BEFORE** | *"The node already has most of a v3 architecture installed — `netd` and a `hardening` package. **The gap is that it is unwired and switched off, not missing.**"* Every recovery layer was `0`; `energy-node-verify` ran daily, exited 1 when degraded, and **no unit consumed the result** — *"detection wired to a dead end."* |
| **PROBLEM (empirical)** | Two distinct field failure modes, distinguished by RTC state at next boot: <br>• **2026-07-27** — RTC came back at epoch (**true power loss**); the node booted unattended. <br>• **2026-07-23 (23 h)** and **2026-08-01 (43 h 37 m)** — RTC **retained correct time**, so the board stayed powered while the SoC was held off (**brownout latch**). Both needed a human. <br>The **internal watchdog was active during the 2026-08-01 failure and could not help** — its counter is inside the SoC, which had no power. The UPS wake keys off power *returning*; power never left. |
| **DECISION** | Build a Recovery Manager as a **pure state machine** first (commit `1dc3df5`), then wrap it in probes, a ledger and a daemon (`159888e`). Policy: service remedy first → reboot (max 3 per 30 min) → **SAFE MODE**, which retries forever and may reboot once per 6 h. Vendor the node packages into git (`66c59a2`) — *"the packages previously existed ONLY on the nodes."* |
| **AFTER** | `make test-node` runs **42 hermetic tests**. SAFE MODE proven end-to-end on a live node (`7a32760`), after three reporting defects found in Stage B were corrected (`5164d9c`). Boot progression persists across reboots (`eadb82d`). A dead sensor no longer escalates to a reboot (`0fe8d67`). |
| **CURRENT STATUS** | **CURRENT on N002 only. N001 is untouched.** The 11-experiment validation plan (V1–V11) is **written and entirely unexecuted.** |

**The reasoning that gates the remaining work** — DOCUMENTED,
`recovery-validation.md`: *"only a mechanism with its own power domain (external
watchdog, relay) or a firmware-level timer that survives the latch (RTC wake) can
close the remaining gap. Everything else shortens outages it was already able to
shorten."*

**Two traps this work uncovered, both worth preserving:**

1. **`SENSOR_KIND` blank means auto-detect**, and `sensors.discover()` prefers
   whichever source is *reachable*. When N002's Shelly died for two hours,
   discovery fell through to the smart plugs and reported the sensor **PASS**
   while the primary meter was dead.
2. **`doctor.check_heartbeat` asks the *backend*** whether it has seen the node,
   so it reports FAIL during a backend outage. *"Anything treating that as a local
   fault will reboot a healthy node over someone else's outage."*

## T12 — The custom ADS1256 measurement architecture (parallel line)

| | |
|---|---|
| **BEFORE** | All measurement came from a commercial meter. The instrument was a black box: its calibration, sampling and internal processing were the vendor's. |
| **PROBLEM (as an engineering/research question)** | Whether a **fully owned** acquisition chain — sensor → ADC → sampling → DSP → measurement — could be built on a Raspberry Pi at a cost and quality that justify it. |
| **DECISION** | Build a layered acquisition stack on N003: `drivers/` (register-level ADS1256 over SPI) → `acquisition/` (per-phase samplers) → `engine/` (measurement assembly) → `processing/` (DC removal, RMS, power, PF), selected at runtime by a `SOURCE` environment variable through a `sources/` package. **Two ADS1256 chips** — one for voltage, one for current — so V and I have independent converters. |
| **AFTER** | The stack exists and runs. Voltage channels were calibrated per phase (`VOLTAGE_SCALE` = 132.3452 / 130.4466 / 130.4163). 2,500 samples per phase per quantity per 15 s cycle. |
| **CURRENT STATUS** | ⚠ **EXPERIMENTAL and currently non-functional.** Both ADS1256 chips are **electrically dead** since ~2026-07-26 (STATUS reads `0x00`, writes do not stick, raw codes constant 0). Current channels are **uncalibrated** (`CURRENT_SCALE = 1.0`). Power factor is computed from **non-simultaneous** V and I arrays. Frequency is **hardcoded 60.0**. The code is **not in the repository**. |

**Chronology, VERIFIED from file mtimes on N003:**

| Date | Artefact | Meaning |
|---|---|---|
| 2026-07-24 17:16 | `poller.py.before_ads_20260724_171626` | The pre-ADS Shelly poller |
| 2026-07-24 17:26 / 17:27 | `poller.py.ads_backup_20260724_172613`, `…172701` | Two ADS versions saved minutes apart |
| 2026-07-24 17:48 | `poller.py.before-auth-20260813_080206` (mtime 07-24) | The version authentication was added to |
| 2026-08-13 08:02 | `poller.py` (current, root-owned) | Authentication added |

The `bench` context rows (2026-07-24 23:28 → 2026-07-26 22:39, avg voltage
**128.64 V**) are the **only period in which the ADS1256 stack demonstrably
produced live signal.** Everything after 2026-07-26 reads exactly zero.

## T13 — Deployment lifecycle maturation — 2026-07-30 → 2026-08-13

| | |
|---|---|
| **BEFORE** | Deployments existed but had no exclusivity constraint, no operational timestamps distinct from declared dates, and no integrity protections. |
| **PROBLEM** | *Declared* dates (`start_date`/`end_date`) proved unreliable (ADR-0006), and nothing distinguished "the operator says this campaign runs 14th–21st" from "this campaign was actually measuring between these two instants." |
| **DECISION** | Three migrations in 16 minutes on 2026-07-30: **009** deployment status exclusivity; **010** `activated_at` / `closed_at` operational timestamps (Python migration); **011** deployment integrity protections. |
| **AFTER** | Attribution matches on `activated_at`/`closed_at`, not the declared dates. `is_exclusive` prevents two concurrent operational deployments on one node. |
| **CURRENT STATUS** | **CURRENT**, plus the 2026-08-13 fix making `deployment_ops` maintain `nodes.measurement_context` (§J.5). |

---

# PHASE 4 — ENGINEERING DECISIONS

**Alternatives are listed only where there is documentary evidence they were
actually considered.** Where a decision has no recorded alternative, that is
stated rather than invented.

---

## D-01 · Raspberry Pi as the edge platform

| | |
|---|---|
| **PROBLEM** | Need a programmable, network-capable, cheap device that can sit at a panel, buffer locally, and be managed remotely. |
| **ALTERNATIVES CONSIDERED** | **No documented alternative.** No ADR or document records an evaluation of a microcontroller, industrial gateway or commercial data logger. → **Q-01.** |
| **CHOSEN APPROACH** | Raspberry Pi 3 B+ and Pi 5, Debian 13, Python 3.13, systemd. |
| **TECHNICAL REASON** | A full Linux userspace gives SQLite (a real transactional buffer), systemd (restart policy, ordering, journald), NetworkManager (the AP-fallback design), and Python — none of which a microcontroller offers. |
| **TRADEOFF** | Power sensitivity. `get_throttled = 0x50000` on **both** Pi 5 nodes means undervoltage and throttling **have occurred**. The two longest outages (23 h, 43 h 37 m) were **brownout latches** the SoC could not self-recover from. SD-card wear is the most common hardware failure, and undervoltage is upstream of most of it. |
| **EVIDENCE** | `docs/Fleet-Manifest.md`; `edge/node/hardening/docs/recovery-validation.md`; `docs/Hardware.md` failure-mode table. |
| **CURRENT STATUS** | **CURRENT.** The deliberate mixed fleet (Pi 3B+ and Pi 5) is treated as a feature — *"the platform is built to tolerate a heterogeneous fleet rather than to assume one"* — and the Energy Node Package's compatibility matrix makes degradation explicit rather than silent. |

## D-02 · Shelly Pro 3EM as the production meter

| | |
|---|---|
| **PROBLEM** | Measure three-phase active power, current, voltage, power factor and frequency at a campus panel, accurately enough for cost attribution. |
| **ALTERNATIVES CONSIDERED** | The **custom ADS1256 chain** — built, on N003 (D-03). No document records evaluating other commercial meters. |
| **CHOSEN APPROACH** | Shelly Pro 3EM (N001, 120 A CT) and Pro 3EM 400 A (N002), read over **Gen2 HTTP RPC** (`/rpc/EM.GetStatus?id=0`) on a **private Ethernet segment** `192.168.50.0/24`. |
| **TECHNICAL REASON** | The meter performs the analogue work, the calibration and the standards compliance. The Pi becomes a **transport, buffering and identity** device. The private segment isolates the meter from campus Wi-Fi and carries no default route. |
| **TRADEOFF** | The measurement chain becomes a **black box**. The platform cannot state its own uncertainty, cannot recalibrate, and inherits whatever the vendor's firmware does. It also means the project's headline "custom instrumentation" claim applies only to N003. |
| **EVIDENCE** | `node.env` on N002 (VERIFIED); `collector.py` `SHELLY_EM_URL`; `docs/Fleet-Manifest.md`; `nodes.hardware_kind = 'shelly'`. |
| **CURRENT STATUS** | **CURRENT.** It is the source of essentially all usable data. |

## D-03 · Custom ADS1256 acquisition chain

| | |
|---|---|
| **PROBLEM** | Own the measurement chain end to end: sensor → ADC → sampling → DSP → measurement, rather than trusting a vendor black box. |
| **ALTERNATIVES CONSIDERED** | Continuing with the Shelly only (D-02) — the two lines ran **in parallel**, which is itself the answer. |
| **CHOSEN APPROACH** | **Two ADS1256** 24-bit ΔΣ converters on `spidev0.0` (voltage) and `spidev0.1` (current), DRATE `0xD0`, VREF 2.5 V, manual GPIO chip-select, differential MUX pairs AIN0/1, AIN2/3, AIN4/5 per phase, **2,500 samples per phase per quantity**, DC removal then RMS in Python. |
| **TECHNICAL REASON** | *"Campus panels run at up to a few hundred amps, but the interesting behaviour — overnight base load, a single failed HVAC compressor — sits far down the range. An 8- or 10-bit converter quantises those away."* Two chips let V and I be sampled on independent converters. |
| **TRADEOFF** | *"The front end must be brought up carefully, and a mis-scaled channel reads as a plausible small number rather than as an obvious error."* Realised in full: the current channels are uncalibrated, PF is not physically meaningful, frequency is a literal, and a **dead board is stored as a perfectly plausible `0.0`** with no error anywhere in the stack. |
| **EVIDENCE** | `drivers/ads1256.py`, `acquisition/*.py`, `engine/measurement.py`, `processing/electrical.py` — all VERIFIED by direct read on N003, 2026-08-13. `docs/Hardware.md` "Why a 24-bit ADC". |
| **CURRENT STATUS** | **EXPERIMENTAL, currently non-functional, not in the repository.** |

## D-04 · Temporary deployments rather than permanent instrumentation

**The project's defining architectural idea.**

| | |
|---|---|
| **PROBLEM** | A campus has many buildings and the project has three nodes. Permanent instrumentation of every building is not affordable; but a reading with no record of *where the instrument was* is worthless. |
| **ALTERNATIVES CONSIDERED** | The **implicit prior model** — attribute readings to whatever building the node currently points at. Rejected by ADR-0004 once the replay defect was found. |
| **CHOSEN APPROACH** | A first-class **`deployment`** entity: node × building × panel × time window, with a five-state lifecycle whose semantics live in **columns of a lookup table** (`allows_attribution`, `is_operational`, `is_terminal`, `is_exclusive`), so a new state is one `INSERT` rather than a constraint rewrite. |
| **TECHNICAL REASON** | It makes instrumentation **portable without making data ambiguous**. `completed` still attributes its own history, so ending a campaign does not orphan what it measured. There is **no transition out of `completed`** because reopening would retroactively change attribution. |
| **TRADEOFF** | Every reading now depends on metadata an operator must enter correctly, and **legacy metadata proved wrong** (ADR-0006: 75 % / 99.9 % of readings outside their declared windows). It also introduces a second lifecycle model that monitoring must defer to rather than duplicate. |
| **EVIDENCE** | ADR-0001, ADR-0004, ADR-0006; `deployment_statuses` (VERIFIED); migrations 003, 009, 010, 011; deployment 7's operator note. |
| **CURRENT STATUS** | **CURRENT.** Deployment 7 (2026-08-13 → 08-22) is the model in active use for its intended purpose. |

## D-05 · Local SQLite buffering, written before upload

| | |
|---|---|
| **PROBLEM** | A campus network and a single application server both fail. Measurements are not reproducible. |
| **ALTERNATIVES CONSIDERED** | A **message broker** — explicitly rejected: *"the edge buffer already provides durability and backpressure; a broker would duplicate it."* |
| **CHOSEN APPROACH** | SQLite (WAL) on the node, written at capture time, drained by an independent 60 s loop, `sync_status` 0/1/2, 7-day retention after confirmed send. |
| **TECHNICAL REASON** | The ordering is the whole point: **buffer first, upload second** turns an outage into a delay. It is also what makes migrations safe — *"ingestion may block for minutes during a migration with no consequence beyond a temporarily deeper buffer."* |
| **TRADEOFF** | Seven days is a hard ceiling — beyond it the oldest data is genuinely gone. And the drain loop has a **head-of-line block**: one permanently rejected row halts the queue forever (VERIFIED on N002, 23,517 rows). |
| **EVIDENCE** | `docs/Collector.md`; `docs/Architecture.md` §2.2; live buffer counts on N002/N003. |
| **CURRENT STATUS** | **CURRENT** on all three nodes. The head-of-line block is an **open defect**. |

## D-06 · Synchronisation architecture — outbound-only, two loops

| | |
|---|---|
| **PROBLEM** | Nodes must work inside buildings whose networks the project does not control. |
| **ALTERNATIVES CONSIDERED** | **Central network scanning** for smart plugs — explicitly rejected: *"a central scanner would need inbound reach into every site, and would forfeit exactly this property."* **Per-node IP allowlist** for authentication — rejected (ADR-0002): NAT, dynamic addresses, and it authenticates a location not a device. |
| **CHOSEN APPROACH** | **Every connection is initiated outbound from the node.** No inbound port is forwarded. Discovery of plugs runs on the Pi. Sampling and syncing are separate loops so sync never blocks sampling. |
| **TECHNICAL REASON** | *"A node dropped onto an ordinary consumer network — a building's existing Wi-Fi, a router nobody wants to reconfigure — works with zero network changes."* |
| **TRADEOFF** | Operator access becomes a **separate problem** with its own solution stack (public NAT addresses, Tailscale, maintenance AP, tty1 console) — and those addresses move, which has cost real time during incidents. |
| **EVIDENCE** | `docs/Networking.md`; `docs/Smart-Plugs.md`; VERIFIED 2026-08-13 — N001 unreachable on both known addresses. |
| **CURRENT STATUS** | **CURRENT.** |

## D-07 · 15-second sampling interval

| | |
|---|---|
| **PROBLEM** | Choose a cadence that resolves operationally meaningful load changes without producing unmanageable data volume. |
| **ALTERNATIVES CONSIDERED** | **None documented.** No file records why 15 s rather than 5 s, 30 s or 60 s. → **Q-02.** |
| **CHOSEN APPROACH** | `POLL_INTERVAL = 15` s sample, `SYNC_INTERVAL = 60` s sync, `HEARTBEAT_INTERVAL = 60` s. Identical on all three nodes. |
| **TECHNICAL REASON (inferable, not stated)** | 15 s gives 5,760 samples/node/day and 240 per hourly aggregate bucket. It resolves HVAC cycling, which dominates campus load in Colima. |
| **TRADEOFF** | 5,760 rows/node/day → ~290k rows and 311 MB in three months from effectively one instrumented node. It also sets the 7-day buffer ceiling in absolute row terms (~40k rows). And **energy is integrated using the nominal 15 s, not the elapsed time** — a defect noted in the architecture review. |
| **EVIDENCE** | `node.env` (VERIFIED); `measurement_eras` records `power_kw × 15.000/3600` to zero relative error. |
| **CURRENT STATUS** | **CURRENT**, never changed. |

## D-08 · FastAPI + gunicorn `-w 1`

| | |
|---|---|
| **PROBLEM** | Serve an HTTP API for ingestion, dashboards, reports and monitoring, on one modest server. |
| **ALTERNATIVES CONSIDERED** | **None documented** for the framework. The `-w 1` choice has a documented rationale. |
| **CHOSEN APPROACH** | FastAPI under `gunicorn -k uvicorn.workers.UvicornWorker -w 1 --timeout 120`, port 8010. |
| **TECHNICAL REASON** | *"Typed request models and a generated OpenAPI schema, which is what makes `API.md` verifiable rather than aspirational."* And: **`-w 1` is a database constraint expressed in the process model** — SQLite has one writer. |
| **TRADEOFF** | No horizontal scaling and no failover on one process. Raising the worker count *"will produce `database is locked` under load."* A single application server means a host loss stops ingestion — absorbed by node buffers for up to 7 days. |
| **EVIDENCE** | `ps aux` (VERIFIED); `docs/Architecture.md` §5; `docs/Deployment.md`. |
| **CURRENT STATUS** | **CURRENT.** |

## D-09 · SQLite in WAL mode, deliberately

| | |
|---|---|
| **PROBLEM** | Store ~300k time-series rows plus organisational metadata, queried by dashboards, reports and monitoring. |
| **ALTERNATIVES CONSIDERED** | **PostgreSQL** — the documentation addresses it directly: *"This is a considered choice, not a placeholder for PostgreSQL."* |
| **CHOSEN APPROACH** | SQLite, WAL journal mode, single file at `backend/energy_platform.db`. |
| **TECHNICAL REASON** | One writer, many readers is *"exactly the WAL sweet spot"*; 290k rows / 311 MB is well inside SQLite's range; **no second process to operate, monitor, back up or fail independently.** |
| **TRADEOFF** | Concurrent writes serialise. Scaling past one application server means a real migration. And a **sharp, non-obvious operational hazard**: `cp`/`rsync`/`tar` produce a **silently corrupt backup** that restores without error and is missing recent transactions. |
| **EVIDENCE** | `docs/Database.md`; `docs/Architecture.md` §2.3; ADR-0005; live file 311.2 MB + 4.4 MB WAL. |
| **CURRENT STATUS** | **CURRENT.** |

## D-10 · Hand-rolled migrations instead of Alembic

| | |
|---|---|
| **PROBLEM** | Evolve the schema of a database holding **225,000+ readings that cannot be regenerated**, under continuous 15 s ingestion, with no git repository at the time. |
| **ALTERNATIVES CONSIDERED** | **Alembic** — explicitly rejected. |
| **CHOSEN APPROACH** | `migrations/runner.py`: online backup → invariant snapshot → apply in one transaction → re-check → record or auto-roll-back. Explicit `.up.sql`/`.down.sql` (or `.py` for rebuilds). Shadow runs against a copy. 16 invariants. |
| **TECHNICAL REASON** | *"Alembic's autogeneration would not have caught that renaming a table carries its indexes under their old names — which collides mid-rebuild of a 255k-row table."* And the failure modes that matter **do not raise exceptions**: *"A migration that drops rows, silently rewrites a measured value, or orphans readings from their node completes successfully and reports nothing."* |
| **TRADEOFF** | Every migration must be written twice (up and down) and rehearsed up → down → up on a throwaway copy. Higher authoring cost per change. |
| **EVIDENCE** | ADR-0005; `backend/docs/ARCHITECTURE.md` §11–12; `schema_migrations` — **14 applied, 0 rolled back** (VERIFIED); `m8-production-cutover-runbook.md` (21 KB). |
| **CURRENT STATUS** | **CURRENT.** |

## D-11 · The monitoring scheduler as a separate process

| | |
|---|---|
| **PROBLEM** | Evaluate health rules on a schedule and deliver alerts, without the monitoring system sharing the fate of the thing it monitors. |
| **ALTERNATIVES CONSIDERED** | **An in-process background task** — rejected on three concrete grounds. |
| **CHOSEN APPROACH** | A separate OS process under `flock`, started by `run-monitoring.sh` plus a `@reboot` crontab entry. |
| **TECHNICAL REASON** | (1) An in-process scheduler would **multiply alerts** the moment gunicorn moved off `-w 1` — every worker evaluating every rule. (2) It **could not report that the backend crashed**, because it would die with it. (3) A backend `SIGHUP` must not restart monitoring. |
| **TRADEOFF** | *"A second unit to operate and a second thing that can be down — which is why the scheduler monitors itself and reports its own downtime."* Also: the proper systemd unit **exists but needs root to install**, so it currently runs from cron. |
| **EVIDENCE** | `docs/Architecture.md` §2.1; `docs/Monitoring.md`; `ps aux` (VERIFIED, running since 2026-08-07). |
| **CURRENT STATUS** | **CURRENT.** |

## D-12 · Alerting thresholds from physical reality, not display defaults

| | |
|---|---|
| **PROBLEM** | The first production run sent **1,386 Telegram messages in four days**. |
| **ALTERNATIVES CONSIDERED** | The status quo — inheriting `runtime_platform_settings.json` (the UI display defaults). **Rejected with quantified evidence.** |
| **CHOSEN APPROACH** | Threshold chain: **panel/breaker rating → node CT rating → learned baseline (operational deployments only, min 500 samples) → conservative fallback**, with a hard rule that a learned baseline may never exceed the physical ceiling. Plus deployment gating, sustain windows, hysteresis, and routing by consequence. |
| **TECHNICAL REASON** | *"Colouring a chart and paging a human are different decisions."* The 200 A display default sat at N001's **94th percentile** and produced 962 messages alone. A learned baseline above the physical ceiling *"learns an overload as normal and stops reporting it."* |
| **TRADEOFF** | The chain depends on data an operator must enter — and ⚠ **every physical-rating column is currently NULL** (§I.3), so in practice thresholds resolve to a learned baseline or the fallback. The design is correct; the inputs are missing. |
| **EVIDENCE** | `docs/Monitoring.md`; `CHANGELOG.md` v1.1.0; live `nodes`/`deployments` rating columns all NULL (VERIFIED). |
| **CURRENT STATUS** | **CURRENT.** |

## D-13 · No hardware-specific logic in the backend

| | |
|---|---|
| **PROBLEM** | The fleet is heterogeneous and will change. A meter-specific branch in an analytics service is permanent. |
| **ALTERNATIVES CONSIDERED** | **None documented** — it is stated as a standing constraint rather than a choice between options. |
| **CHOSEN APPROACH** | A collector translates its device into the **canonical measurement model**; the platform stores and interprets that model and nothing else. Adding a meter type is a collector change plus **at most one row in `measurement_eras`.** |
| **TECHNICAL REASON** | It is what makes the fleet's heterogeneity survivable, and it is enforced by `tests/test_collector.py`, which *"tests the contract, not a device."* |
| **TRADEOFF** | It puts the burden on the collector — and **the collectors are the one component not under version control**. It also means the platform cannot compensate for a device's known error characteristics. |
| **EVIDENCE** | `docs/Architecture.md` §2.4; `backend/docs/collector-contract.md`; `docs/Collector.md` §"Adding a new meter type" — *"Change nothing in `app/services/`. If you find yourself needing to, the translation belongs in the collector and the design has been violated."* |
| **CURRENT STATUS** | **CURRENT** as a rule; ⚠ the contract it depends on is **not yet emitted by any collector** (§C.4). |

## D-14 · `energy_source` mandatory; `measurement_eras` instead of redefinition

| | |
|---|---|
| **PROBLEM** | `energy_kwh` silently changed meaning between two collector versions; dashboard KPIs were **~400× low**. |
| **ALTERNATIVES CONSIDERED** | **Redefining the column** to the new meaning — rejected, because *"historical data was stored under its current meaning and cannot be re-collected."* **Cumulative counters** as the canonical quantity — rejected, with four specific weaknesses (reset detection, ordered adjacency, first-reading-of-window, gap-as-false-delta). |
| **CHOSEN APPROACH** | `interval_energy_kwh` as **the** analytics quantity, `meter_energy_kwh` for reconciliation only, and **`energy_source` mandatory**. The legacy column's meaning is resolved **per era** from a `measurement_eras` table that records the evidence for each era's classification. |
| **TECHNICAL REASON** | *"`interval_energy_kwh: 0.0517` is unfalsifiable on its own. With it, a reader knows whether the number came from a meter or from arithmetic."* Interval energy is **additive** and immune to resets and gaps. |
| **TRADEOFF** | Every reader must consult the era table for legacy rows. And **the contract is currently aspirational**: all four canonical columns are NULL on 290,439 rows. |
| **EVIDENCE** | ADR-0007; `measurement_eras` (VERIFIED, with the 0.0 % / 51.6 % negative-delta evidence in the rows); `SELECT energy_source, COUNT(*)` → `(None, 290439)`. |
| **CURRENT STATUS** | **Backend CURRENT, edge PLANNED.** |

## D-15 · Context declared explicitly, never inferred

| | |
|---|---|
| **PROBLEM** | Bench data taken during ADS1256 bring-up flowed into building metrics, model training and anomaly detection, indistinguishable from production. |
| **ALTERNATIVES CONSIDERED** | **Infer context from attribution** (no covering deployment ⇒ bench). Written into an earlier draft and **rejected during review.** Also: **delete** non-production data — rejected on the standing rule *"never delete historical data."* |
| **CHOSEN APPROACH** | `energy_readings.context`, `NOT NULL`, from `nodes.measurement_context`. A payload may **narrow** but never **widen** to `production`. Seven contexts with behaviour-bearing columns. |
| **TECHNICAL REASON** | The rejected inference is unsafe in exactly one case, and it is the important one: a genuine production node whose deployment was never created would be **silently relabelled `bench` and vanish from every KPI with no error anywhere.** Making context explicit turns that into an **alarm**. |
| **TRADEOFF** | Someone must set it correctly, and **nothing wrote that column until 2026-08-13** — which is precisely how deployment 7 activated and attributed nothing. |
| **EVIDENCE** | ADR-0003; `measurement_contexts` (VERIFIED, 7 rows); `INV-09`; the 2026-08-13 `deployment_ops` fix. |
| **CURRENT STATUS** | **CURRENT.** |

## D-16 · Attribution resolved per row by `captured_at`, and immutable

| | |
|---|---|
| **PROBLEM** | Batch attribution to the newest deployment silently misfiles replayed buffer data. |
| **ALTERNATIVES CONSIDERED** | **Per-batch attribution** (the status quo). **Re-deriving attribution on read** (partly in place) — rejected because *"editing or re-dating a deployment retroactively changed what historical readings appeared to mean."* **Absolute immutability** — rejected because *"taken literally and without exception, immutability would permanently freeze the very misattribution this redesign exists to correct."* |
| **CHOSEN APPROACH** | Resolve per row from its own `captured_at`; write once at ingest; enforce with a `BEFORE UPDATE` trigger; scope immutability as *"immutable at runtime; correctable only by supervised migration."* Measured values are immutable **with no waiver**. |
| **TECHNICAL REASON** | *"With a ~19k-row buffer replaying after an outage, this is not a corner case."* And ambiguity is a **result**, not a tiebreak — overlapping windows produce `MULTIPLE_MATCHES` and attribute nothing. |
| **TRADEOFF** | The resolver reads the node's *current* declared context, so it is **right for new readings and wrong for history** — *"it must never be run as a backfill over stored rows."* Correcting historical attribution requires a supervised migration. |
| **EVIDENCE** | ADR-0004; `app/services/attribution.py`; the reason-code table; `INV-02`, `INV-03`, `INV-15`. |
| **CURRENT STATUS** | **CURRENT.** |

## D-17 · Uploads authorised by commissioning, not deployment lifecycle

| | |
|---|---|
| **PROBLEM** | Ingestion was gated on `Deployment.status`. **Completing a deployment stopped uploads** — an administrative action silently destroying field data. |
| **ALTERNATIVES CONSIDERED** | **Widen the accepted statuses to `("active","completed")`** — this was the actual hotfix in production; rejected as a design because *"every new lifecycle state requires revisiting the filter, and it still couples data collection to campaign administration."* |
| **CHOSEN APPROACH** | Three ordered questions — authenticate, authorize (`may_upload`), attribute. **Once authenticated and authorized, data is always stored and never rejected.** A reading that cannot be attributed is stored **unattributed**. |
| **TECHNICAL REASON** | *"Rejection is no longer used to express 'this data does not belong to a campaign'. That distinction moves to `context`, which preserves the evidence instead of destroying it."* |
| **TRADEOFF** | A `registered` node's uploads are refused **403** and its buffer grows without bound — VERIFIED on N002 (~5,700 rows/day, 23,517 at audit). The audit's verdict: *"Do not add an alert — the node is deliberately unmonitored."* |
| **EVIDENCE** | ADR-0002; `app/services/ingest_gate.py`; `node_identity_violations` (VERIFIED). |
| **CURRENT STATUS** | **CURRENT.** |

## D-18 · Node identity as a presented credential, never a network attribute

| | |
|---|---|
| **PROBLEM** | On 2026-08-06, **two producers published heartbeats as N001 from the same address**, disagreeing about the node's health. |
| **ALTERNATIVES CONSIDERED** | **Per-node IP allowlist** — rejected (ADR-0002): NAT, dynamic addresses, and *"an allowlist authenticates a network location rather than a device."* **`commission_state` alone** — rejected: *"Without step 1 the identity is self-asserted, so the flag gates nothing."* |
| **CHOSEN APPROACH** | Bearer token (`Authorization: Bearer` or `X-Node-Token`), `secrets.token_urlsafe(32)`, stored **only as SHA-256**, constant-time comparison, shown **once**. Three distinct outcomes; a mismatch between credential subject and claimed node is **impersonation → 403, in either mode.** |
| **TECHNICAL REASON** | *"Anything derived from the network path is a hint, not an identity."* A stolen database yields no usable credential. |
| **TRADEOFF** | Token distribution requires visiting every node; N003 was not credentialed until 2026-08-13, taking **5,985 × 401** in the interim. Rotation is immediate and irreversible — the previous token stops working the moment it commits. |
| **EVIDENCE** | `app/db/node_auth.py`; migration 013; `monitoring/evidence/identity-collision-20260806_134531.md`; `node_identity_violations` (VERIFIED). |
| **CURRENT STATUS** | **CURRENT, `mode: enforce`, no exemptions.** |

## D-19 · Smart plugs as accessories, never nodes

| | |
|---|---|
| **PROBLEM** | Panel-level measurement cannot say *which outlet*. But plug readings and panel readings measure **different things** and must never be summed. |
| **ALTERNATIVES CONSIDERED** | **Treating plugs as Energy Nodes** — rejected structurally. **Central network scanning** — rejected: it would forfeit the outbound-only property. **Last-writer-wins ownership** — this was v1.1.0's behaviour and was **replaced** in v1.2.0 by explicit first-claim ownership. |
| **CHOSEN APPROACH** | Separate tables (`smart_plugs`, `smart_plug_readings`), a **separate SQLite buffer file** on the Pi, a separate API prefix. Identity is the **MAC**. RPC is **read-only**. Discovery only on the Pi. |
| **TECHNICAL REASON** | *"Keeping them in separate tables makes that mistake structurally impossible rather than a rule someone has to remember."* And *"a plug subsystem fault cannot corrupt or block the measurement path that matters most."* |
| **TRADEOFF** | Plugs are on Wi-Fi and drop out more than wired nodes, so `smart_plug.*` rules are report-only. And three of four plugs remain **unassigned** to any building (VERIFIED) — their 152k readings are collected but not attributed. |
| **EVIDENCE** | `docs/Smart-Plugs.md`; `edge/CHANGELOG.md` 1.2.0; live `smart_plugs` table. |
| **CURRENT STATUS** | **CURRENT.** |

## D-20 · The frontend: inline styles, polling, no state library

| | |
|---|---|
| **PROBLEM** | Build a 13-screen operational dashboard with one developer and no runtime to operate in production. |
| **ALTERNATIVES CONSIDERED** | **None documented** for the styling or state choices; the trade-off is acknowledged retrospectively. |
| **CHOSEN APPROACH** | React 19 + Vite + TypeScript, static build served by a plain Python static server. **No CSS framework** — inline `style={{}}` driven by token objects. **No Redux, no React Query, no WebSocket** — local state plus interval polling (3 s live, 30 s dashboards). |
| **TECHNICAL REASON** | *"For a dashboard whose underlying data changes every 15 seconds at the source, interval polling against a single client module is sufficient and removes an entire category of cache-invalidation bugs."* And deployment becomes `npm run build` — *"a completed build **is** the release."* |
| **TRADEOFF** | Acknowledged in the documentation: *"it concentrates a great deal of the UI in `App.tsx`"* — **2,532 lines**, 12 of 13 screens unextracted, 36 pre-existing ESLint findings, and **no test suite at all**. |
| **EVIDENCE** | `docs/Frontend.md`; `wc -l src/App.tsx` = 2532 (VERIFIED). |
| **CURRENT STATUS** | **CURRENT.** Extracting screens the way `components/smartplugs/` already is would be *"the single highest-value refactor in the frontend."* |

## D-21 · Networking: one mutator, one published fact, fail-open

| | |
|---|---|
| **PROBLEM** | *"A node is never unreachable"* — not after a wrong Wi-Fi password, not after the campus SSID changes, not after the router is replaced, not after a technician moves the node. Recovery must never require removing the SD card or attaching a serial console. |
| **ALTERNATIVES CONSIDERED** | **hostapd + dnsmasq** — avoided in favour of NetworkManager `ap` mode with `ipv4.method=shared`, *"no hostapd or dnsmasq config to maintain."* **A captive portal** — explicitly rejected: `/generate_204` is answered honestly *"so the browser opens normally instead of forcing a sign-in sheet."* **`192.168.50.0/24` for the AP** — rejected, it is the Shelly sensor segment. |
| **CHOSEN APPROACH** | `energy-node-netd` as **the only component that mutates network state**; portal and console are unprivileged clients over a control socket. A **pure, I/O-free decision layer** where time arrives as a parameter. **One published fact** — `{"network": "available"}` — and the collector reads only that. |
| **TECHNICAL REASON** | *"The collector never learns how connectivity is achieved… so the networking subsystem can be redesigned without touching collector code."* And **fail-open**: if the state file is missing or stale, `network_available()` returns `True`, because *"a collector that stopped trying because the monitor died would turn a networking fault into a data-loss fault."* |
| **TRADEOFF** | The portal is **unauthenticated by design** — *"a technician at a dead node must not need a password"* — so the trust boundary is *where you connect from*, not who you are. |
| **EVIDENCE** | `edge/node/net/README.md`; **46 unit tests**, re-run by the installer on each node. |
| **CURRENT STATUS** | **CURRENT** on all three nodes. ⚠ N003 additionally runs a **legacy second mutator** (`energy-node-wifi-fallback`), violating the one-mutator rule. |

## D-22 · Recovery: layered, cheapest first, and unvalidated mechanisms ship disabled

| | |
|---|---|
| **PROBLEM** | Two field outages of 23 h and 43 h 37 m, both requiring a human, both **brownout latches** the internal watchdog could not address. |
| **ALTERNATIVES CONSIDERED** | Documented in the V1–V11 plan as **competing mechanisms with an explicit decision point**: internal watchdog (V1, proven insufficient for the latch), collector self-heal (V2), reboot escalation (V3), UPS auto-boot (V4 — *"will NOT recover the Aug 1 failure"*), **RTC wake (V5 — "the highest-value experiment")**, GPIO wake (V6 — blocked, *"a halted Pi cannot pull its own wake pin"*), relay power cycle (V10), external watchdog (V11 — *"the strongest option"*, because its counter lives **outside** the SoC). |
| **CHOSEN APPROACH** | Recovery Manager with policy: service remedy → reboot (max 3 per 30 min) → **SAFE MODE** (retries forever, may reboot once per 6 h). Built as a **pure state machine first**, then wrapped in probes, a ledger and a daemon. |
| **TECHNICAL REASON** | Layered, cheapest first — *"prefer a flag flip to a restore; prefer a bounded correction to a whole-database rollback."* And the governing principle: **an untested recovery mechanism is worse than none** — *"it creates false confidence, and it can itself take a node down. That is why none of these are enabled today."* |
| **TRADEOFF** | Live on **N002 only**; N001 untouched. Every recovery layer beyond systemd `Restart=always` and the SoC watchdog is **still `0`** in `hardening.conf`. The whole 11-experiment validation plan is **unexecuted**. |
| **EVIDENCE** | `recovery-validation.md`; commits `1dc3df5`, `159888e`, `0fe8d67`, `eadb82d`, `97ceeae`, `5164d9c`, `7a32760`; `make test-node` = 42 hermetic tests. |
| **CURRENT STATUS** | **PARTIALLY CURRENT / largely PLANNED.** |

## D-23 · Sensor calibration

| | |
|---|---|
| **PROBLEM** | Convert ADC counts into volts and amperes. |
| **ALTERNATIVES CONSIDERED** | **None documented.** |
| **CHOSEN APPROACH** | Per-phase multiplicative scale constants applied after DC removal and RMS: `VOLTAGE_SCALE = {A: 132.3452, B: 130.4466, C: 130.4163}`, `CURRENT_SCALE = {A: 1.0, B: 1.0, C: 1.0}`. |
| **TECHNICAL REASON** | The three distinct voltage constants, given to four decimal places and differing by ~1.5 % between phases, are consistent with a **per-channel calibration against a reference** — but the procedure, the reference instrument and the date are **not recorded anywhere**. |
| **TRADEOFF** | ⚠ **The current channels are not calibrated at all.** `CURRENT_SCALE = 1.0` means `current_a` is the CT channel's RMS **in ADC volts**, and every derived power figure on N003's ADS path inherits that. A single multiplicative constant also cannot correct phase shift, non-linearity or offset drift. |
| **EVIDENCE** | `processing/electrical.py` on N003 — VERIFIED by direct read 2026-08-13. |
| **CURRENT STATUS** | **EXPERIMENTAL and incomplete.** → **Q-03, Q-04.** |

## D-24 · Analytics sized to the dataset

| | |
|---|---|
| **PROBLEM** | Produce forecasting, anomaly detection and profiling from ~11 weeks of data from effectively **one** instrumented node. |
| **ALTERNATIVES CONSIDERED** | **A neural forecaster** — explicitly rejected on three grounds: the production series is *"one node with roughly two and a half months of continuous data"*; the server has **no GPU** and inference must complete inside a dashboard request; and *"a random forest's behaviour can be explained to a facilities manager who has to act on it."* **Gradient-boosted ensembles on engineered features** — rejected as *"would fit noise."* |
| **CHOSEN APPROACH** | scikit-learn RandomForest / IsolationForest / KMeans, trained **on request** rather than on a schedule, all running locally. |
| **TECHNICAL REASON** | *"A random forest on obvious temporal features is the honest size of model for this dataset."* Training on request *"removes an entire class of 'the model is stale' bugs."* |
| **TRADEOFF** | The models are **very** modest — the forecaster uses two integer features and is then clamped to ±35 % of a moving average; the clustering result is not actually derived from the clustering (§H.1 A3). |
| **EVIDENCE** | `docs/AI.md`; `app/services/ml_engine.py` — VERIFIED. |
| **CURRENT STATUS** | **CURRENT.** |

## D-25 · Telegram as the alert channel

| | |
|---|---|
| **PROBLEM** | Deliver alerts to facilities staff. |
| **ALTERNATIVES CONSIDERED** | **None named**, but the reasoning implies email/SMS/a new app were weighed: *"Alert delivery that requires a new app is alert delivery that gets ignored."* |
| **CHOSEN APPROACH** | Telegram Bot API through a **durable outbox** that never discards a message. |
| **TECHNICAL REASON** | *"The operators already carry it."* The outbox means *"a Telegram outage delays delivery; it does not lose the alert."* |
| **TRADEOFF** | A third-party dependency on the alert path, and an outbound internet requirement. Empirically robust: **2,165 delivered, 31 failed** — all failures in a single 39-minute window, none lost. |
| **EVIDENCE** | `docs/Architecture.md` §5; `monitor_notification_outbox` (VERIFIED). |
| **CURRENT STATUS** | **CURRENT.** |

## D-26 · No containers, no broker, no ORM migration framework

| | |
|---|---|
| **PROBLEM** | Choose the operational substrate. |
| **ALTERNATIVES CONSIDERED** | All three named and rejected in `docs/Architecture.md` §5 "What is deliberately absent". |
| **CHOSEN APPROACH** | systemd, gunicorn and a static build on a single server, plus Raspberry Pis *"managed as pets."* |
| **TECHNICAL REASON** | **Containers:** *"The deployment target is one server and a handful of Pis… Docker would add a layer without removing one."* **Message broker:** *"The edge buffer already provides durability and backpressure; a broker would duplicate it."* **ORM migrations:** see D-10. |
| **TRADEOFF** | No orchestration, no failover, and a deployment that is a set of documented manual procedures. Also a real hazard on this host: *"Never `docker system prune` on this host — all images and both volumes belong to running OpenWebUI containers."* |
| **EVIDENCE** | `docs/Architecture.md` §5; `docs/Deployment.md`. |
| **CURRENT STATUS** | **CURRENT.** |

---

# PHASE 5 — VALIDATION AND TESTING EVIDENCE

**Framing.** Most validation in this project is **engineering verification**
(does the software do what it claims?), not **metrological validation** (is the
measurement correct against a reference?). That distinction is preserved below
and must be preserved in the thesis.

**There is no evidence of any measurement being compared against a calibrated
reference instrument.** → **Q-04.**

---

## V-A · Automated test suites — VERIFIED by execution 2026-08-13

| | |
|---|---|
| **WHAT WAS TESTED** | Monitoring rules and thresholds; the measurement contract; smart-plug ingest/ownership; the end-to-end pipeline |
| **METHOD** | Plain-python assertion suites (no test framework — *pytest is not installed on the deployment host*). Four hermetic suites each build a throwaway SQLite database. Executed by the auditor: `make test`, then each suite individually |
| **REFERENCE/BASELINE** | The suites' own expectations |
| **RESULT** | `test_monitoring` **404 passed / 0 failed** · `test_collector` **49 / 0** · `test_smart_plugs` **53 / 0** · `test_synthetic_deployment` **18 / 0**. **Total 524 hermetic checks, all passing.** |
| **SOURCE** | Direct execution; `backend/tests/` |
| **LIMITATIONS** | ⚠ Documentation claims **449** checks (329 for monitoring) — stale. Two suites (`test_energy_aggregate`, `test_deployment_lifecycle`) are **not hermetic** and excluded from CI; `test_deployment_lifecycle` is DOCUMENTED as currently failing because it expects exactly one `active` deployment. **The frontend has no tests at all.** mypy (45 findings) and ESLint (36) are advisory. |

## V-B · The sensitivity checks — validating that monitoring did not go blind

| | |
|---|---|
| **WHAT WAS TESTED** | That real faults still fire after the alerting policy was tightened, while known noise stays silent |
| **METHOD** | `tests/test_monitoring.py` §19–25 plus `tests/test_synthetic_deployment.py`, which drives the **entire pipeline against a generated campaign containing a real overload** |
| **REFERENCE/BASELINE** | Four named fault classes that must fire: **missing phase, overload, power loss, power-factor collapse**; and the message classes from the 1,386-message incident that must stay silent |
| **RESULT** | Passing. The synthetic campaign asserts: **300 A past a 250 A breaker is detected**; the threshold comes from the **panel rating rather than statistics**; the sustain window suppresses it initially; it **pages as EMERGENCY once sustained**; and **completing the campaign closes the alert** rather than leaving it hanging |
| **SOURCE** | `CHANGELOG.md` v1.2.0; `docs/Monitoring.md`; direct execution |
| **LIMITATIONS** | The overload is **synthetic**, not a real breaker event. The suite validates the decision logic, not the sensor. Its own history is a caution — see V-C. |

## V-C · Discovery that two suites were passing vacuously — the strongest validation finding

| | |
|---|---|
| **WHAT WAS TESTED** | (Inadvertently) whether the sensitivity suite was exercising the path it exists to protect |
| **METHOD** | Running the suites on a clean CI machine for the first time, 2026-08-04 |
| **REFERENCE/BASELINE** | Migration 010's `activated_at`/`closed_at` as the real marker of an operational campaign |
| **RESULT** | Both fixtures **predated migration 010** and set only `status`. No deployment was ever found, so the node read as having **no operational deployment** and every electrical rule was *correctly* suppressed. **The suite whose entire purpose is to prove monitoring did not go quiet was itself not exercising that path.** After the fix: `test_synthetic_deployment` 5 passed/6 failed → **18/0**; `test_smart_plugs` 52/1 → **53/0** |
| **SOURCE** | `CHANGELOG.md` v1.2.0 "Fixed" |
| **LIMITATIONS** | Found only because a public repository forced a clean-machine run. It is not known what else the fixtures were failing to exercise. |

## V-D · Clean-machine dependency validation

| | |
|---|---|
| **WHAT WAS TESTED** | Whether a fresh checkout can import and run the application |
| **METHOD** | First CI run on a clean machine, 2026-08-04 |
| **REFERENCE/BASELINE** | A machine that is not the deployment host |
| **RESULT** | **Three undeclared dependencies**, all present in the deployment venv so nothing had ever failed there: `google-genai` (requirements named the legacy `google-generativeai`, which does not provide `from google import genai`); `playwright` (imported at module load by `cfe_scraper.py`); `psutil` (used by the 15 server health rules). Also **three Mermaid diagrams that did not parse** |
| **SOURCE** | `CHANGELOG.md` v1.2.0; `scripts/check_requirements.py` |
| **LIMITATIONS** | Only import-time dependencies are checked. |

## V-E · Migration validation — invariants, shadow runs and restore drills

| | |
|---|---|
| **WHAT WAS TESTED** | That each schema migration preserves every reading, every measured value, every timestamp and every foreign key |
| **METHOD** | For each migration: online backup → invariant snapshot → apply in one transaction → re-check **16 invariants** → record or **automatic rollback**. High-risk steps additionally rehearsed **up → down → up** on a throwaway copy, run in `--shadow` mode against a copy, and gated by a `restore-drill` |
| **REFERENCE/BASELINE** | The pre-migration snapshot, **bounded by `id <= max_reading_id`** so 15 s concurrent ingestion cannot cause a false failure or mask a real loss |
| **RESULT** | **14 migrations applied, 0 rolled back** (VERIFIED, `schema_migrations` — every row has a `checksum` and a `backup_path`, every `rolled_back_at` is NULL). Baseline and shadow reports for the riskiest steps are committed under `backend/docs/migration-baselines/` |
| **SOURCE** | `schema_migrations` (live); ADR-0005; `migrations/invariants.py`; `m8-production-cutover-runbook.md`; `m11-backfill-validation.md` |
| **LIMITATIONS** | The invariants prove **preservation**, not **correctness of interpretation**. Migration 005 reclassified 123,696 rows; the invariants confirm nothing was lost, not that the classification was right. |

## V-F · Buffer-preservation validation during the N002 collector upgrade

| | |
|---|---|
| **WHAT WAS TESTED** | That replacing the collector on a live node does not discard buffered measurements |
| **METHOD** | `sync_status` counts captured **before** the upgrade, compared **after** the restart. Documented as a required step in `docs/Energy-Node-Package.md` |
| **REFERENCE/BASELINE** | The pre-upgrade counts |
| **RESULT** | **5,660 → 5,671 pending; 34,357 discarded unchanged; total 40,017 → 40,028.** Growth only — nothing discarded by the restart |
| **SOURCE** | `docs/P2-Simplification-Audit.md` D2 |
| **LIMITATIONS** | Single node, single upgrade. The rollback path (restore the timestamped backup) was **not** exercised. |

## V-G · Fleet-drift verification by checksum

| | |
|---|---|
| **WHAT WAS TESTED** | That the two Pi 5 nodes run identical software |
| **METHOD** | `sha256sum /opt/energy-node/app/collector.py` on both nodes; `grep -c '_hb_heartbeat.publish'`; server-side heartbeat producer/version query |
| **REFERENCE/BASELINE** | The Energy Node Package v2.1 reference build |
| **RESULT** | Both nodes: **`d9cc6138c8be60b273615d13`** — byte-identical. Both produce v2.0.0 authenticated heartbeats at a steady cadence. **Verified again by the auditor 2026-08-13**: `sha256sum` on N002 returns `d9cc6138c8be60b273615d13` |
| **SOURCE** | `docs/Fleet-Manifest.md`; `docs/Energy-Node-Package.md`; auditor's SSH session |
| **LIMITATIONS** | ⚠ The **hardening package reports a checksum mismatch on both Pi 5 nodes** (recorded `fd660f9d7fb9`, actual `5a70bee18bf1`) — the installed tree is **not** the released tree, so rollback targets are ambiguous. N003 is out of scope entirely. |

## V-H · Documentation-node consistency verification — performed by this audit

| | |
|---|---|
| **WHAT WAS TESTED** | Whether documentation on the nodes has diverged from the repository |
| **METHOD** | `find / -xdev -name "*.md"` on N002 and N003, then `sha256sum` against the repository copies |
| **REFERENCE/BASELINE** | `edge/node/**` in the git repository |
| **RESULT** | **All 9 project `.md` files on N002 and both on N003 are byte-identical to their repository counterparts.** No node carries undocumented documentation |
| **SOURCE** | This audit, 2026-08-13 (§1.7) |
| **LIMITATIONS** | **N001 was not reachable** (port 22 filtered on both known addresses). The equivalent **code** is *not* in the repository. |

## V-I · Root-cause investigation: the false read-only EMERGENCY

**The strongest piece of diagnostic work in the project.**

| | |
|---|---|
| **WHAT WAS TESTED** | Whether `node.filesystem_readonly: true` indicated a failing SD card |
| **METHOD** | Compared the probe result **inside and outside the service's mount namespace** using `nsenter -t 1305 -m`; then ran independent storage evidence: `/proc/mounts`, `statvfs ST_RDONLY`, write tests in four locations, a full SQLite create/insert/commit/drop cycle, `tune2fs`, and boot-history counts of remount-ro / mmc / ext4 errors |
| **REFERENCE/BASELINE** | The host's own view of the same filesystem |
| **RESULT** | **Monitoring logic bug; the storage is healthy.** `ProtectSystem=strict` places the service in a private mount namespace where `/` genuinely **is** `ro,nosuid,noatime`; the host sees `rw,noatime`. Same code, same file, same host. `disk_percent` diverged (17.5 inside vs 13.9 on host) for the same reason (`PrivateTmp=true`). Storage evidence: remount-ro events **0**, mmc errors **0**, ext4 errors **0**, `Filesystem state: clean`, card manufactured 06/2025 with 46 GB lifetime writes, and **75,261 buffered measurements** written normally, newest seconds before capture |
| **SOURCE** | `monitoring/evidence/filesystem-readonly-20260806_134531.md` |
| **LIMITATIONS** | One node, one point in time. |

**The conclusion is quotable:** *"The value is not wrong about the namespace — it
is **the wrong question**."* Four required fixes were derived: probe the path the
service is responsible for, report **tri-state** (True/False/NULL) honestly,
**corroborate before alarming**, and never assert SD-card failure without ext4 /
I/O / mmc / remount-ro evidence.

## V-J · Root-cause investigation: the N001 identity collision

| | |
|---|---|
| **WHAT WAS TESTED** | Whether two heartbeat producers claiming to be N001 were two physical machines |
| **METHOD** | Compared **host-unique discriminators** present in both payloads against N001 measured on-device — deliberately **not** inferred from NAT addresses |
| **REFERENCE/BASELINE** | N001's actual on-device values |
| **RESULT** | **Not a separate machine.** `collector_pid` **1305** in both and on-device; `sqlite_size_mb` 25.15 / 25.1 vs 25.10 measured; `uptime_seconds` 154,440.6 / 153,640.3 — same boot; same hostname; same `ip_address`. **Producer 2 was an old agent left in a backup directory** (`/opt/energy-node/backups/pre-m14-hardening-20260803_082109/app/node_agent.py`) whose argument handling is `once = "--once" in sys.argv` — it parses no other flags, so a `--dry-run` flag is **silently ignored** and it enters its infinite publish loop |
| **SOURCE** | `monitoring/evidence/identity-collision-20260806_134531.md` |
| **LIMITATIONS** | — |

**A notable integrity practice:** the report **discloses that the audit itself
caused the second window** — a read-only probe invoked that backup file with
`--dry-run`, which it ignored, and it published as N001 until the SSH channel
closed. *"Disclosed rather than left as an unexplained anomaly."*

**This is the empirical evidence that produced D-18** and closed the project's
most-cited limitation.

## V-K · Diagnostic proof that N003's ADS1256 front end is dead

| | |
|---|---|
| **WHAT WAS TESTED** | Whether N003's zero readings were a de-energised panel or a dead converter |
| **METHOD** | Collector stopped for **exclusive SPI access**; read `STATUS`, `MUX`, `ADCON`, `DRATE` register read-backs on both chips; captured 400 raw samples × 3 phases × 2 ADCs |
| **REFERENCE/BASELINE** | The ADS1256 factory chip-ID nibble (`0x3` in `STATUS`); and the platform's own historical noise-floor signature (~127 V with current at ~1e-5 A) |
| **RESULT** | `STATUS` = **`0x00`** on both chips. `MUX`/`ADCON`/`DRATE` all read back `0x00` **immediately after writing** `STATUS=0x30` and `DRATE=0xD0` — writes do not stick, reads return zero, **MISO is undriven**. Raw codes all **constant 0**, `distinct = 1/400`, stdev `0.00`. **Zero tracebacks in the node's entire log history** |
| **SOURCE** | Prior session, recorded in project memory; corroborated by the auditor today via `energy_readings` (bench era avg voltage **128.64 V**; production era avg **0.7956 V**) |
| **LIMITATIONS** | Cannot distinguish "boards unpowered" from "ribbon unseated" without on-site work. The node was stored ~2026-07-27 and repowered 2026-08-03 — **its buffer has no rows at all for 07-27 → 08-02**, consistent with physical handling. |

**The generalisable diagnostic:** *exactly `0.0` voltage is the tell.* Genuinely
idle mains still reads ~127 V. Disconnected CTs give zero current but **live
voltage and a chip that still answers with ID `0x3`.*

## V-L · Power-event characterisation and the recovery ground truth

| | |
|---|---|
| **WHAT WAS TESTED** | Why nodes required human intervention, and which recovery mechanisms could possibly help |
| **METHOD** | Black-box boot records plus **the RTC value at next boot** as the discriminator between "power genuinely went away" and "the board stayed powered while the SoC was held off" |
| **REFERENCE/BASELINE** | RTC epoch (`1970-01-01`) = true power loss; RTC correct = brownout latch |
| **RESULT** | **2026-07-27** — RTC at epoch: true power loss, node booted **unattended**. **2026-07-23 (23 h)** and **2026-08-01 (43 h 37 m)** — RTC **retained correct time**: brownout latch, **both needed a human**. The internal watchdog **was active during the 2026-08-01 failure and could not help** — its counter is inside the SoC, which had no power. The UPS wake keys off power *returning*; power never left. **N001's blackbox records 27 boots, 23 unplanned**, last classified `power_loss` |
| **SOURCE** | `edge/node/hardening/docs/recovery-validation.md`; project memory |
| **LIMITATIONS** | Small n (three characterised events). The brownout latch has **never been reproduced on demand** — that is experiment V7, unexecuted. |

**A negative result recorded honestly:** across **7 captured undervoltage
events**, `batt_ma` stayed between **−2 and +1 mA** and `on_battery` was **0 every
time** — the battery has floated at ~4.19 V for the entire observation period, so
**the INA219 discharge sign convention has never executed** and remains assumed
rather than verified.

## V-M · The recovery validation plan — PLANNED, explicitly unexecuted

| | |
|---|---|
| **WHAT WAS TESTED** | **Nothing yet.** |
| **METHOD** | Eleven experiments (V1–V11), each with prerequisites, enable step, method, expected outcome, success criteria, failure meaning, rollback, risk rating, and required data capture |
| **REFERENCE/BASELINE** | The characterised failure modes of V-L |
| **RESULT** | **None.** The document opens: *"Nothing in this document has been executed. Every recovery mechanism in the package ships **disabled** and **unvalidated**."* |
| **SOURCE** | `edge/node/hardening/docs/recovery-validation.md` |
| **LIMITATIONS** | This is the plan's own stated position, not an oversight. Its governing principle: *"An untested recovery mechanism is worse than none: it creates false confidence, and it can itself take a node down."* |

**Its decision structure is genuinely experimental** and is good thesis material:
V5 Phase B (does a pre-armed RTC alarm wake the board from a real brownout
latch?) is marked *"genuinely unknown… undocumented either way"*, with the
explicit consequence — **if it succeeds the failure mode is solvable in software;
if it fails, external hardware becomes a procurement requirement rather than an
optimisation.**

## V-N · Networking subsystem unit tests

| | |
|---|---|
| **WHAT WAS TESTED** | The state machine (boot grace, first-boot→AP, stable-before-teardown, flapping links, backoff and its cap, operator overrides, AP self-healing); uplink selection (all three Ethernet modes, the sensor-segment case); the collector contract (**fail-open on missing / stale / corrupt** state file); config degradation; `nmcli` terse parsing including colon-escaped SSIDs |
| **METHOD** | `python3 -m unittest discover -s tests -t .` — **the installer re-runs the suite on each node after installing**, and the deployment orchestrator *"refuses to ship a payload whose unit tests do not pass"* |
| **REFERENCE/BASELINE** | Expected state transitions, with **time injected as a parameter** so every transition is testable without a radio |
| **RESULT** | **46 tests** |
| **SOURCE** | `edge/node/net/README.md` |
| **LIMITATIONS** | Tests the **pure decision layer**. Real radio behaviour, real NetworkManager interaction and real AP association are not covered. Not run by the auditor. |

## V-O · Recovery Manager node tests

| | |
|---|---|
| **WHAT WAS TESTED** | The recovery decision core (built deliberately as a **pure state machine** before any I/O), probes, ledger, boot-state persistence, SAFE MODE |
| **METHOD** | `make test-node` — 42 hermetic tests; plus a **passive live proof** on N002 |
| **REFERENCE/BASELINE** | Expected escalation policy: service remedy → reboot (max 3/30 min) → SAFE MODE |
| **RESULT** | **42 hermetic tests.** SAFE MODE proven end to end on a live node (commit `7a32760`) after **three reporting defects found in Stage B** were corrected (`5164d9c`). A partial demonstration is recorded: *"the safe suite proves a `SIGSTOP`ed collector still reads `active` to systemd"* |
| **SOURCE** | Commits `1dc3df5`, `159888e`, `0fe8d67`, `eadb82d`, `97ceeae`, `5164d9c`, `7a32760`; project memory |
| **LIMITATIONS** | **N002 only.** The destructive experiments (V1–V11) remain unexecuted. |

## V-P · Smart-plug field validation

| | |
|---|---|
| **WHAT WAS TESTED** | Discovery, ownership, offline/online transitions, reboot persistence, and non-interference with the Energy Node pipeline |
| **METHOD** | The acceptance criteria in `edge/HANDOFF-raspberry-pi.md`: dry run (`--once --log-level DEBUG`) before enabling anything; then unplug a plug → must become `online: false` with `last_seen` **preserved and not deleted**; plug back in → must recover; reboot the Pi → known plugs must return from the local buffer. Non-interference: `energy_readings` count still growing, `nodes.last_sync` still current, edge POSTs still 200 |
| **REFERENCE/BASELINE** | The four known plug MACs |
| **RESULT** | Four plugs live and reporting; **152,493 readings** as of 2026-08-13 (VERIFIED). Three of the four have been continuously present since 2026-07-25 19:20; plug 1 stopped at **2026-08-11 02:45** and is `online = 0` — the offline-detection path demonstrably works. Deployment reports for all three nodes are committed under `docs/deployments/` |
| **SOURCE** | `edge/HANDOFF-raspberry-pi.md`; `docs/deployments/*.md`; live `smart_plugs` / `smart_plug_readings` |
| **LIMITATIONS** | ⚠ *"`_mdns_candidates()` and the real subnet sweep were **stubbed in tests** — the Pi is their first real exercise."* **No plug reading has been compared against any reference.** |

## V-Q · Ownership and API validation

| | |
|---|---|
| **WHAT WAS TESTED** | That the first node to report a plug claims it and other nodes are refused; MAC/duplicate/timestamp validation; idempotent replay |
| **METHOD** | `tests/test_smart_plugs.py`, 53 checks against a throwaway database |
| **REFERENCE/BASELINE** | The ownership contract in `docs/Smart-Plug-Architecture.md` |
| **RESULT** | **53/0 passing** (VERIFIED by execution). `(smart_plug_id, timestamp)` uniqueness makes replaying a buffered batch **idempotent**; upsert keyed on MAC means a plug on a new IP updates in place and never duplicates |
| **SOURCE** | Direct execution; `edge/CHANGELOG.md` 1.2.0 |
| **LIMITATIONS** | — |

## V-R · Auth-policy parity regression tests

| | |
|---|---|
| **WHAT WAS TESTED** | That every ingest route derives the authentication policy from the **same** function |
| **METHOD** | `tests/test_monitoring.py` §3g — tests that compare routes **against each other** rather than each against a fixed expectation |
| **REFERENCE/BASELINE** | `node_auth.enforcement_applies_to()` as the single source |
| **RESULT** | Passing. *"Any new route that re-derives the policy fails regardless of which way it diverges"* |
| **SOURCE** | Project memory; `tests/test_monitoring.py` |
| **LIMITATIONS** | — |

**This is a notable test-design idea for the thesis:** the bug being guarded
against was two routes disagreeing, so the test asserts **agreement between
implementations** rather than conformance to a constant.

## V-S · CI gates as continuous validation

| | |
|---|---|
| **WHAT WAS TESTED** | Lint/format consistency, declared dependencies, hermetic suites, documentation link integrity, Mermaid diagram parseability, **API-documentation completeness**, commit-message convention, and security scanning |
| **METHOD** | `make check` — the same gates CI runs. Six GitHub workflows: backend, frontend, docs, security (gitleaks, pip-audit, npm audit, CodeQL), commitlint, release drafter |
| **REFERENCE/BASELINE** | The running OpenAPI schema, for `check_api_docs.py` |
| **RESULT** | Gates in place. `scripts/check_api_docs.py` **fails the build when a route exists that `docs/API.md` does not document, or vice versa** — which is what makes the API reference verifiable rather than aspirational |
| **SOURCE** | `Makefile`; `.github/workflows/`; `CHANGELOG.md` v1.2.0 |
| **LIMITATIONS** | mypy and ESLint are **advisory** (45 and 36 pre-existing findings) — *deliberately*, because tightening the config without doing the annotation work would produce a false green. |

## V-T · What was NOT validated

Stated plainly, because these are the gaps a thesis examiner will ask about.

| Not validated | Consequence |
|---|---|
| **Any measurement against a calibrated reference instrument** | The platform cannot state its own measurement uncertainty. → **Q-04** |
| **Shelly Pro 3EM vs ADS1256 side by side** | The two acquisition chains have **never been compared**, on the same load or otherwise. This is the single most valuable missing experiment. → **Q-07** |
| **CT clamp linearity, ratio or phase error** | `CURRENT_SCALE = 1.0` — the current path was never characterised at all |
| **Voltage calibration procedure** | The three `VOLTAGE_SCALE` constants exist; **their derivation is unrecorded**. → **Q-03** |
| **Any measurement against the utility bill** | `meter_energy_kwh` exists *"so a campaign can be checked against the utility bill"* — **no such reconciliation is recorded**. → **Q-08** |
| **Forecast accuracy against held-out data** | Only a moving-average MAPE (§H.1 A4). No baseline comparison, no cross-validation |
| **Anomaly detection against labelled faults** | `contamination=0.08` fixes the anomaly rate by construction |
| **Clustering validity** | Moot — the KMeans labels are discarded (§H.1 A3) |
| **Whole-database restore from a production backup** | `restore-drill` exists and is documented as gating high-risk steps; **no drill result is recorded** as evidence. → **Q-09** |
| **Recovery mechanisms V1–V11** | Explicitly unexecuted (V-M) |
| **The rollback path of a node collector upgrade** | Documented; not exercised |
| **Any frontend behaviour** | No test suite exists |
| **Network failure/recovery in the field** | The 46 unit tests cover the pure decision layer only; **no recorded field test** of the AP fallback, factory reset, or a real SSID change. → **Q-10** |

---

# PHASE 6 — RESULTS INVENTORY

**This section is deliberately conservative. Nothing is promoted between
categories.**

All figures below were read from the live database or the node filesystems on
**2026-08-13** unless a different source is stated.

---

## 6.1 VERIFIED REAL RESULTS

Numbers demonstrably obtained from a real electrical load at a real panel.

### R-1 · N001 production series — deployment 4

| Quantity | Value |
|---|---|
| Rows | **118,620** |
| Window | 2026-06-14 21:57:34 → 2026-07-30 21:09:15 |
| Building / panel | 8 *Edificio de prueba* (⚠ **placeholder**) / 8 *Tablero Principal* |
| Mean active power | **19.662 kW** |
| Min / max active power | 2.22 kW / **32.649 kW** |
| Mean voltage | **126.83 V** |
| Mean current | **195.70 A** |
| Mean power factor | **0.805** |
| Mean frequency | **59.996 Hz** |
| `energy_kwh` populated | 117,960 of 118,620 rows |
| Instrument | Shelly Pro 3EM, 120 A CT |

**Source:** `SELECT … FROM energy_readings WHERE node_id=1 AND context='production'
AND deployment_id=4`.

**Caveats that must travel with this figure:**
- The building label is a **development placeholder**; the *load* is real, the
  *place label* is not authoritative (ADR-0006).
- **Mean current 195.70 A against a 120 A rated CT.** → **Q-12.**
- This series spans the `energy_kwh` semantic change of 2026-07-03 15:32:39;
  only `measurement_eras` makes it interpretable.
- ⚠ `README.md` and `docs/AI.md` describe N001 as *"~11.4 kW"*. The measured mean
  over deployment 4 is **19.662 kW**. → **C-10.**

### R-2 · N001 production series — deployment 6

| Quantity | Value |
|---|---|
| Rows | **22,443** |
| Window | 2026-07-30 21:09:30 → 2026-08-06 14:18:53 |
| Building / panel | 9 *Edificio Principal Prueba* / 9 *Centro de Datos* |
| Mean active power | **6.311 kW** |
| Min / max | 0.0 kW / **13.407 kW** |
| Mean voltage | **127.73 V** |
| Mean current | **52.39 A** |
| Mean power factor | **0.512** |
| Mean frequency | **59.994 Hz** |

**A genuinely different load profile** from deployment 4 — roughly one third the
power, one quarter the current, and a markedly worse power factor (0.512 vs
0.805). **This is the deployment model working**: the same node, moved, produced
a distinguishable characterisation of a second panel.

⚠ **Caveat:** 10,450 of these rows (2026-08-03 21:57 → 2026-08-06 14:18) fall
**outside deployment 6's operational window** and were attributed by the old
pipeline (`affected-rows-20260806_142730.md`). Their mean power in that report is
0.017 kW — so the deployment-6 mean above **mixes real load with a near-idle
tail**. Treat 6.311 kW as an aggregate over a mixed set.

### R-3 · N001 production series — deployment 7 (live at audit)

| Quantity | Value |
|---|---|
| Rows | **170** (growing) |
| Window | 2026-08-13 14:18:01 → 14:52:16 (~34 minutes) |
| Building / panel | 10 *Edificio Principal 2.0* / 10 *SITE* |
| Mean active power | **12.944 kW** |
| Min / max | 12.814 / **13.161 kW** |
| Mean voltage | **126.61 V** |
| Mean current | **107.58 A** |
| Mean power factor | **0.949** |
| Operator note | *"Despliegue temporal para comparación de cargas en periodos de ingreso."* |

**Remarkably stable** — a 2.7 % spread between min and max over 34 minutes, and
a power factor of 0.949. This is the freshest and cleanest data in the platform,
produced by the current resolver on an `active` deployment.

**Too short to draw conclusions from.** 34 minutes is not a load profile.

### R-4 · N003 prototype acquisition series (May–June)

| Quantity | Value |
|---|---|
| Rows | **120,361** |
| Window | 2026-05-13 14:20:15 → 2026-06-20 21:51:33 (**38 days**) |
| Context | `laboratory` — **deliberately unattributed** |
| Mean active power | **21.577 kW** |
| Min / max | 10.111 / **26.324 kW** |
| Mean voltage | **126.17 V** |
| Mean current | **225.87 A** |
| Mean power factor | **0.756** |
| Instrument | **Shelly EM/Pro 3EM over HTTP** (predates the ADS1256 conversion of 2026-07-24) |

**This is real acquisition from a real load.** ADR-0006 records the platform
owner's own determination: *"N003's May–June data is real historical acquisition
from the prototype. It predates the deployment model and must not be
retroactively attributed."*

**Independent corroboration — VERIFIED on the node today:**
`/home/theblackdie/udec-edge/deployment_week.csv`, 22.6 MB, **120,104 lines**
(120,103 data rows), written 2026-05-29. First rows:

```
captured_at              V_a    I_a     P_a      S_a      PF_a  f    ... total_P   total_S   total_I
2026-05-13T14:20:15.325Z 125.6  66.408  6994.4   8354.3   0.84  60.0    19644.406 26333.074 209.711
2026-05-13T14:20:29.213Z 125.3  69.324  7089.2   8701.0   0.79  60.0    20346.480 28042.080 223.645
```

Per-phase detail: **V ≈ 124.8–125.7 V per phase; I ≈ 59–93 A per phase; PF 0.62–0.84
per phase; f = 60.0.** Phase C consistently carries the worst power factor.

**This CSV is the single best raw-data artefact in the project** — a
self-describing, exportable, 38-day three-phase campaign. It should be a thesis
dataset appendix.

⚠ **Caveat:** the 15 s cadence produces 13.9 s and 14.0 s inter-sample gaps in
the first two rows — the loop is `sleep(max(0, POLL_INTERVAL − elapsed))`, so the
cadence is nominal, not exact.

### R-5 · Smart-plug sub-metering series

| Plug | Rows | Window | Mean P | Max P | Cumulative energy |
|---|---:|---|---:|---:|---:|
| 2 (`…F2:83:08`) | **45,781** | 2026-07-25 19:20 → 2026-08-13 14:53 | **175.39 W** | 359.0 W | **78.0433 kWh** |
| 3 (`…F6:53:88`) | **45,774** | same window | 4.90 W | **1,877.8 W** | 2.7381 kWh |
| 4 (`…F2:91:B8`) | **45,658** | same window | 0.00 W | 29.9 W | 0.0063 kWh |
| 1 (`…F2:57:EC`) | **15,292** | 2026-07-25 19:20 → **2026-08-11 02:45** | 6.47 W | 1,272.1 W | 1.0096 kWh |
| **Total** | **152,493** | 19 days | | | |

**Plug 2 is a continuously-loaded outlet** — 175 W mean over 19 days, 78 kWh
cumulative. Plug 3 shows a **1,877.8 W peak against a 4.90 W mean** — an
intermittent high-draw appliance, exactly the discovery the sub-metering exists
to make. Plug 4 is effectively unloaded. Plug 1 went offline on 2026-08-11.

⚠ **Only plug 3 is assigned to a building** (building 8, deployment 5). The other
three — including the 78 kWh one — are **unattributed**.

### R-6 · Alerting operational record

| Quantity | Value |
|---|---|
| Alerts raised | **675** (674 resolved, 1 open) |
| Alert events | **3,713** |
| Telegram messages **delivered** | **2,165** (2026-07-26 16:32 → 2026-08-13 14:50) |
| Telegram messages **failed** | **31** (all within a single 39-minute window on 2026-07-29) |
| Node heartbeats received | **19,941** |
| Server heartbeats | **25,764** |
| Identity violations recorded | **12,278** |
| `electrical.current` share of all alerts | **480 of 675 = 71 %** |

**The 1,386-messages-in-4-days figure** is DOCUMENTED (`CHANGELOG.md` v1.1.0,
`docs/Monitoring.md`, project memory) and is **consistent with** the outbox: 2,165
total delivered over 18 days, with the policy rebuilt on day 4.

Sub-figures from the incident analysis, all DOCUMENTED (from the message history,
not re-derivable from the current tables): 697 messages on one day · 73 in one
hour · **1,288 of 1,312 (98 %) from nodes with no operational deployment** ·
**962 messages from the 200 A threshold alone**, which sat at N001's **94th
percentile** · **404 of 472 alerts lasted under two minutes** · one disk trend
produced an **EMERGENCY and 71 notifications** with three weeks of headroom.

### R-7 · Platform scale

| Quantity | Value |
|---|---|
| `energy_readings` | **290,439** rows |
| Span | 2026-05-13 14:20:15 → 2026-08-13 14:52:16 (**92 days**) |
| Distinct days with data — N001 | **38** |
| Distinct days with data — N003 | **25** |
| Distinct days with data — N002 | **0** |
| Database size | **311.2 MB** + 4.4 MB WAL |
| Tables | **34** |
| Migrations applied / rolled back | **14 / 0** |
| API operations | **90** across 85 paths |
| Health rules | **42** |
| Hermetic test checks | **524** |
| `App.tsx` | **2,532** lines |

⚠ **"Ingesting continuously since May 2026"** (README) needs qualification: the
span is 92 days but only **63 node-days** carry data, from **two** nodes, and the
two series **do not overlap** — N003 ends 2026-06-20, N001 begins 2026-06-14.

### R-8 · Node reliability record

| Quantity | Value | Source |
|---|---|---|
| N001 boots recorded | **27**, of which **23 unplanned**, last classified `power_loss` | blackbox, DOCUMENTED |
| Characterised long outages | 2026-07-23 (**23 h**), 2026-08-01 (**43 h 37 m**) — both brownout latches, both needed a human | `recovery-validation.md` |
| Unattended recovery | 2026-07-27 — true power loss, node booted unattended | idem |
| Undervoltage events captured | **7**, all with `batt_ma` between **−2 and +1 mA** and `on_battery = 0` | idem |
| `get_throttled` | `0x50000` on **both** Pi 5 nodes — undervoltage and throttling **have occurred** | Fleet Manifest |
| N002 buffer at audit | **23,517** rows pending | `monitor_node_heartbeat_latest` |
| N003 buffer at audit | **7,217** pending / 128,095 sent | direct query |
| N002 buffer growth rate | ~**5,700 rows/day** | P2 audit |
| N001 SD card | `SN64G`, manufactured 06/2025, **46 GB lifetime writes**, 0 remount-ro / 0 mmc / 0 ext4 errors | filesystem-readonly evidence |

## 6.2 TEST / DEVELOPMENT DATA

Obtained while testing hardware or software. **Real signal in some cases, but not
a measurement of a building's consumption.**

### T-1 · N003 ADS1256 bring-up, `bench` context

| Quantity | Value |
|---|---|
| Rows | **3,335** |
| Window | 2026-07-24 23:28:41 → 2026-07-26 22:39:25 |
| Mean active power | **−0.0 kW** (max |P| = 1.5 × 10⁻⁵ kW) |
| Mean voltage | **128.6383 V** ← **live signal** |
| Mean current | 8.2 × 10⁻⁴ (ADC volts, uncalibrated) |
| Mean power factor | 1.0 × 10⁻⁴ |

**The only period in which the ADS1256 stack demonstrably produced live signal.**
The voltage channel reads a plausible 128.6 V; the current channel is at the
noise floor with no calibration. Correctly classified `bench`,
`counts_in_analytics = 0`.

### T-2 · N003 post-failure rows, misclassified `production`

| Quantity | Value |
|---|---|
| Rows | **4,499** |
| Window | 2026-07-26 22:40:16 → 2026-08-06 14:18:14 |
| Context | ⚠ **`production`** |
| Attribution | ⚠ deployment 5, building 8 |
| Mean active power | **−0.0 kW** |
| Mean voltage | **0.7956 V** ← **dead converter** |
| Mean current | 6 × 10⁻⁶ |

⚠ **These rows are labelled `production` and attributed to a real building, but
they are artifacts of a dead ADC** (§B.5, V-K). They are the residue of the
pre-resolver pipeline. They **must not be used as results.** → **Q-06.**

### T-3 · N003's currently buffered rows — DO NOT UPLOAD

| Quantity | Value |
|---|---|
| Rows | **7,217** (`sync_status = 0`) |
| Window | 2026-08-06 14:19:04 → 2026-08-13 14:58:54 |
| Character | **Artifacts of the dead ADS1256 front end** |

VERIFIED by direct query of `/home/theblackdie/udec-edge/edge_buffer.db` on
2026-08-13. If uploaded they would enter the platform as real observations of a
de-energised panel.

### T-4 · Rows attributed outside any operational window

| Node | Deployment | Rows | Window | Mean P | Max P |
|---|---|---:|---|---:|---:|
| N001 | 6 | **10,450** | 2026-08-03 21:57 → 2026-08-06 14:18 | 0.017 kW | 12.938 kW |
| N003 | 5 | **4,499** | 2026-07-26 22:40 → 2026-08-06 14:18 | 0.0 kW | 0.0 kW |

**Source:** `monitoring/evidence/affected-rows-20260806_142730.md` — *"Read-only.
No row was mutated."*

### T-5 · N001's `infrastructure_validation` period

| Quantity | Value |
|---|---|
| Rows | **21,043** |
| Window | 2026-08-06 14:19:08 → 2026-08-13 14:17:46 |
| Context | `infrastructure_validation` — **unattributed by design** |
| Mean active power | **0.142 kW** |

Node powered and collecting for platform validation with **no operational
deployment**. Real measurements, retained for diagnostics, correctly excluded
from analytics. **This is the `infrastructure_validation` context doing exactly
what migration 014 created it to do.**

### T-6 · Synthetic test campaign

`tests/test_synthetic_deployment.py` generates a campaign including a **300 A
load past a 250 A breaker**. Explicitly synthetic; used only to validate the
monitoring pipeline. **Never enters the production database.**

### T-7 · Migration artefact tables

| Table | Rows | Nature |
|---|---:|---|
| `energy_readings_pre_m4` | **225,594** | Pre-rebuild rollback copy — **not live data** |
| `m5_attribution_backup` | **123,696** | Pre-reclassification attribution snapshot |
| `nodes_pre_m7` / `deployments_pre_m3` / `m5_node_context_backup` | 3 / 2 / 3 | Reference-table snapshots |

**Counting `energy_readings_pre_m4` as data would double-count 225,594 readings.**

## 6.3 EXAMPLE / SYNTHETIC DATA

| Item | Nature |
|---|---|
| `runtime_platform_settings.json` thresholds (`maxCurrent: 200`, `minPowerFactor: 0.90`, `demandSpike: 25`, `nodeOfflineTimeout: 300`) | **UI display defaults**, not measurements. Explicitly forbidden as alerting thresholds |
| The `2026-06-phase1-prototype.html` figures | Mock data from the pre-API prototype |
| `docs/Collector.md` payload example (`power_kw: 12.4`, `interval_energy_kwh: 0.0517`, `meter_energy_kwh: 26411.882`) | **Illustrative**, not a real reading |
| `assets/screenshots/*.png` | Real UI over real data at capture time (2026-08-04), but **frozen** — the numbers shown are not current |
| Building 8 *"Edificio de prueba"* | **Development placeholder**, `is_placeholder = 1` |
| Buildings 9, 10 | `is_user_defined = 1`, created from the technician form. Real deployments, but the names are operator-entered test labels (*"Edificio Principal Prueba"*, *"Edificio Principal 2.0"*) |

## 6.4 UNCERTAIN — provenance cannot be established

| Item | Why uncertain |
|---|---|
| **`VOLTAGE_SCALE` = 132.3452 / 130.4466 / 130.4163** | Four-decimal per-phase constants implying a calibration against a reference — but **no file records the procedure, the reference or the date**. → Q-03 |
| **Whether N001's `energy_kwh` counter era (17,283.82 → 26,259.24 kWh) is a real utility-comparable total** | The era row records it as a monotonic lifetime register with 0.0 % negative deltas; whether it reconciles with any bill is unrecorded. → Q-08 |
| **N003's "1000 A" CT rating** | Recorded in the Fleet Manifest; no part number, and `CURRENT_SCALE = 1.0` means it was never applied |
| **N001's mean current of 195.70 A against a 120 A rated CT** | Either the CT rating in the manifest is wrong, the meter is configured for a different ratio, or the figure means something other than assumed. → Q-12 |
| **Which physical building/panel deployments 4, 6 and 7 actually measured** | The building records are operator-created with test-sounding names. ADR-0006 established building 8 is a placeholder; **9 and 10 are not similarly adjudicated**. → Q-13 |
| **The `~11.4 kW` figure for N001** in README/AI.md | Does not match any measured mean this audit computed. → C-10, Q-14 |
| **`deployment_week.csv`'s exact relationship to the 120,361 stored `laboratory` rows** | 120,103 CSV data rows vs 120,361 stored rows — a 258-row difference, unexplained |
| **The 1,386 / 1,288 / 962 / 404 alerting figures** | DOCUMENTED from the original message history; the current `monitor_alerts` table has been through retention and does not reproduce them |
| **Hardening package checksum mismatch** (recorded `fd660f9d7fb9`, actual `5a70bee18bf1`) | The installed tree is not the released tree; which is authoritative is unknown |

## 6.5 The one-sentence summary of the results position

**The platform holds 92 days of data, but the analysable production dataset is
one Raspberry Pi reading one commercial three-phase meter across three
consecutive deployments totalling 141,233 attributed readings — plus a separate,
unattributed 38-day 120,361-row prototype campaign from a second node.** The
custom ADS1256 instrumentation has produced **no usable measurements**.

---

# PHASE 7 — LIMITATIONS AND UNFINISHED WORK

## 7.1 Measurement limitations

| # | Limitation | Severity | Evidence |
|---|---|---|---|
| M-1 | **No measurement has been validated against a calibrated reference.** The platform cannot state its own uncertainty. | **High** | Absence across all documentation |
| M-2 | **N003's current channels are uncalibrated** (`CURRENT_SCALE = 1.0`). Current is reported in ADC volts; every derived power figure inherits the error. | **High** | `processing/electrical.py`, VERIFIED |
| M-3 | **N003's power factor is computed from non-simultaneous V and I samples.** The phase relationship is destroyed by construction. | **High** | `engine/measurement.py`, VERIFIED |
| M-4 | **N003's frequency is a hardcoded literal `60.0`.** | Medium | `sources/ads.py`, VERIFIED |
| M-5 | **A dead ADC is stored as a plausible `0.0`.** `wait_drdy()` only guards against DRDY stuck *high*; `remove_dc()` + `rms()` turn a constant into exactly zero. **Zero tracebacks in the node's entire log history.** | **High** | V-K |
| M-6 | **Both N003 ADS1256 chips are electrically dead** since ~2026-07-26. Requires on-site work. | **High** | V-K |
| M-7 | **The production measurement chain is a vendor black box.** The Shelly Pro 3EM's calibration and internal processing are not the project's. | Medium | D-02 |
| M-8 | **The canonical measurement contract is not emitted.** `energy_source`, `interval_energy_kwh`, `interval_seconds`, `meter_energy_kwh` are **NULL on all 290,439 rows**. | **High** | VERIFIED |
| M-9 | **Energy is integrated using the nominal interval, not elapsed time** — `power_kw × POLL_INTERVAL / 3600`. | Medium | Architecture review |
| M-10 | **`energy_kwh` had two meanings** and dashboard KPIs were **~400× low** before ADR-0007. Legacy rows remain interpretable only via `measurement_eras`. | Medium (resolved) | ADR-0007 |
| M-11 | **The RTC does not hold time across power loss.** At boot the kernel sets `1970-01-01T00:00:10`; systemd advances to a stale saved timestamp; NTP then corrects. The collector is ordered `After=network-online.target` but **not** `time-sync.target`, so it can stamp measurements with a wrong `captured_at`. **Not theoretical: N001's buffer has 4 rows where a later `id` carries an earlier `captured_at`.** Attribution is by `captured_at`, so once uploaded this is **silent and permanent**. | **High** | Architecture review |
| M-12 | Sampling cadence is **nominal, not exact** — `sleep(max(0, POLL_INTERVAL − elapsed))` produces 13.9–14.0 s gaps. | Low | `deployment_week.csv`, VERIFIED |
| M-13 | **No CT characterisation** — no linearity, ratio-error or phase-error data for any clamp. | Medium | Absence |
| M-14 | **No schematic** for N003's signal conditioning (burden resistors, bias, divider). | Medium | Absence |

## 7.2 Hardware limitations

| # | Limitation | Evidence |
|---|---|---|
| H-1 | **Raspberry Pi brownout latch is unrecoverable in software today.** Two outages of 23 h and 43 h 37 m. The internal watchdog cannot help — its counter is inside the SoC, which had no power. | V-L |
| H-2 | **Undervoltage and throttling have occurred on both Pi 5 nodes** (`get_throttled = 0x50000`). Undervoltage is upstream of most SD-card failures. | Fleet Manifest |
| H-3 | **N003 (Pi 3B+) is explicitly unsupported** by the Energy Node Package: no PMIC ADC, no usable GPIO I²C (only `i2c-2`, the HDMI DDC bus), 905 MB RAM, `sudo` needs a password. | Energy-Node-Package.md |
| H-4 | **N002 has no `spidev`** — it could not drive an ADC even if the software existed. | Fleet Manifest |
| H-5 | **The UPS HAT is unreadable on N003** (no GPIO I²C bus enabled). | node03 audit |
| H-6 | **The INA219 discharge sign convention has never executed** — across 7 undervoltage events the battery floated at ~4.19 V and `on_battery` was 0 every time. | V-L |
| H-7 | **N002's bootloader is 4 months behind** N001's (2026-01-21 vs 2026-05-26). | Fleet Manifest |
| H-8 | **No bill of materials.** No part numbers for CTs, enclosure, PSU or conditioning components. | `docs/Hardware.md` |
| H-9 | **No hardware photographs.** The manifest lists them with capture guidance; the images do not exist. | MANIFEST.md |
| H-10 | **Hardening package checksum mismatch on both Pi 5 nodes** — the installed tree is not the released tree, so **rollback targets are ambiguous**. | Fleet drift record |

## 7.3 Data and attribution limitations

| # | Limitation | Evidence |
|---|---|---|
| D-1 | **The analysable production dataset is one node.** N002 has produced zero readings; N003's ADS produced none usable. | VERIFIED |
| D-2 | **All three buildings are operator-created with test-sounding names.** Building 8 is an adjudicated placeholder; 9 and 10 are not adjudicated. | VERIFIED |
| D-3 | **Deployments 5 and 6 own readings after their `closed_at`** — pre-resolver damage, deliberately not fixed because correcting it would mutate historical attribution. | §J.8 |
| D-4 | **4,499 N003 rows are classified `production` and attributed to building 8, but are artifacts of a dead ADC.** | T-2 |
| D-5 | **10,450 N001 rows carry attribution outside any operational window.** | T-4 |
| D-6 | **Only ~25 % of N001's readings fell inside deployment 4's originally declared window.** Handled by opening the window, not by correcting the data. | ADR-0006 |
| D-7 | **Three of four smart plugs are unassigned** — including the one carrying 78 kWh. | VERIFIED |
| D-8 | **`Node.status` is a stale third vocabulary** that disagrees with `last_sync`. N003 currently reads `offline` while its heartbeat is 60 s old. | VERIFIED |
| D-9 | **The two long series do not overlap** — N003 ends 2026-06-20, N001 begins 2026-06-14, and they measure different things. **No cross-validation between nodes is possible from the existing data.** | VERIFIED |
| D-10 | **All physical-rating columns are NULL** on all nodes and all deployments, so the threshold-resolution chain never reaches its first two tiers. | VERIFIED |

## 7.4 Software limitations and known bugs

| # | Bug / limitation | Status | Evidence |
|---|---|---|---|
| S-1 | **Sync head-of-line block.** One permanently-rejected row halts the entire upload queue forever. N002: 23,517 rows behind one blocker, growing ~5,700/day. | **OPEN, live** | VERIFIED |
| S-2 | **`NODE_ID` defaults to `"N001"`** when `node.env` is missing. Authentication contains the blast radius (403 `subject_mismatch`) but the default should be a hard failure. | **OPEN** | VERIFIED in source |
| S-3 | **`energy-node-collector.service` sets `StartLimitBurst=20`/`StartLimitIntervalSec=300`** — 20 crashes in 5 minutes leaves it permanently `failed` with no reboot escalation. No `sd_notify`/`WatchdogSec`, so a wedged-but-alive collector is invisible. | **OPEN** | Architecture review |
| S-4 | **`edge_node.log` is opened at a relative path and never rotated** — 25.2 MB on N003, duplicating journald. | **OPEN** | VERIFIED |
| S-5 | **`energy-node-verify` runs post-boot and daily, exits 1 when degraded, and no unit consumes the result.** Detection wired to a dead end. | **OPEN** | Architecture review |
| S-6 | **`test_deployment_lifecycle` currently fails** — it expects exactly one `active` deployment. | **OPEN** | DOCUMENTED |
| S-7 | **Two test suites read the live production database** and cannot run in CI. | **OPEN** | VERIFIED |
| S-8 | **The frontend has no test suite.** | **OPEN** | VERIFIED |
| S-9 | **`App.tsx` is 2,532 lines**; 12 of 13 screens unextracted; 36 ESLint findings. | **OPEN** | VERIFIED |
| S-10 | **mypy is advisory** — 45 findings in `app/monitoring` alone. | **OPEN, deliberate** | DOCUMENTED |
| S-11 | **KMeans labels are computed and discarded**; the "cluster" output is rule-based. | **OPEN** | VERIFIED §H.1 A3 |
| S-12 | **The documented forecast feature set does not exist** — no lags, no rolling means; two integer features. | **OPEN** | VERIFIED §H.1 A1 |
| S-13 | **`anomaly_engine`'s "night" window is offset by six hours** (UTC vs UTC−6). Acknowledged in the source. | **OPEN** | VERIFIED |
| S-14 | **`/api/nodes` exposes no measuring/freshness signal** — a consumer cannot tell "online and measuring" from "online and not measuring". The data exists on `/api/monitoring/status`. | **OPEN, deliberate gap** | DOCUMENTED |
| S-15 | **N003 runs two Wi-Fi managers simultaneously** — `netd` and the legacy `energy-node-wifi-fallback`. netd's design requires exactly one mutator. | **OPEN** | Fleet drift |
| S-16 | **The monitoring scheduler runs from cron, not systemd** — the unit exists but needs root. | **OPEN** | VERIFIED |
| S-17 | **`/api/edge/heartbeat` remains unauthenticated and mounted.** Retirement is blocked on whole-fleet collector convergence. | **OPEN, tracked as D3** | VERIFIED |
| S-18 | **Frontend roles are not an authorisation boundary** — they shape what the UI shows, not what the API allows. | **OPEN** | DOCUMENTED |
| S-19 | **CORS is fully permissive** (`allow_origins=["*"]`). *"It becomes dangerous the moment authentication is added [to the UI], and tightening it must be part of that change."* | **OPEN, deliberate** | VERIFIED |
| S-20 | **Backups live on the application server.** A host loss takes them with it. *"The largest single gap in this platform's durability story."* | **OPEN** | DOCUMENTED |
| S-21 | **Single application server, no failover.** A host loss stops ingestion; node buffers absorb up to 7 days. | **OPEN, accepted** | DOCUMENTED |
| S-22 | **Telegram bot token and three Pi passwords were pasted in plaintext** in a 2026-07-26 session and **should be rotated**. | **OPEN** | Project memory |
| S-23 | **Screenshots cannot be captured on the server** — Playwright Chromium present but nine shared libraries absent; installing them needs root. | **OPEN** | VERIFIED |

## 7.5 Incomplete and experimental components

| Component | Status | Note |
|---|---|---|
| **The base collectors** (`collector.py`, `poller.py`) | **NOT IN THE REPOSITORY** | The single largest provenance gap. Top roadmap item. |
| **ADS1256 acquisition chain** | **EXPERIMENTAL, non-functional, not in the repository** | Dead hardware + uncalibrated current + non-simultaneous PF |
| **Canonical measurement contract (ADR-0007)** | **Backend complete, edge not started** | All four columns NULL |
| **Recovery Manager** | **Live on N002 only** | N001 untouched; every recovery layer still `0` |
| **Recovery validation V1–V11** | **PLANNED, entirely unexecuted** | *"Nothing in this document has been executed."* |
| **N003 fleet convergence** | **Not started** | Explicitly out of scope for the Energy Node Package |
| **Physical rating entry** (panel breaker, CT ratings) | **Schema exists (migration 008), values not entered** | Threshold chain degraded to learned baselines |
| **Smart-plug building assignment** | **1 of 4 assigned** | |
| **`test_energy_aggregate` / `test_deployment_lifecycle` hermeticity** | **PLANNED** | |
| **Frontend test suite** | **PLANNED** | |
| **`App.tsx` screen extraction** | **PLANNED** | `components/smartplugs/` is the model |
| **TLS on the API** | **PLANNED** | |
| **Off-host backups** | **PLANNED** | |
| **Legacy `/api/edge/heartbeat` retirement** | **PLANNED, blocked** | |

## 7.6 Analytics limitations

| # | Limitation |
|---|---|
| A-1 | **The forecaster uses two integer features** (hour, weekday) and its output is **clamped to ±35 % of a trailing 24-hour average**. Week and month figures are the daily figure × 7 and × 30. |
| A-2 | **The reported `confidence` from the forecast function is a dispersion heuristic**, not an error measure. |
| A-3 | **The backtested confidence measures a 3-day moving average**, not the RandomForest. |
| A-4 | **`contamination = 0.08` fixes the anomaly rate at 8 % by construction** — the detector will always find anomalies. |
| A-5 | **The clustering output is not derived from the clustering.** |
| A-6 | **Only 3 buildings exist**, one a placeholder — clustering is degenerate regardless. |
| A-7 | **No forecast accuracy against held-out data**, no baseline comparison, no cross-validation, no hyper-parameter search. All parameters are fixed constants. |
| A-8 | **No anomaly detector validation against labelled faults.** |
| A-9 | **No demonstrated energy saving, cost reduction or operational improvement** attributable to the platform. |
| A-10 | **~11 weeks of data from one node** is below what any of these models would normally require. `docs/AI.md` acknowledges this: *"a gradient-boosted ensemble on fifty engineered features would fit noise."* |

## 7.7 Documentation limitations — the contradiction register

**Ten contradictions found. All must be resolved before anything is written.**

| # | Claim in documentation | Observed | Where |
|---|---|---|---|
| **C-01** | *"Raspberry Pi nodes sample through a 24-bit ADS1256 and CT clamps"; "this is the path used by the production nodes"* | Production nodes read a **Shelly Pro 3EM over HTTP**. ADS1256 exists only on N003, and is dead. | README, Hardware.md, Architecture.md, Collector.md |
| **C-02** | *"Ingestion endpoints are unauthenticated… not yet implemented"* | **Authenticated and enforced** since 2026-08-06/07. 12,278 violations logged. | README, Security.md, Architecture.md §6, CHANGELOG v1.2.0, ADR-0002 |
| **C-03** | `energy_source` is a mandatory field of the ingestion contract | **NULL on all 290,439 rows.** No collector sends it. | collector-contract.md, ADR-0007, Collector.md |
| **C-04** | Heartbeat cadence *"every 45 s"* | `HEARTBEAT_INTERVAL=60` in `hardening.conf`; verified 60 s | README, Architecture.md, Monitoring.md |
| **C-05** | *"449 checks"* (329 for `test_monitoring`) | **524** (404 for `test_monitoring`) | README, Backend.md |
| **C-06** | *"255,379 readings, 33 tables, 12 migrations"* | **290,439 / 34 / 14** | README, Database.md, Architecture.md |
| **C-07** | Forecast features include *"lagged demand, rolling means"* | `X.append([dt.hour, dt.weekday()])` — neither exists | AI.md |
| **C-08** | *"KMeans building load profiles"*, output labelled *"Cluster ML generado con K-Means"* | KMeans labels **discarded**; grouping is a four-way if/elif on fixed thresholds | AI.md, README, ml_engine.py output string |
| **C-09** | *"39 health rules"* | **42** registered | README, Monitoring.md, CHANGELOG |
| **C-10** | N001 is *"~11.4 kW"* | Measured means: **19.662 kW** (dep. 4), 6.311 kW (dep. 6), 12.944 kW (dep. 7) | README, AI.md, Database.md |

**Two further documentation risks:**

- `docs/Deployment.md` lists `energy-node-heartbeat.service` as a current
  per-node unit. It is **absent on N001 and disabled on N002** — retired by D1.
- `docs/Hardware.md`'s fleet table lists N001's board as *"Raspberry Pi"* and its
  collector unit as *"(per-device)"*, while `docs/Fleet-Manifest.md` gives exact
  values. Prefer the Fleet Manifest.

## 7.8 Deployment and operational limitations

| # | Limitation |
|---|---|
| O-1 | **N001 was not SSH-reachable during this audit** — port 22 filtered on both known public addresses. Node addresses are campus DHCP and move. |
| O-2 | **Tailscale does not route from the application server** and installing it needs root. |
| O-3 | **`sudo` is not available to automated sessions on the application server** — backend changes are applied by `SIGHUP`, and several fixes (systemd unit installation, library installation, removing a stale `.bak` unit) are blocked on root. |
| O-4 | **One node (`148.213.2.153`) fail2bans the server IP after a single wrong password.** |
| O-5 | **Root filesystem was at 86 % before retention**; 37 migration backups totalled 4.9 GB. |
| O-6 | **`docker system prune` must never be run on this host** — all images and both volumes belong to running OpenWebUI containers. |
| O-7 | **Two near-identical frontend trees** (`frontend/`, `frontend-src/`) distinguished only by directory name — it is easy to edit the wrong one. |
| O-8 | **N002 has been `registered` since commissioning**, uploading nothing while buffering ~5,700 rows/day. A decision is required: commission it, or accept unbounded growth. |

## 7.9 Future work

Ordered by consequence, drawn from the repository roadmap and this audit.

1. **Bring both collectors under version control.** The one component whose source of truth is a device.
2. **Emit the canonical measurement contract** (`interval_energy_kwh`, `interval_seconds`, `energy_source`) from the collectors, closing ADR-0007.
3. **Fix the sync head-of-line block** — it is live and unbounded.
4. **Repair and calibrate N003's ADS1256 front end**, then run the Shelly-vs-ADS comparison (Q-07) — the single most valuable missing experiment.
5. **Calibrate the current channels** and record the procedure.
6. **Order the collector `After=time-sync.target`** to close the wrong-`captured_at` hazard (M-11).
7. **Enter the physical ratings** (panel breaker, CT) so the threshold chain reaches its first tier.
8. **Move backups off the application server.**
9. **Execute the recovery validation plan** V1 → V2 → V3 → V8 → V4 → V5A → V9 → V7 → V5B, and decide on hardware at the V5-Phase-B decision point.
10. **Roll the Recovery Manager out to N001.**
11. **Reconcile the documentation** against the ten contradictions in §7.7.
12. **Make `test_energy_aggregate` and `test_deployment_lifecycle` hermetic.**
13. **Add a frontend test suite; extract screens out of `App.tsx`.**
14. **Weather as an exogenous forecasting feature** — HVAC dominates campus load in Colima.
15. **Per-building models** once more than one building is genuinely instrumented.
16. **Reconcile a campaign against a utility bill** using `meter_energy_kwh`.
17. **Retire `/api/edge/heartbeat`** once the fleet has converged.
18. **Produce a sourceable BOM and hardware photographs.**
19. **Rotate the credentials** exposed in plaintext on 2026-07-26.
20. **Decide N002's long-term commission state.**

---

# PHASE 8 — EVIDENCE INDEX

Mapping from thesis-relevant subject to the best available evidence. Confidence
reflects how directly the claim can be checked by a third party.

| SUBJECT | PRIMARY SOURCE | SECONDARY SOURCE | CURRENT? | CONFIDENCE |
|---|---|---|---|---|
| System architecture, tiers | `docs/Architecture.md` | `backend/docs/ARCHITECTURE.md`, `docs/diagrams/README.md` | Yes (auth section stale) | **High** |
| Backend structure and routers | Live OpenAPI at `:8010/openapi.json` | `docs/Backend.md`, `docs/API.md` (CI-verified) | Yes | **High** |
| Route count (90 ops / 85 paths) | Live OpenAPI | `docs/API.md` | Yes | **High** |
| Database schema and row counts | Live `energy_platform.db` (read-only) | `docs/Database.md` (figures stale) | Yes | **High** |
| The five-concept model | ADR-0001 | `backend/docs/ARCHITECTURE.md` §2 | Yes | **High** |
| Deployment lifecycle semantics | `deployment_statuses` table | `backend/docs/ARCHITECTURE.md` §5 | Yes | **High** |
| Node commission lifecycle | `node_commission_states` table | `backend/docs/ARCHITECTURE.md` §4 | Yes | **High** |
| Measurement contexts | `measurement_contexts` table (7 rows) | ADR-0003, migration 014 | Yes | **High** |
| Attribution algorithm and reason codes | `app/services/attribution.py` | ADR-0004, `ARCHITECTURE.md` §7 | Yes | **High** |
| Attribution defects (14,949 rows) | `monitoring/evidence/affected-rows-20260806_142730.md` | Live DB (re-verified) | Yes | **High** |
| Deployment-window mismatch (75 % / 99.9 %) | ADR-0006 | — | Historical, quantified | **High** |
| `energy_kwh` two eras, ~400× KPI error | `measurement_eras` table `notes` | ADR-0007 | Yes | **High** |
| **Canonical contract unimplemented** | `SELECT energy_source, COUNT(*) FROM energy_readings` → `(None, 290439)` | ADR-0007, `docs/Collector.md` | Yes | **High** |
| **Authentication implemented and enforcing** | `backend/monitoring_config.json`, `nodes.auth_token_hash`, migration 013 | `app/db/node_auth.py`, `app/services/ingest_gate.py` | **Yes — supersedes the docs** | **High** |
| Identity-collision incident | `monitoring/evidence/identity-collision-20260806_134531.md` | `node_identity_violations` (12,278 rows) | Historical | **High** |
| Filesystem-readonly false alarm | `monitoring/evidence/filesystem-readonly-20260806_134531.md` | `monitor_alerts` (5 rows, 4 EMERGENCY) | Historical | **High** |
| Monitoring rules (42) | `grep -c '@rule(' backend/app/monitoring/*.py` | `docs/Monitoring.md` (says 39) | Yes | **High** |
| Alerting policy and the four principles | `docs/Monitoring.md` | `CHANGELOG.md` 1.1.0 | Yes | **High** |
| Alert-flood numbers (1,386 / 962 / 404-of-472) | `CHANGELOG.md` 1.1.0, `docs/Monitoring.md` | `monitor_notification_outbox` (2,165 delivered, 31 failed) | Historical | **High** |
| Alert lifecycle and current state | `monitor_alerts` (675 rows, 1 open) | `docs/Monitoring.md` | Yes | **High** |
| Threshold resolution chain | `app/monitoring/thresholds.py` | `docs/Monitoring.md` | Yes, but **degraded** — all ratings NULL | **High** |
| Collector behaviour and intervals | `/opt/energy-node/app/collector.py` on N002; `node.env` | `docs/Collector.md`, `docs/Energy-Node-Package.md` | Yes | **High** |
| **Production nodes use Shelly, not ADS1256** | `SHELLY_EM_URL` in the collector on N002; `SPI: none` in the manifest | `monitoring/evidence/node03-audit-*.md` | **Yes — supersedes the docs** | **High** |
| ADS1256 architecture and configuration | `/home/theblackdie/udec-edge/{drivers,acquisition,engine,processing,sources}/` on N003 | — **not in the repository** | Yes | **High** |
| **Uncalibrated current channel** | `processing/electrical.py` on N003 (`CURRENT_SCALE = 1.0`) | — | Yes | **High** |
| **Non-time-aligned power factor** | `engine/measurement.py` + `processing/electrical.py` on N003 | — | Yes | **High** |
| ADS1256 dead — STATUS `0x00` | Session of 2026-08-13 | Live DB voltage collapse 128.64 V → 0.796 V | Yes | **High** |
| Fleet inventory and drift | `docs/Fleet-Manifest.md` (2026-08-07) | Direct SSH verification (N002, N003) | Yes for N002/N003; **N001 unverified** | **High / Medium** |
| Reference node build v2.1 | `docs/Energy-Node-Package.md` | `sha256sum` on N002 | Yes | **High** |
| Fleet convergence and buffer preservation | `docs/P2-Simplification-Audit.md` D2 | `docs/Fleet-Manifest.md` | Historical | **High** |
| Networking subsystem | `edge/node/net/README.md` | Byte-identical copies on N002 and N003 | Yes | **High** |
| AP fallback behaviour | `edge/node/net/README.md` | — | Yes | **Medium** (not exercised in this audit) |
| Recovery gaps and power events | `edge/node/hardening/docs/recovery-validation.md` | Git history 2026-08-10 → 08-11 | Yes | **High** |
| Recovery Manager on N002 | Git commits `1dc3df5`…`7a32760` | `make test-node` (42 tests) | Yes | **High** |
| ML algorithms and their real behaviour | `backend/app/services/ml_engine.py` (read line by line) | `docs/AI.md` (**two inaccuracies**) | **Yes — supersedes the docs** | **High** |
| Forecast confidence method | `backend/app/services/model_confidence.py` | — | Yes | **High** |
| Threshold anomaly rules | `backend/app/services/anomaly_engine.py` | `docs/AI.md` | Yes | **High** |
| Analytics scope enforcement | `backend/app/db/scope.py` | ADR-0003, invariant INV-09 | Yes | **High** |
| Cost engine and GDMTH tariff | `tariff_periods` table (7 rows) | `runtime_platform_settings.json`, `app/services/cost_engine.py` | Yes | **High** |
| Frontend modules | `frontend/src/App.tsx` navigation array | `docs/Frontend.md` | Yes | **High** |
| Smart-plug architecture and ownership | `docs/Smart-Plug-Architecture.md`, `edge/CHANGELOG.md` | Live `smart_plugs` table (4 rows) | Yes | **High** |
| Smart-plug measurements | Live `smart_plug_readings` (152,493 rows) | `docs/Smart-Plugs.md` (figure stale) | Yes | **High** |
| Migration discipline and 16 invariants | `backend/docs/ARCHITECTURE.md` §11–12 | ADR-0005, `schema_migrations` (14 rows) | Yes | **High** |
| Test suites and counts | `make test` re-run 2026-08-13 → 524 checks | `README.md` (says 449) | **Yes — supersedes the docs** | **High** |
| CI-exposed defects | `CHANGELOG.md` 1.2.0 | `.github/workflows/` | Historical | **High** |
| N003 prototype dataset | Live DB (120,361 rows) | `deployment_week.csv` on N003 (120,103 rows) | Historical, retained | **High** |
| N001 production statistics | Live DB aggregates | — | Yes | **High** |
| Development timeline | `schema_migrations.applied_at` + git log + `CHANGELOG.md` | ADR dates | Yes | **High** for 2026-07 onward; **Medium** for May–June (squashed into one commit) |
| Project provenance / thesis framing | `edge/HANDOFF-raspberry-pi.md`, `README.md` "Research context" | `docs/prototype/README.md` | Yes | **High** |
| CT ratings per node | `docs/Fleet-Manifest.md` | User statement 2026-08-13 | Yes | **Medium** — contradicted by N001's mean current |
| CT part numbers, burden, wiring | — | — | — | **None — no evidence exists** |
| Calibration procedure | — | — | — | **None — no evidence exists** |
| Forecast accuracy | — | — | — | **None — never measured** |
| Energy savings / efficiency benefit | — | — | — | **None — never measured or claimed** |

---

# Questions Requiring Diego's Confirmation

These cannot be determined from the repository, the database or the nodes. They
require the project author's personal knowledge. **They are not answered here.**

## Hardware and instrumentation

1. What are the **CT clamps** on each node — manufacturer, model, turns ratio,
   burden resistance, accuracy class? Nothing in the repository or on any node
   records this.
2. N001's deployment-4 series has a **mean current of 195.7 A** while
   `docs/Fleet-Manifest.md` records a **120 A** CT rating for that node. Is the
   manifest rating wrong, is the CT operating out of range, or is `current` a
   three-phase sum against a per-phase rating?
3. How is **voltage sensed on N003** — a resistive divider, a potential
   transformer, or the Shelly? What is the ratio, and what produced the three
   `VOLTAGE_SCALE` constants (132.3452, 130.4466, 130.4163)?
4. Was there a **calibration procedure** for those voltage constants — against
   what reference, on what date, with what uncertainty?
5. **Was the current channel ever intended to be calibrated?** `CURRENT_SCALE`
   is `1.0` on all three phases. Was a calibration planned and never done, or
   was the current path abandoned before calibration?
6. Is there **signal conditioning** between the CTs and the ADS1256 — burden
   resistors, bias network, anti-alias filtering? `docs/Hardware.md` shows an
   "AFE" block in a diagram with no values.
7. What **PSU, enclosure and mounting** is used at each site?
8. Do **photographs** of the installed hardware exist anywhere outside the
   repository?

## Sites and measurement campaigns

9. **What building did N003 actually measure between 2026-05-13 and
   2026-06-20?** Its own device row says *"UdeC data center - first
   deployment"*, but the platform attributes it to nothing. This is the
   project's largest real dataset (120,361 readings) and its site is unrecorded.
10. **What building did N001's deployment 4 actually measure?** It is attributed
    to building 8, `Edificio de prueba`, which is flagged as a development
    placeholder. 118,620 readings — the principal production series — depend on
    this answer.
11. Are **`Edificio Principal Prueba`** (building 9) and **`Edificio Principal
    2.0`** (building 10) real, distinct buildings, and what are their real
    names? Both were created ad hoc from the deployment form.
12. What is **deployment 7's campaign** measuring? Its note reads *"Despliegue
    temporal para comparación de cargas en periodos de ingreso"* — what is being
    compared, and against what?
13. Why does N001 have only **38 distinct measurement days across a ~60-day
    span**? Are the missing days outages, node relocation, or something else?
14. Deployment 6's series has a **mean power factor of 0.512** — was this a known
    condition of that installation, or is it a measurement problem?
15. Should the **4,499 all-zero N003 rows currently stored as `production` and
    attributed to building 8** be reclassified? They are artifacts of a dead ADC
    and are the only artifacts in the database carrying a production label.

## Design intent and history

16. **Why was the ADS1256 path abandoned in favour of the Shelly Pro 3EM?** The
    conversion is datable to 2026-07-24 from the backup files on N003, but no
    document records the decision or its reasoning. This is a central engineering
    decision for the thesis and is the one with no written record.
17. **Was the ADS1256 always intended as a research strand**, or was it the
    intended production instrument that was superseded?
18. **Why was 15 seconds chosen** as the sampling interval? Was any other cadence
    evaluated?
19. Was the **Raspberry Pi** compared against any alternative edge platform?
20. What happened during the **2026-06-17 frontend recovery**
    (*"Rescue current frontend work before recovery"*)? Was work lost?
21. The backend, edge and monitoring work from May–July 2026 exists in git as a
    **single squashed commit**. Does an earlier version history exist anywhere —
    the two legacy repositories moved to `~/energy-platform-legacy-git/`, or
    elsewhere?

## Data classification

22. ADR-0006 records that **N003's May–June data must never be retroactively
    attributed** and that **building 8 is a placeholder** as facts *established
    with the platform owner*. Please confirm both, since they are testimony
    rather than derived evidence and several conclusions rest on them.
23. Is the `laboratory` classification for N003's May–June set still the right
    one, given it appears to be real load at a real site?
24. Readings between **2026-07-03 15:32 and 2026-07-25 00:01** on N001 fall in a
    gap between the two declared `measurement_eras`. What did `energy_kwh` mean
    in that window?

## Scope and thesis framing

25. **What is the thesis's actual research question?** The README frames it as
    *"whether low-cost edge hardware plus disciplined data modelling can produce
    measurements trustworthy enough for operational and financial decisions"* —
    is that the thesis's framing, or the repository's?
26. Is the **ADS1256 custom acquisition** intended to be a chapter of the thesis?
    If so, it needs the answers to Q3–Q6 and Q16, and its current non-functional
    state should be stated.
27. Should the **institution be named**? `docs/Networking.md` states that no real
    addresses or hostnames appear in the repository, but `docs/Fleet-Manifest.md`
    contains node passwords and the AP scheme, and the README names Universidad
    de Colima.
28. Is there an **institutional or academic supervisor requirement** that
    constrains what may be published — public IPs, credentials, building names?
29. Are there **prior reports, presentations or protocol documents** for this
    project that are not in the repository and that the thesis should reconcile
    with?

## Operational

30. **Should the Telegram bot token and the three Pi passwords be rotated?** They
    were pasted in plaintext in a 2026-07-26 session, and node passwords appear
    in a document in a public repository.
31. Is **N002 intended to be commissioned**, or to stay `registered`? Its buffer
    grows ~5,700 rows/day behind a correct 403 and nothing alerts on it.
32. Is there a plan and a date for **physical access to N003** to diagnose the
    dead ADS1256 boards?
33. **Why is N001's SSH port 22 filtered** on its current public address? It was
    reachable on 2026-08-10 and is not now, while its heartbeats continue
    normally.
34. Are there **`.md` files, notebooks or reports on N001** that this audit could
    not reach? N002 and N003 carry nothing that is not already in the repository,
    but N001 was unreachable and is the only node with an
    `energy-node-maintenance-ap` unit.
35. Do **measurement records exist outside the platform** — spreadsheets, utility
    bills, a reference-meter log — that could be used to validate absolute
    accuracy? This is the single largest gap in the project's evidence, and the
    thesis would be materially stronger with any such comparison.

---

## Cross-reference — the `Q-nn` tags used earlier in this document

Phases 2, 4, 5, 6 and 7 tag open questions inline as `Q-01` … `Q-14`. They map to
the numbered questions above as follows.

| Tag | Raised in | Question |
|---|---|---|
| **Q-01** | §4 D-01 | **19** — was the Raspberry Pi compared against any alternative edge platform? |
| **Q-02** | §4 D-07 | **18** — why was 15 seconds chosen? |
| **Q-03** | §2.B, §4 D-23, §6.4 | **3** and **4** — how is voltage sensed on N003, and what produced the three `VOLTAGE_SCALE` constants? |
| **Q-04** | §5 V-T, §4 D-23, §7 M-1 | **4** and **35** — was there a calibration procedure, and do any external measurement records exist to validate absolute accuracy? |
| **Q-05** | §2.I.3, §4 D-12 | **36** *(added below)* |
| **Q-06** | §2.J.8, §6.2 T-2 | **15** — should the 4,499 all-zero N003 rows stored as `production` be reclassified? |
| **Q-07** | §5 V-T | **37** *(added below)* |
| **Q-08** | §5 V-T, §6.4 | **35** — utility-bill reconciliation |
| **Q-09** | §5 V-T | **38** *(added below)* |
| **Q-10** | §5 V-T | **39** *(added below)* |
| **Q-11** | §1.7 | **34** — are there files on N001 this audit could not reach? |
| **Q-12** | §6.1 R-1, §6.4 | **2** — 195.7 A mean current against a 120 A CT rating |
| **Q-13** | §6.4 | **10** and **11** — which buildings were actually measured? |
| **Q-14** | §6.4, §7.7 C-10 | **40** *(added below)* |

## Additional questions raised by this audit

36. **Were the physical rating columns ever meant to be populated?** Migration 008
    added `panel_main_breaker_a`, `ct_max_current_a`, `nominal_voltage_v`,
    `phase_count` and the warning/critical/emergency current columns to both
    `nodes` and `deployments`. **Every one is NULL on every row.** The monitoring
    subsystem's threshold chain is designed to start from these values and
    currently never reaches its first two tiers. Entering them is a data-entry
    task, not a code change — is there a reason it has not been done?
37. **Was a Shelly-vs-ADS1256 comparison ever run, or planned?** The two
    acquisition chains have never been compared on the same load. This is the
    single most valuable missing experiment in the project and would turn the
    custom instrumentation from an implementation into a result. Was it intended?
38. **Has a whole-database restore drill ever been completed?** `restore-drill` is
    documented as gating the high-risk migrations, and ADR-0005 says *"a backup
    that has never been restored is a hypothesis, not a backup"* — but no drill
    result is recorded anywhere as evidence.
39. **Has the AP fallback, factory network reset or a real SSID change ever been
    exercised in the field?** The 46 unit tests cover the pure decision layer
    only. A recorded field test would materially strengthen the networking
    chapter.
40. **Where does the "~11.4 kW" figure for N001 come from?** It appears in
    `README.md`, `docs/AI.md` and `docs/Database.md`, but no aggregate this audit
    computed reproduces it — deployment 4 means 19.662 kW, deployment 6 means
    6.311 kW, deployment 7 means 12.944 kW. Was it a different window, a
    per-phase figure, or a different quantity?

---

*End of document. Compiled 2026-08-13 by direct inspection of the repository at
`/home/manager/energy-platform`, the live production database, the running
services, and edge nodes N002 and N003 over SSH. N001 was not reachable.*
