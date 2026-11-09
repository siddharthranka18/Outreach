"""Telegram Bot API helpers for the local digest delivery test."""

import json
import os
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _request(method: str, payload: dict) -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not re.fullmatch(r"\d+:[\w-]+", token, re.ASCII):
        raise ValueError("Set TELEGRAM_BOT_TOKEN in your local .env file.")
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=15.0) as response:
            status = response.status
            data = json.load(response)
    except HTTPError as exc:
        status = exc.code
        exc.close()
        data = {}
    except (OSError, ValueError):
        # Transport exceptions can include the URL, which contains the token.
        raise RuntimeError("Could not read a response from Telegram.") from None
    if not data.get("ok"):
        hints = {
            401: "Check the bot token in .env.",
            403: "Open your bot's private chat and send /start.",
            409: "Check whether a webhook or another bot process is active.",
            400: "Check the private chat ID and send /start to your bot.",
        }
        raise RuntimeError(f"Telegram rejected {method} ({status}). {hints.get(status, '')}".strip())
    return data


def private_chat_ids() -> list[int]:
    updates = _request("getUpdates", {})["result"]
    chats = [update.get("message", {}).get("chat", {}) for update in updates]
    return sorted({chat["id"] for chat in chats if chat.get("type") == "private"})


def send_test_digest(digest: str) -> int:
    raw_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not re.fullmatch(r"[1-9][0-9]*", raw_chat_id):
        raise ValueError("Set TELEGRAM_CHAT_ID to your private chat ID in .env.")
    messages = []
    current = "Test delivery\n"
    for entry in digest.split("\n\n"):
        if len(entry.encode("utf-16-le")) // 2 > 4000:
            raise ValueError("A digest entry exceeds Telegram's message limit.")
        combined = f"{current}\n\n{entry}"
        if len(combined.encode("utf-16-le")) // 2 > 4000:
            messages.append(current)
            current = entry
        else:
            current = combined
    messages.append(current)
    for index, message in enumerate(messages):
        try:
            _request("sendMessage", {
                "chat_id": int(raw_chat_id), "text": message,
                "link_preview_options": {"is_disabled": True},
            })
        except RuntimeError as exc:
            raise RuntimeError(f"Telegram confirmed {index} of {len(messages)} messages. {exc}") from None
    return len(messages)
