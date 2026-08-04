"""The notification channel contract.

Adding a channel — email, Discord, Slack, Teams, SMS — means writing one class
that implements :class:`NotificationChannel` and registering it. Nothing in the
alert engine, the rule engine or the scheduler changes.

The contract is deliberately narrow:

* A channel receives an already-rendered :class:`OutboundMessage`. It does not
  decide *whether* to send (rate limits, quiet hours and deduplication are
  settled upstream) and it does not decide *what* to say.
* A channel never raises for a delivery failure. It returns a
  :class:`DeliveryResult` saying whether the failure is worth retrying. An
  exception escaping a channel is treated as a retryable failure, so a badly
  behaved channel degrades rather than stalling the outbox.
* A channel declares whether it is configured. An unconfigured channel is
  skipped without error, so a half-configured deployment still delivers on the
  channels that *are* set up.

The retryable/permanent distinction matters. A network timeout should be
retried; a malformed chat id should not, because retrying it twelve times only
delays the moment someone notices the configuration is wrong.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.monitoring.severity import Severity


@dataclass
class OutboundMessage:
    """A rendered message ready for delivery."""

    #: Plain-text body. Channels that support rich text may also read
    #: ``html_body``; those that do not use this and stay correct.
    body: str
    severity: Severity = Severity.INFO
    subject: str | None = None
    #: alert | report | selftest | recovery
    kind: str = "alert"
    #: HTML rendering, when the renderer produced one.
    html_body: str | None = None
    #: Channel-specific hints (thread ids, mention targets). Ignored by
    #: channels that do not understand a given key.
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeliveryResult:
    """Outcome of a single delivery attempt."""

    ok: bool
    #: Whether another attempt could plausibly succeed. Ignored when ``ok``.
    retryable: bool = True
    detail: str | None = None

    @classmethod
    def success(cls, detail: str | None = None) -> DeliveryResult:
        return cls(ok=True, retryable=False, detail=detail)

    @classmethod
    def retry(cls, detail: str) -> DeliveryResult:
        """A transient failure: network, timeout, rate limit, 5xx."""
        return cls(ok=False, retryable=True, detail=detail)

    @classmethod
    def permanent(cls, detail: str) -> DeliveryResult:
        """A failure that will recur identically: bad credentials, bad target."""
        return cls(ok=False, retryable=False, detail=detail)


class NotificationChannel(ABC):
    """Base class for every delivery channel."""

    #: Stable identifier, stored on outbox rows. Must not change once used.
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """True when this channel has everything it needs to deliver.

        Checked before every send. A channel that becomes configured at
        runtime (a token added to the environment and the config reloaded)
        starts delivering without a restart.
        """

    @abstractmethod
    def send(self, message: OutboundMessage) -> DeliveryResult:
        """Attempt one delivery. Must not raise for delivery failures."""

    @property
    def recipient(self) -> str | None:
        """Destination recorded on the outbox row, for auditing."""
        return None

    def describe(self) -> dict[str, Any]:
        """Diagnostic summary, safe to expose through the API.

        Must never include secrets.
        """
        return {
            "name": self.name,
            "configured": self.is_configured(),
            "recipient": self.recipient,
        }

    def split_body(self, body: str, limit: int) -> list[str]:
        """Split an over-long body at line boundaries.

        Every channel has a size ceiling, and truncating an alert would remove
        exactly the diagnostic detail the alert exists to carry. Splitting on
        lines keeps each part readable; a single line longer than the limit is
        hard-cut, since there is nothing better to do with it.
        """
        if len(body) <= limit:
            return [body]

        parts: list[str] = []
        current: list[str] = []
        length = 0

        for line in body.splitlines(keepends=True):
            while len(line) > limit:
                if current:
                    parts.append("".join(current))
                    current, length = [], 0
                parts.append(line[:limit])
                line = line[limit:]

            if length + len(line) > limit:
                parts.append("".join(current))
                current, length = [line], len(line)
            else:
                current.append(line)
                length += len(line)

        if current:
            parts.append("".join(current))
        return parts


__all__ = ["DeliveryResult", "NotificationChannel", "OutboundMessage"]
