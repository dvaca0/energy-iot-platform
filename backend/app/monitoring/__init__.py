"""Monitoring and alerting for the University Energy Intelligence Platform.

A self-contained subsystem: it reads the operational schema, writes only its
own six tables, and exposes its own router. Nothing outside this package needs
to change for a new check, a new threshold or a new notification channel.

Layout
------
``config``         Layered, typed configuration.
``severity``       Severity levels and their presentation.
``models``         The six monitoring tables.
``storage``        Session ownership, table creation, retention.
``rules``          The rule registry and evaluation engine.
``health``         Server probes and server rules.
``heartbeat``      Node heartbeat ingestion, liveness, node rules.
``metrics``        Electrical, plug and fleet metrics and rules.
``alerts``         Alert lifecycle: dedup, escalation, resolution.
``notifications``  Rendering, the durable outbox, delivery policy.
``channels``       Pluggable delivery channels.
``status``         Status snapshot and the periodic report.
``history``        Read-side queries for the alerts UI.
``scheduler``      The runtime loop and self-monitoring.
``router``         FastAPI routes.

Importing this package registers every rule as a side effect of importing the
rule modules, which is what makes the registry complete without a manual list.
"""

from __future__ import annotations

# Importing these modules is what populates the rule registry. Order does not
# matter; each module registers its own rules at import time.
from app.monitoring import health, heartbeat, metrics  # noqa: F401
from app.monitoring.config import get_config
from app.monitoring.rules import registered_rules
from app.monitoring.storage import create_tables

__all__ = ["create_tables", "get_config", "registered_rules"]

__version__ = "1.0.0"
