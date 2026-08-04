"""Notification channels.

``build_channels`` is the only place that knows which channels exist. Adding a
channel is a one-line change here plus the channel module itself; no other file
in the package refers to a concrete channel.
"""

from __future__ import annotations

from app.monitoring.channels.base import (
    DeliveryResult,
    NotificationChannel,
    OutboundMessage,
)
from app.monitoring.channels.telegram import TelegramChannel
from app.monitoring.config import MonitoringConfig, get_config


def build_channels(config: MonitoringConfig | None = None) -> list[NotificationChannel]:
    """Instantiate every known channel.

    Unconfigured channels are still returned. The dispatcher skips them at send
    time, and returning them keeps them visible in the API's channel listing —
    "configured: false" is far more useful for debugging a silent system than
    an absent entry.
    """
    config = config or get_config()
    return [
        TelegramChannel(config.telegram),
        # Future channels register here:
        #   EmailChannel(config.email),
        #   DiscordChannel(config.discord),
        #   SlackChannel(config.slack),
    ]


def channel_by_name(
    name: str, config: MonitoringConfig | None = None
) -> NotificationChannel | None:
    """Look up a single channel by its registered name."""
    for channel in build_channels(config):
        if channel.name == name:
            return channel
    return None


__all__ = [
    "DeliveryResult",
    "NotificationChannel",
    "OutboundMessage",
    "TelegramChannel",
    "build_channels",
    "channel_by_name",
]
