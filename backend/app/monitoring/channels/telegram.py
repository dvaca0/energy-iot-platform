"""Telegram delivery channel.

Implements :class:`~app.monitoring.channels.base.NotificationChannel` against
the Bot API. The interesting behaviour is in the error classification, because
that decides whether a message is retried or abandoned:

* **Retryable** — network errors, timeouts, HTTP 5xx, and HTTP 429 (rate
  limited, with ``retry_after`` honoured by the outbox backoff).
* **Permanent** — HTTP 401 (bad token), 403 (bot blocked, or the user never
  pressed Start), and 400 with a chat-not-found description. These fail
  identically on every retry; retrying them only delays the operator noticing
  the configuration is wrong.

HTML is used rather than Markdown because Telegram's legacy Markdown parser
fails on unescaped ``_`` and ``*``, which appear constantly in hostnames, unit
names and file paths. A parse failure would reject the whole message, so the
formatter escapes the four HTML-significant characters and nothing else.
"""

from __future__ import annotations

import html
import logging
from typing import Any

import requests

from app.monitoring.channels.base import (
    DeliveryResult,
    NotificationChannel,
    OutboundMessage,
)
from app.monitoring.config import TelegramConfig

log = logging.getLogger("monitoring.channels.telegram")

API_BASE = "https://api.telegram.org"


def escape(text: str) -> str:
    """Escape the characters Telegram's HTML parser treats as markup.

    Only ``&``, ``<`` and ``>`` are significant. Escaping more would put
    literal entities in front of the reader.
    """
    return html.escape(str(text), quote=False)


class TelegramChannel(NotificationChannel):
    """Sends alerts to a Telegram chat via the Bot API."""

    name = "telegram"

    def __init__(self, config: TelegramConfig) -> None:
        self._config = config
        self._session = requests.Session()

    @property
    def recipient(self) -> str | None:
        return self._config.chat_id or None

    def is_configured(self) -> bool:
        return bool(self._config.enabled and self._config.bot_token and self._config.chat_id)

    def _url(self, method: str) -> str:
        return f"{API_BASE}/bot{self._config.bot_token}/{method}"

    def send(self, message: OutboundMessage) -> DeliveryResult:
        """Deliver a message, splitting it if it exceeds the size limit.

        A split message is only reported as delivered when every part
        succeeded; a partial failure is retryable, and Telegram tolerates the
        resulting duplicate parts better than an operator tolerates a truncated
        alert.
        """
        if not self.is_configured():
            return DeliveryResult.permanent("telegram channel is not configured")

        body = message.html_body or escape(message.body)
        parts = self.split_body(body, self._config.max_message_chars)

        for index, part in enumerate(parts):
            suffix = f"\n\n<i>({index + 1}/{len(parts)})</i>" if len(parts) > 1 else ""
            result = self._send_one(part + suffix)
            if not result.ok:
                return result

        return DeliveryResult.success(f"sent in {len(parts)} part(s)")

    def _send_one(self, text: str) -> DeliveryResult:
        payload: dict[str, Any] = {
            "chat_id": self._config.chat_id,
            "text": text,
            "parse_mode": self._config.parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            response = self._session.post(
                self._url("sendMessage"),
                json=payload,
                timeout=self._config.timeout_seconds,
            )
        except requests.Timeout:
            return DeliveryResult.retry("timed out talking to the Telegram API")
        except requests.RequestException as exc:
            return DeliveryResult.retry(f"network error: {exc}")

        if response.status_code == 200:
            return DeliveryResult.success()

        description = ""
        retry_after: int | None = None
        try:
            data = response.json()
            description = str(data.get("description", ""))
            retry_after = (data.get("parameters") or {}).get("retry_after")
        except ValueError:
            description = response.text[:200]

        detail = f"HTTP {response.status_code}: {description}"

        if response.status_code == 429:
            return DeliveryResult.retry(
                detail + (f" (retry after {retry_after}s)" if retry_after else "")
            )
        if response.status_code >= 500:
            return DeliveryResult.retry(detail)
        if response.status_code in (401, 403):
            return DeliveryResult.permanent(detail)
        if response.status_code == 400 and "chat not found" in description.lower():
            return DeliveryResult.permanent(
                detail + " — the chat id is wrong, or nobody has pressed Start on the bot yet"
            )

        # Any other 4xx is a malformed request: identical on every retry.
        return DeliveryResult.permanent(detail)

    def verify(self) -> dict[str, Any]:
        """Check the token and report the bot identity.

        Used by the API's self-test endpoint so a misconfiguration is visible
        without waiting for the first real alert to fail.
        """
        if not self._config.bot_token:
            return {"ok": False, "error": "no bot token configured"}

        try:
            response = self._session.get(self._url("getMe"), timeout=self._config.timeout_seconds)
            data = response.json()
        except requests.RequestException as exc:
            return {"ok": False, "error": str(exc)}
        except ValueError as exc:
            return {"ok": False, "error": f"unparseable response: {exc}"}

        if not data.get("ok"):
            return {"ok": False, "error": data.get("description", "unknown error")}

        result = data.get("result") or {}
        return {
            "ok": True,
            "bot_username": result.get("username"),
            "bot_name": result.get("first_name"),
            "chat_id_configured": bool(self._config.chat_id),
        }

    def discover_chat_id(self) -> dict[str, Any]:
        """Read recent updates to find the chat id.

        Convenience for first-time setup: after someone messages the bot, this
        reports the chat id to configure. Returns an empty list when nobody has
        messaged it, which is itself the diagnosis.
        """
        if not self._config.bot_token:
            return {"ok": False, "error": "no bot token configured"}

        try:
            response = self._session.get(
                self._url("getUpdates"), timeout=self._config.timeout_seconds
            )
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

        chats: list[dict[str, Any]] = []
        seen: set[Any] = set()
        for update in data.get("result") or []:
            for key in ("message", "edited_message", "channel_post", "my_chat_member"):
                chat = (update.get(key) or {}).get("chat")
                if chat and chat.get("id") not in seen:
                    seen.add(chat.get("id"))
                    chats.append(
                        {
                            "chat_id": chat.get("id"),
                            "type": chat.get("type"),
                            "title": chat.get("title") or chat.get("first_name"),
                            "username": chat.get("username"),
                        }
                    )

        return {
            "ok": True,
            "chats": chats,
            "hint": (
                "No chats yet — open the bot in Telegram, press Start and send any "
                "message, then call this again."
                if not chats
                else "Set MONITORING_TELEGRAM_CHAT_ID to the chat_id you want."
            ),
        }


__all__ = ["TelegramChannel", "escape"]
