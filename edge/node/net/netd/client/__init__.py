"""Standalone client shipped to collector processes.

The module in this package is installed *outside* the ``netd`` package, next
to the collector, so the collector never imports networking code.
"""

from __future__ import annotations

__all__: list[str] = []
