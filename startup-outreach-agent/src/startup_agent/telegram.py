"""Telegram Bot API helpers for the local digest delivery test."""

import json
import logging
import os
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sqlalchemy import update

from startup_agent.database.models import JobModel
from startup_agent.digest import format_digest
from startup_agent.routing import OutreachRoute


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


def _private_chat_id() -> int:
    raw_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not re.fullmatch(r"[1-9][0-9]*", raw_chat_id):
        raise ValueError("Set TELEGRAM_CHAT_ID to your private chat ID in .env.")
    return int(raw_chat_id)


def send_test_digest(digest: str) -> int:
    chat_id = _private_chat_id()
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
                "chat_id": chat_id, "text": message,
                "link_preview_options": {"is_disabled": True},
            })
        except RuntimeError as exc:
            raise RuntimeError(f"Telegram confirmed {index} of {len(messages)} messages. {exc}") from None
    return len(messages)


def send_job_cards(routes: list[OutreachRoute]) -> int:
    chat_id = _private_chat_id()
    sent = 0
    for route in routes:
        if route.job_id is None or not route.url:
            continue
        text = format_digest([route]).split("\n\n", 1)[1]
        _request("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "link_preview_options": {"is_disabled": True},
            "reply_markup": {"inline_keyboard": [[
                {"text": "Skip", "callback_data": f"job:skipped:{route.job_id}"},
                {"text": "Mark Applied", "callback_data": f"job:applied:{route.job_id}"},
            ]]},
        })
        sent += 1
    return sent


def _record_job_action(callback: dict, chat_id: int, session_factory) -> str:
    chat = callback.get("message", {}).get("chat", {})
    if chat.get("type") != "private" or chat.get("id") != chat_id or callback.get("from", {}).get("id") != chat_id:
        return "This action is unavailable in this chat."
    action = re.fullmatch(r"job:(skipped|applied):([1-9][0-9]{0,17})", callback.get("data") or "")
    if not action:
        return "Unknown job action."
    status, job_id = action.groups()
    with session_factory.begin() as session:
        result = session.execute(
            update(JobModel)
            .where(JobModel.id == int(job_id), JobModel.status == "open")
            .values(status=status)
        )
        changed = result.rowcount == 1
    return {"skipped": "Skipped", "applied": "Marked applied"}[status] if changed else "Already handled or unavailable."


def poll_job_actions(session_factory) -> None:
    chat_id = _private_chat_id()
    offset = 0
    logger = logging.getLogger(__name__)
    while True:
        updates = _request("getUpdates", {
            "offset": offset, "timeout": 10,
            "allowed_updates": ["message", "callback_query"],
        })["result"]
        for item in updates:
            callback = item.get("callback_query")
            if callback:
                message = _record_job_action(callback, chat_id, session_factory)
                if message in {"Skipped", "Marked applied"}:
                    logger.info("Telegram action saved for job #%s: %s", callback["data"].rsplit(":", 1)[1], message)
                else:
                    logger.info("Telegram button tap: %s", message)
                try:
                    _request("answerCallbackQuery", {
                        "callback_query_id": callback["id"], "text": message,
                    })
                except RuntimeError:
                    logger.warning("Could not acknowledge a Telegram button tap.")
            offset = item["update_id"] + 1
