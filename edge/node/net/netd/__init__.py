"""Energy Node networking subsystem (``netd``).

A self-contained, NetworkManager-integrated networking and maintenance
subsystem for Raspberry Pi Energy Nodes.

The subsystem owns *all* connectivity decisions on the node and publishes a
single, deliberately minimal fact for the rest of the appliance to consume:
whether the network is available or unavailable.  See :mod:`netd.statefile`
for that contract.

Layering (strictly downward dependencies only)::

    supervisor / portal / tui        <- entry points
        managers (wifi, ap)          <- intent
            evaluator + statemachine <- pure decision logic
                probes + nm          <- I/O adapters
                    config + models  <- data
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
