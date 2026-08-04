# Diagrams

Every structural diagram for the platform, in one place. All of them are
Mermaid, so GitHub renders them inline and they diff as text when the system
changes — there are no binary images to fall out of date silently.

Each diagram is also embedded in the document that owns the subject. This page
is the index.

| # | Diagram | Owning document |
|---|---|---|
| 1 | [System architecture](#1-system-architecture) | [Architecture.md](../Architecture.md) |
| 2 | [Database](#2-database) | [Database.md](../Database.md) |
| 3 | [Deployment flow](#3-deployment-flow) | [Deployment.md](../Deployment.md) |
| 4 | [Collector flow](#4-collector-flow) | [Collector.md](../Collector.md) |
| 5 | [Heartbeat flow](#5-heartbeat-flow) | [Monitoring.md](../Monitoring.md) |
| 6 | [Monitoring pipeline](#6-monitoring-pipeline) | [Monitoring.md](../Monitoring.md) |
| 7 | [Alert pipeline](#7-alert-pipeline) | [Monitoring.md](../Monitoring.md) |
| 8 | [AI pipeline](#8-ai-pipeline) | [AI.md](../AI.md) |
| 9 | [Boot process](#9-boot-process) | [Deployment.md](../Deployment.md) |
| 10 | [Node recovery](#10-node-recovery) | [Recovery.md](../Recovery.md) |
| 11 | [Data synchronisation](#11-data-synchronisation) | [Collector.md](../Collector.md) |
| 12 | [Network topology](#12-network-topology) | [Networking.md](../Networking.md) |

---

## 1. System architecture

Three tiers: measurement at the edge, storage and interpretation at the centre,
presentation and alerting at the surface. The monitoring scheduler is drawn
outside the API process because that separation is deliberate — see
[Architecture.md](../Architecture.md).

```mermaid
flowchart LR
  subgraph EDGE["Edge tier — Raspberry Pi at the panel"]
    direction TB
    CT["CT clamps<br/>+ ADS1256 ADC"]
    COL["collector<br/>poll 15 s"]
    BUF[("local SQLite<br/>buffer, 7 d")]
    HB["heartbeat agent<br/>every 45 s"]
    SP["Shelly plugs<br/>Gen4 RPC"]
    CT --> COL
    SP --> COL
    COL --> BUF
    BUF -->|"sync 60 s"| OUT((" "))
    HB --> OUT
  end

  subgraph CORE["Core tier — application server"]
    direction TB
    API["FastAPI / gunicorn :8010<br/>90 routes"]
    ING["ingest → authenticate<br/>→ authorise → classify<br/>→ attribute"]
    DB[("SQLite WAL<br/>33 tables")]
    SVC["services<br/>cost · ML · anomaly<br/>reports · attribution"]
    SCHED["monitoring scheduler<br/>separate process"]
    API --> ING --> DB
    DB --> SVC --> API
    SCHED --> DB
  end

  subgraph SURF["Surface tier"]
    direction TB
    WEB["React 19 dashboard<br/>:5174"]
    TG["Telegram<br/>alert channel"]
    PDF["PDF / XLSX<br/>reports"]
  end

  OUT --> API
  API --> WEB
  SCHED --> TG
  SVC --> PDF

  classDef edge fill:#1e3a5f,stroke:#3B82F6,color:#e6edf7
  classDef core fill:#1c2b4a,stroke:#60a5fa,color:#e6edf7
  classDef surf fill:#3b2f1a,stroke:#F59E0B,color:#f7f0e6
  class CT,COL,BUF,HB,SP edge
  class API,ING,DB,SVC,SCHED core
  class WEB,TG,PDF surf
```

---

## 2. Database

The domain schema. Monitoring owns six further tables in its own namespace
(`monitor_*`) and deliberately modifies none of these; migration shadow tables
(`*_pre_m*`) are omitted.

The structural point is that **identity, authorisation, lifecycle and
attribution are four separate concerns** with four separate owners. See
[ADR-0001](../../backend/docs/adr/0001-separate-identity-health-lifecycle-attribution.md).

```mermaid
erDiagram
  DELEGATIONS    ||--o{ CAMPUSES : contains
  CAMPUSES       ||--o{ ORGANIZATIONAL_UNITS : contains
  CAMPUSES       ||--o{ BUILDINGS : contains
  ORGANIZATIONAL_UNITS ||--o{ BUILDINGS : occupies
  BUILDINGS      ||--o{ ELECTRICAL_PANELS : has
  BUILDINGS      ||--o{ DEPLOYMENTS : "hosts"

  NODES          ||--|| NODE_COMMISSION_STATES : "authorised by"
  NODES          ||--o{ NODE_COMMISSION_EVENTS : "audited by"
  NODES          ||--o{ DEPLOYMENTS : "installed as"

  DEPLOYMENTS    }o--|| DEPLOYMENT_STATUSES : "in"
  DEPLOYMENTS    ||--o{ DEPLOYMENT_STATUS_TRANSITIONS : "audited by"
  DEPLOYMENTS    ||--o{ ENERGY_READINGS : "attributes"
  ELECTRICAL_PANELS ||--o{ DEPLOYMENTS : "measured at"

  ENERGY_READINGS }o--|| MEASUREMENT_CONTEXTS : "classified as"
  ENERGY_READINGS }o--|| MEASUREMENT_ERAS : "interpreted by"

  SMART_PLUGS    ||--o{ SMART_PLUG_READINGS : produces
  BUILDINGS      ||--o{ SMART_PLUGS : "assigned to"
  NODES          ||--o{ SMART_PLUGS : "collected by"

  DELEGATIONS {
    int  id PK
    text name
  }
  CAMPUSES {
    int  id PK
    int  delegation_id FK
    text name
  }
  BUILDINGS {
    int  id PK
    int  campus_id FK
    text name
    bool is_placeholder
  }
  ELECTRICAL_PANELS {
    int   id PK
    int   building_id FK
    float rated_current_a
  }
  NODES {
    int  id PK
    text code UK
    text name
    text status
    ts   last_sync
  }
  NODE_COMMISSION_STATES {
    int  node_id PK
    bool is_monitored
    bool may_upload
  }
  DEPLOYMENTS {
    int  id PK
    int  node_id FK
    int  building_id FK
    int  panel_id FK
    int  status_id FK
    ts   activated_at
    ts   closed_at
  }
  DEPLOYMENT_STATUSES {
    int  id PK
    text code
    bool is_operational
  }
  ENERGY_READINGS {
    int   id PK
    int   node_id FK
    int   building_id FK
    int   deployment_id FK
    int   context_id FK
    ts    timestamp
    float power_kw
    float interval_energy_kwh
    float interval_seconds
    text  energy_source
    float voltage
    float current
    float power_factor
    float frequency_hz
  }
  MEASUREMENT_CONTEXTS {
    int  id PK
    text code
    bool counts_as_production
  }
  MEASUREMENT_ERAS {
    int  id PK
    text code
    text energy_kwh_meaning
  }
  SMART_PLUGS {
    int  id PK
    text device_id UK
    text mac
    int  building_id FK
    int  node_id FK
  }
  SMART_PLUG_READINGS {
    int   id PK
    int   plug_id FK
    ts    timestamp
    float power_w
    float energy_wh
  }
  TARIFF_PERIODS {
    int   id PK
    text  tariff
    text  period
    float rate_mxn_kwh
  }
```

---

## 3. Deployment flow

How a code change reaches production. There is no container runtime and no
orchestrator: this is systemd, gunicorn and a static build, and the flow is
written to match what actually happens rather than an idealised pipeline.

```mermaid
flowchart TD
  START([change authored]) --> LINT{"ruff · black --check<br/>mypy · eslint · tsc"}
  LINT -->|fail| FIX[fix] --> LINT
  LINT -->|pass| TEST{"6 backend suites<br/>plain python"}
  TEST -->|fail| FIX
  TEST -->|pass| KIND{what changed?}

  KIND -->|backend code| BE1["git pull on server"]
  BE1 --> BE2{"schema change?"}
  BE2 -->|yes| MIG["migrations.runner --shadow<br/>then --apply<br/>invariants checked"]
  BE2 -->|no| BE3
  MIG --> BE3["SIGHUP the gunicorn master"]
  BE3 --> BE4["workers re-import,<br/>old workers retire<br/>— no dropped connection"]

  KIND -->|frontend code| FE1["npm run build in frontend-src/"]
  FE1 --> FE2["review on :5175"]
  FE2 --> FE3{approved?}
  FE3 -->|no| FIX
  FE3 -->|yes| FE4["npm run build in frontend/<br/>→ frontend/dist"]
  FE4 --> FE5["static server serves it<br/>Cache-Control: no-store<br/>— no restart needed"]

  KIND -->|monitoring code| MO1["restart the scheduler process<br/>separately from the API"]

  KIND -->|collector code| ED1["push to each Pi"]
  ED1 --> ED2["systemctl restart the<br/>collector unit"]
  ED2 --> ED3["buffer replays<br/>anything missed"]

  BE4 --> VERIFY
  FE5 --> VERIFY
  MO1 --> VERIFY
  ED3 --> VERIFY
  VERIFY{"/health green ·<br/>readings still rising ·<br/>heartbeats current"}
  VERIFY -->|no| ROLL["roll back: git revert,<br/>migration .down.sql"]
  VERIFY -->|yes| DONE([released])

  classDef gate fill:#3b2f1a,stroke:#F59E0B,color:#f7f0e6
  classDef ok fill:#14331f,stroke:#22C55E,color:#e6f7ec
  classDef bad fill:#3a1b1b,stroke:#EF4444,color:#f7e6e6
  class LINT,TEST,KIND,BE2,FE3,VERIFY gate
  class DONE,BE4,FE5,ED3 ok
  class ROLL,FIX bad
```

---

## 4. Collector flow

One sampling cycle on a node. The important property is that **nothing in this
loop can lose a measurement because the network is down** — the buffer is
written before the upload is ever attempted.

```mermaid
flowchart TD
  T([tick — every 15 s]) --> READ["read ADS1256 channels<br/>V, I per phase"]
  READ --> OK{read valid?}
  OK -->|no| LOGERR["log, increment<br/>error counter"] --> T
  OK -->|yes| DERIVE["derive power_kw,<br/>power factor, frequency"]
  DERIVE --> ENERGY["compute interval energy"]
  ENERGY --> SRC{"how was it obtained?"}
  SRC -->|"device register differenced"| CD["energy_source =<br/>counter_delta"]
  SRC -->|"power integrated over interval"| PI["energy_source =<br/>power_integral"]
  SRC -->|"device reported it directly"| MS["energy_source =<br/>measured"]
  CD --> PLUGS
  PI --> PLUGS
  MS --> PLUGS
  PLUGS["poll Shelly plugs<br/>over Gen4 RPC"] --> BUF[("append to local<br/>SQLite buffer")]
  BUF --> T

  BUF -.->|"independent 60 s loop"| SYNC
  SYNC["batch unsent rows"] --> POST["POST /api/v1/measurements/batch"]
  POST --> RESP{2xx?}
  RESP -->|yes| MARK["mark rows sent"] --> PRUNE["prune rows older<br/>than 7 days"]
  RESP -->|no| KEEP["leave rows unsent,<br/>retry next cycle"]
  KEEP -.-> SYNC

  classDef store fill:#1e3a5f,stroke:#3B82F6,color:#e6edf7
  classDef bad fill:#3a1b1b,stroke:#EF4444,color:#f7e6e6
  class BUF store
  class LOGERR,KEEP bad
```

---

## 5. Heartbeat flow

Health reporting travels on its own path, on its own schedule. That is what
makes "the node is down" distinguishable from "the node is up but not
measuring" — the two failures produce different evidence.

```mermaid
sequenceDiagram
  autonumber
  participant HB as heartbeat agent<br/>(on the Pi)
  participant OS as Pi kernel / sysfs
  participant API as FastAPI :8010
  participant DB as SQLite
  participant SCH as monitoring scheduler

  loop every 45 s
    HB->>OS: uptime, disk, CPU temperature
    HB->>OS: throttle flags (undervoltage, throttled)
    HB->>OS: filesystem read-only check
    HB->>HB: buffer depth, collector liveness,<br/>software version
    HB->>API: probe internet + measure latency
    HB->>API: POST /api/edge/heartbeat<br/>(~50 fields)
    API->>DB: insert monitor_node_heartbeats
    API->>DB: upsert monitor_node_heartbeat_latest
    API-->>HB: 200
  end

  Note over HB,API: A failed POST is not retried — the next<br/>tick supersedes it. Heartbeats are a<br/>liveness signal, not a data series.

  loop scheduler cycle
    SCH->>DB: read latest heartbeat per node
    alt last heartbeat older than liveness window
      SCH->>SCH: node.offline fires
    else fields out of range
      SCH->>SCH: node.* rules evaluate<br/>(temperature, disk, undervoltage…)
    end
  end
```

---

## 6. Monitoring pipeline

One scheduler cycle. 39 rules across nine subsystems, each returning a verdict
plus the evidence behind it.

```mermaid
flowchart TD
  TICK([scheduler tick]) --> LOCK{"flock acquired?"}
  LOCK -->|no| EXIT([another instance owns it — exit])
  LOCK -->|yes| GATHER

  GATHER["gather evidence"] --> G1["server probes<br/>disk, memory, load, clock"]
  GATHER --> G2["database probes<br/>size, WAL, integrity"]
  GATHER --> G3["latest heartbeat per node"]
  GATHER --> G4["electrical metrics<br/>per operational deployment"]
  GATHER --> G5["smart-plug fleet state"]

  G1 & G2 & G3 & G4 & G5 --> EVAL["evaluate 39 rules"]

  EVAL --> GATE{"deployment gate:<br/>is_monitored · may_upload<br/>· is_operational"}
  GATE -->|"node has no operational deployment"| SKIP["rule reports<br/>'cannot evaluate' — never alerts"]
  GATE -->|operational| THRESH["resolve threshold:<br/>panel rating → CT rating →<br/>learned baseline → fallback"]

  THRESH --> VERDICT{condition met?}
  VERDICT -->|no| CLEAR["record pass"]
  VERDICT -->|yes| SUSTAIN{"held for the<br/>sustain window?"}
  SUSTAIN -->|no| PEND["pending — no alert yet"]
  SUSTAIN -->|yes| ALERT["→ alert pipeline"]

  CLEAR --> HIST[("write monitor history")]
  SKIP --> HIST
  PEND --> HIST
  ALERT --> HIST
  HIST --> SELF["self-monitor:<br/>record own tick"]
  SELF --> RETAIN["apply retention"] --> DONE([cycle complete])

  classDef gate fill:#3b2f1a,stroke:#F59E0B,color:#f7f0e6
  classDef ok fill:#14331f,stroke:#22C55E,color:#e6f7ec
  class LOCK,GATE,VERDICT,SUSTAIN gate
  class CLEAR,DONE ok
```

> [!IMPORTANT]
> The deployment gate is the single most important box on this diagram. The
> first production run sent **1,386 Telegram messages in four days**, and 1,288
> of them came from nodes with no operational deployment. See
> [Monitoring.md § Alerting policy](../Monitoring.md#alerting-policy).

---

## 7. Alert pipeline

What happens between "a rule fired" and "a human is interrupted" — and, most of
the time, what stops the interruption from happening.

```mermaid
stateDiagram-v2
  direction LR
  [*] --> Evaluating

  Evaluating --> Pending: condition true
  Pending --> Evaluating: cleared before<br/>sustain window elapsed
  Pending --> Firing: held for the<br/>full sustain window

  Firing --> Deduplicated: an identical alert<br/>is already open
  Deduplicated --> Firing: same alert,<br/>occurrence counted

  Firing --> Routed
  state Routed {
    direction LR
    [*] --> Severity
    Severity --> ReportOnly: INFO / WARNING
    Severity --> Paging: CRITICAL / EMERGENCY
    ReportOnly --> [*]: appears in the hourly<br/>report only
    Paging --> [*]: queued to the outbox
  }

  Routed --> Outbox: paging alerts only
  Outbox --> Delivered: Telegram accepted
  Outbox --> Outbox: delivery failed —<br/>retained and retried
  Delivered --> Open

  Open --> Escalated: still true after<br/>the escalation window
  Escalated --> Open

  Open --> Resolving: condition absent
  Resolving --> Open: reappeared inside<br/>the hysteresis window
  Resolving --> Resolved: absent for the<br/>full hysteresis window
  Resolved --> [*]

  note right of Outbox
    The outbox never discards a message.
    A Telegram outage delays delivery;
    it does not lose the alert.
  end note

  note right of Resolving
    Hysteresis exists because a value
    oscillating on a threshold would
    otherwise send two messages per
    crossing, forever.
  end note
```

---

## 8. AI pipeline

Three scikit-learn models plus an optional LLM narration layer. Everything
numeric is computed locally; the LLM only writes prose about numbers it is
given, and the platform is fully functional with `LLM_ENABLED=0`.

```mermaid
flowchart TD
  RAW[("energy_readings")] --> SCOPE{"analytics scope filter"}
  SCOPE -->|"excludes bench-context and<br/>non-production readings"| DS["build_hourly_dataset<br/>default 168 h"]
  SCOPE -.->|excluded| DROP["bring-up / bench data<br/>never reaches a model"]

  DS --> FEAT["features: hour of day,<br/>day of week, lagged demand,<br/>rolling means"]

  FEAT --> RF["RandomForestRegressor<br/>demand + cost forecast"]
  FEAT --> IF["IsolationForest<br/>anomaly detection"]
  FEAT --> KM["KMeans<br/>building load profiles"]

  RF --> GUARD1{"≥ 7 days of history?"}
  GUARD1 -->|no| UNTRAINED["trained: false —<br/>surfaced honestly in the UI"]
  GUARD1 -->|yes| FC["forecast series"]

  IF --> AN["scored anomalies"] --> GRP["group_anomaly_events<br/>10-minute gap merge"]
  KM --> GUARD2{"enough operational<br/>buildings?"}
  GUARD2 -->|no| UNTRAINED
  GUARD2 -->|yes| CL["cluster assignments"]

  FC --> CONF["model_confidence<br/>backtesting where history allows"]
  CONF --> OUT
  GRP --> OUT
  CL --> OUT
  OUT["/api/ai-center"] --> UI["AI Centre screen"]

  OUT --> LLMGATE{"LLM_ENABLED?"}
  LLMGATE -->|"0 — default-safe"| UI
  LLMGATE -->|1| GEM["Gemini: narrative summary<br/>over the computed figures"]
  GEM --> UI

  classDef bad fill:#3a1b1b,stroke:#EF4444,color:#f7e6e6
  classDef warn fill:#3b2f1a,stroke:#F59E0B,color:#f7f0e6
  class DROP,UNTRAINED warn
```

> [!NOTE]
> The scope filter is not a refinement. Building profiles trained on bench data
> were the worst single source of wrong analytics in this platform's history —
> see [ADR-0006](../../backend/docs/adr/0006-legacy-deployment-dates-non-authoritative.md)
> and [AI.md § Data scope](../AI.md#data-scope).

---

## 9. Boot process

What comes up, in what order, on both tiers. Nothing here waits on anything
else across the network — a node boots and starts buffering whether or not the
server exists, and vice versa.

```mermaid
sequenceDiagram
  autonumber
  participant SD as systemd (server)
  participant GU as gunicorn master
  participant WK as uvicorn worker
  participant DB as SQLite (WAL)
  participant MS as monitoring scheduler
  participant FS as static server
  participant PI as systemd (Raspberry Pi)

  rect rgba(59,130,246,0.10)
    Note over SD,FS: Application server
    SD->>GU: start energy-platform-backend.service
    GU->>WK: fork worker (-w 1)
    WK->>WK: load .env via python-dotenv
    WK->>WK: import routers, register 90 routes
    WK->>WK: import monitoring package<br/>(registers 39 rules; creates no tables)
    WK->>DB: open connection, WAL mode
    WK-->>GU: ready — /health serves 200
    SD->>FS: start energy-platform-frontend.service
    FS->>FS: serve frontend/dist, Cache-Control: no-store
    SD->>MS: start energy-platform-monitoring.service
    MS->>MS: flock — refuse to start a second instance
    MS->>DB: create monitor_* tables if absent
    MS->>MS: begin scheduler loop, record own liveness
  end

  rect rgba(245,158,11,0.10)
    Note over PI: Edge node — independent of the above
    PI->>PI: start collector unit
    PI->>PI: open local SQLite buffer
    PI->>PI: begin 15 s sample loop
    PI->>PI: begin 60 s sync loop (retries if server absent)
    PI->>PI: start heartbeat unit, 45 s loop
  end
```

---

## 10. Node recovery

The decision tree an operator follows when a node stops reporting. It is
ordered by what the evidence can distinguish, not by what is easiest to check.

```mermaid
flowchart TD
  START([node stopped reporting]) --> Q1{"heartbeats<br/>still arriving?"}

  Q1 -->|yes| Q2{"buffer depth rising?"}
  Q2 -->|yes| C1["Node alive, collector alive,<br/>upload path broken"]
  C1 --> A1["check server reachability<br/>from the node; check<br/>may_upload authorisation"]
  A1 --> R1["fix path — buffer replays<br/>automatically, no data lost"]

  Q2 -->|no| C2["Node alive, collector<br/>not producing"]
  C2 --> A2["check collector unit status;<br/>check ADC read errors"]
  A2 --> R2["restart collector unit"]

  Q1 -->|no| Q3{"node reachable<br/>on the network?"}
  Q3 -->|yes| C3["Node alive,<br/>heartbeat agent down"]
  C3 --> A3["restart heartbeat unit"]

  Q3 -->|no| Q4{"was the last heartbeat<br/>carrying a warning?"}
  Q4 -->|"undervoltage / throttled"| C4["Power supply fault"]
  C4 --> A4["replace PSU or cabling —<br/>this is the most common<br/>root cause"]
  Q4 -->|"filesystem read-only"| C5["SD card failing"]
  C5 --> A5["reflash card, restore<br/>from node image"]
  Q4 -->|"disk full"| C6["Buffer never pruned"]
  C6 --> A6["clear buffer, check<br/>retention job"]
  Q4 -->|"nothing unusual"| C7["Hard failure or<br/>site-level outage"]
  C7 --> A7["site visit: power,<br/>network, physical state"]

  R1 & R2 & A3 & A4 & A5 & A6 & A7 --> VERIFY{"readings resumed and<br/>backfill landed in the<br/>correct deployment?"}
  VERIFY -->|no| START
  VERIFY -->|yes| DONE([recovered])

  classDef ok fill:#14331f,stroke:#22C55E,color:#e6f7ec
  classDef bad fill:#3a1b1b,stroke:#EF4444,color:#f7e6e6
  class DONE,R1 ok
  class C4,C5,C7 bad
```

---

## 11. Data synchronisation

The reconciliation between a node's buffer and the central store, including the
case that makes it non-trivial: a long outage whose backfill spans a deployment
change.

```mermaid
sequenceDiagram
  autonumber
  participant COL as collector
  participant BUF as local buffer
  participant API as /api/v1/measurements/batch
  participant ATT as attribution
  participant DB as energy_readings

  Note over COL,BUF: Normal operation
  COL->>BUF: append sample (captured_at = now)
  loop every 60 s
    BUF->>API: batch of unsent rows
    API->>API: authenticate node
    API->>API: authorise — may_upload?
    API->>ATT: classify + attribute each row
    ATT->>ATT: resolve deployment by the row's<br/>own captured_at, not by newest id
    ATT->>DB: insert with building_id,<br/>deployment_id, context_id
    API-->>BUF: 200 — mark rows sent
  end

  Note over COL,DB: Outage and replay
  COL->>BUF: append (server unreachable)
  BUF->>BUF: rows accumulate — up to 7 days
  BUF--xAPI: sync fails, rows stay unsent
  Note right of BUF: Backpressure is the only<br/>symptom; no sample is dropped.

  BUF->>API: server returns — replay backlog
  API->>ATT: rows carry their original captured_at
  alt backfill spans a deployment change
    ATT->>ATT: earlier rows → the deployment<br/>that was active when captured
    ATT->>ATT: later rows → the current deployment
  end
  ATT->>DB: each row attributed to its own moment
  API-->>BUF: 200 — prune beyond retention
```

> [!WARNING]
> Attributing a whole batch to the newest deployment id — rather than to each
> row's own `captured_at` — silently and permanently files buffered data against
> the wrong building. This was a real defect, found in the 2026-07-26 audit, and
> is the reason [ADR-0004](../../backend/docs/adr/0004-immutable-timestamp-attribution.md)
> exists.

---

## 12. Network topology

How the tiers actually reach each other. Node access is over the site's public
NAT address rather than the overlay network, which matters when you are trying
to reach one at 3 a.m.

```mermaid
flowchart TB
  subgraph SITE["Monitored site"]
    direction TB
    PANEL["electrical panel"]
    subgraph LAN["site LAN"]
      N1["energy-node-001<br/>Raspberry Pi"]
      N2["energy-node-002<br/>Raspberry Pi"]
      N3["energy-node-003<br/>Raspberry Pi"]
      PLUGS["Shelly Plug US Gen4 ×4<br/>Wi-Fi, Gen4 RPC over HTTP"]
    end
    NAT["site router / NAT"]
    PANEL -.->|CT clamps| N1
    PANEL -.->|CT clamps| N3
    N1 & N2 & N3 --- NAT
    PLUGS --- NAT
    N1 -.->|"polls plugs on the LAN"| PLUGS
  end

  INET(("Internet"))
  NAT ---|"outbound HTTPS —<br/>nodes initiate every connection"| INET

  subgraph SRV["Application server"]
    direction TB
    FW["host firewall"]
    B[":8010 gunicorn — API + ingest"]
    F[":5174 static server — production UI"]
    S[":5175 static server — staging UI"]
    FW --- B & F & S
  end

  INET --- FW
  OPS["operator browser"] --- F
  TGAPI(("Telegram Bot API")) 
  B -.->|"outbound only"| TGAPI
  CFE(("CFE tariff site"))
  B -.->|"scheduled scrape"| CFE

  classDef edge fill:#1e3a5f,stroke:#3B82F6,color:#e6edf7
  classDef core fill:#1c2b4a,stroke:#60a5fa,color:#e6edf7
  classDef ext fill:#2b2b2b,stroke:#94A3B8,color:#e8e8e8
  class N1,N2,N3,PLUGS edge
  class B,F,S,FW core
  class INET,TGAPI,CFE ext
```

> [!NOTE]
> Every connection is initiated **outbound from the node**. No inbound port is
> forwarded to a Pi for the platform's own operation, so a node behind an
> ordinary consumer NAT needs no network configuration to work. Operator SSH
> access is a separate concern — see [Networking.md](../Networking.md).
