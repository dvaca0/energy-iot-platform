"""Severity levels and their presentation.

Severity is an ordered enum so escalation is a comparison rather than a lookup
table, and so ``max()`` over a set of findings yields the overall state.

The numeric values are stable and are what gets stored; the names are what
appear in the database and the API. Presentation (emoji, label) lives here too,
so a channel never invents its own formatting.
"""

from __future__ import annotations

from enum import IntEnum


class Severity(IntEnum):
    """Alert severity, ordered from least to most urgent.

    ``OK`` is not a real alert level: it is the absence of a problem, used as
    the identity element when reducing findings. Nothing is ever stored or
    notified at ``OK``.
    """

    OK = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4
    EMERGENCY = 5

    @classmethod
    def parse(cls, value: str | int | Severity | None, default: Severity | None = None) -> Severity:
        """Coerce a stored string, an int or an instance into a Severity.

        Falls back to ``default`` (or ``INFO``) for anything unrecognised, so a
        corrupted database value cannot crash the alert engine.
        """
        if isinstance(value, Severity):
            return value
        if isinstance(value, int):
            try:
                return cls(value)
            except ValueError:
                return default or cls.INFO
        if isinstance(value, str):
            try:
                return cls[value.strip().upper()]
            except KeyError:
                return default or cls.INFO
        return default or cls.INFO

    @property
    def emoji(self) -> str:
        """Leading glyph used in every notification."""
        return _EMOJI[self]

    @property
    def label(self) -> str:
        """Uppercase name as it appears in alerts and in the database."""
        return self.name

    @property
    def headline(self) -> str:
        """Emoji and label together, e.g. ``🚨 CRITICAL``."""
        if self is Severity.OK:
            return "✅ OK"
        return f"{self.emoji} {self.name}"

    @property
    def is_actionable(self) -> bool:
        """True for levels that represent a problem needing attention."""
        return self >= Severity.WARNING

    @property
    def breaks_quiet_hours(self) -> bool:
        """True for levels that must be delivered even during quiet hours.

        Quiet hours exist to suppress routine noise. Suppressing a critical
        outage overnight would defeat the purpose of the system, so the two
        highest levels always break through regardless of configuration.
        """
        return self >= Severity.CRITICAL


_EMOJI: dict[Severity, str] = {
    Severity.OK: "✅",
    Severity.INFO: "ℹ️",
    Severity.WARNING: "⚠️",
    Severity.ERROR: "❌",
    Severity.CRITICAL: "🚨",
    Severity.EMERGENCY: "🆘",
}


#: Lifecycle states an alert can be reported in. Kept as plain strings because
#: they are written to the database and returned by the API unchanged.
STATUS_NEW = "NEW"
STATUS_ONGOING = "ONGOING"
STATUS_ESCALATED = "ESCALATED"
STATUS_RESOLVED = "RESOLVED"
STATUS_REMINDER = "REMINDER"


def worst(severities: list[Severity] | tuple[Severity, ...]) -> Severity:
    """Highest severity in a collection, or ``OK`` when empty."""
    return max(severities, default=Severity.OK)


__all__ = [
    "STATUS_ESCALATED",
    "STATUS_NEW",
    "STATUS_ONGOING",
    "STATUS_REMINDER",
    "STATUS_RESOLVED",
    "Severity",
    "worst",
]
