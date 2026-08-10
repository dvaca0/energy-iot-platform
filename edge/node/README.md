# Energy Node — on-node software

The software that runs on the Raspberry Pi field nodes. Two packages, both
previously existing **only on the nodes themselves**, with no source tree, no
version control and no CI. They were imported here verbatim on 2026-08-10 so
that changes can be tested, reviewed and rolled back.

| Package | Installed at | Purpose |
|---|---|---|
| `hardening/` | `/opt/energy-node/hardening` | Health (doctor, selftest), telemetry, canonical heartbeat, black-box boot recorder, power/UPS logging, and the recovery framework |
| `net/` | `/opt/energy-node/net` | `netd` networking supervisor, maintenance AP, web portal, tty1 appliance console |

The collector itself (`/opt/energy-node/app/collector.py`) is deliberately
**not** vendored here yet — it is authoritative production software and is
changed only under explicit approval.

## Provenance

Imported byte-for-byte from **N001** (`energy-node-001`). At import time N001
and N002 were verified identical: 84 files, and the *only* difference between
the two nodes was `net/config/network.yaml`, which is rendered per node.

The pre-import state of both nodes is archived outside git, with a SHA-256
manifest per node:

```
backups/node-packages-baseline-20260810/
  MANIFEST-n001.sha256    MANIFEST-n002.sha256
  n001-hardening-net.tar.gz    n002-hardening-net.tar.gz
```

That archive is the rollback target for anything in this directory.

## Secrets

`net/config/network.yaml` holds the maintenance-AP passphrase and is
**git-ignored**. Only `network.yaml.example`, with the passphrase redacted, is
tracked. Node identity and the backend auth token live in
`/opt/energy-node/config/node.env`, which is never vendored.

This repository is public. Nothing under `edge/node/` may contain a real
passphrase, token or password.

## Linting

These packages are excluded from `make lint`, which is scoped to
`backend/app backend/tests scripts`. That is deliberate: they were imported
unchanged, and reformatting 84 working files would destroy the diff that makes
future drift reviewable. New code written for these packages is expected to
match the surrounding style.

## Tests

Both packages ship unittest suites that run without hardware, a radio or a
network. `make test-node` runs them.

```
net/tests/          state machine, uplink selection, collector contract, config
hardening/tests/    recovery state machine, escalation ledger, boot stages
```
