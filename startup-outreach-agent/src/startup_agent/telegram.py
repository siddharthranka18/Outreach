"""Telegram Bot API helpers for the local digest delivery test."""

import hmac
import hashlib
import json
import logging
import os
import re
import smtplib
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sqlalchemy import update

from startup_agent.database.models import EmailDraftModel, JobModel
from startup_agent.gmail import gmail_address, gmail_app_password, load_resume, send_gmail, send_gmail_self_test
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


def _authorized_callback(callback: dict, chat_id: int) -> bool:
    chat = callback.get("message", {}).get("chat", {})
    return chat.get("type") == "private" and chat.get("id") == chat_id and callback.get("from", {}).get("id") == chat_id


def _gmail_test_signature(draft: EmailDraftModel, address: str) -> str:
    payload = json.dumps([draft.job_id, address, draft.subject, draft.body]).encode()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip().encode()
    return hmac.digest(token, payload, "sha256").hex()[:24]


def _employer_signature(draft: EmailDraftModel, sender: str, resume: tuple[str, bytes]) -> str:
    filename, content = resume
    payload = json.dumps([
        "employer", draft.job_id, sender, draft.recipient, draft.subject, draft.body,
        filename, hashlib.sha256(content).hexdigest(),
    ]).encode()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip().encode()
    return hmac.digest(token, payload, "sha256").hex()[:24]


def _valid_recipient(address: str | None) -> bool:
    return bool(address and re.fullmatch(r"[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", address))


def send_employer_email_card(
    draft: EmailDraftModel, *, preview: bool = False, preview_signature: str | None = None,
) -> None:
    sender = gmail_address()
    if not preview:
        gmail_app_password()
    if not _valid_recipient(draft.recipient):
        raise ValueError("This draft needs a published employer email address.")
    if not preview and draft.gmail_status != "pending":
        raise ValueError(f"This draft's Gmail delivery status is {draft.gmail_status}.")
    resume = load_resume()
    signature = preview_signature or _employer_signature(draft, sender, resume)
    heading = "Preview only" if preview else "Employer email"
    message = (
        f"{heading}\nFrom: {sender}\nTo: {draft.recipient}\n"
        f"Subject: {draft.subject}\nAttachment: {resume[0]}\n\n{draft.body}"
    )
    if len(message.encode("utf-16-le")) // 2 > 4000:
        raise ValueError("This draft is too long to review in one Telegram message.")
    _request("sendMessage", {
        "chat_id": _private_chat_id(),
        "text": message,
        "link_preview_options": {"is_disabled": True},
        "reply_markup": {"inline_keyboard": [[
            {"text": "Edit", "callback_data": f"{'gmail-preview-edit' if preview else 'gmail-edit'}:{draft.job_id}:{signature}"},
            {"text": "Approve & Send", "callback_data": "gmail-preview:send" if preview else f"gmail-send:{draft.job_id}:{signature}"},
        ]]},
    })


def send_gmail_test_card(draft: EmailDraftModel) -> None:
    address = gmail_address()
    gmail_app_password()
    if draft.gmail_test_status != "pending":
        raise ValueError(f"This draft's Gmail test is already {draft.gmail_test_status}.")
    signature = _gmail_test_signature(draft, address)
    _request("sendMessage", {
        "chat_id": _private_chat_id(),
        "text": f"Gmail self-test\nTo: {address}\nSubject: [Test] {draft.subject}\n\n{draft.body}",
        "link_preview_options": {"is_disabled": True},
        "reply_markup": {"inline_keyboard": [[
            {"text": "Approve & Send Test", "callback_data": f"gmail-test:{draft.job_id}:{signature}"},
        ]]},
    })


def _record_gmail_test(callback: dict, chat_id: int, session_factory) -> str:
    if not _authorized_callback(callback, chat_id):
        return "This action is unavailable in this chat."
    action = re.fullmatch(r"gmail-test:([1-9][0-9]{0,17}):([a-f0-9]{24})", callback.get("data") or "")
    if not action:
        return "Invalid Gmail test approval."
    job_id, signature = action.groups()
    try:
        address, password = gmail_address(), gmail_app_password()
    except ValueError as exc:
        return str(exc)
    with session_factory.begin() as session:
        draft = session.get(EmailDraftModel, int(job_id))
        if not draft or not hmac.compare_digest(signature, _gmail_test_signature(draft, address)):
            return "Draft or Gmail address changed. Open a new test card."
        result = session.execute(
            update(EmailDraftModel)
            .where(EmailDraftModel.job_id == draft.job_id, EmailDraftModel.gmail_test_status == "pending")
            .values(gmail_test_status="sending")
        )
        if result.rowcount != 1:
            return "Test already handled. Check Gmail Sent before trying again."
        subject, body = draft.subject, draft.body

    try:
        send_gmail_self_test(address, password, f"[Test] {subject}", body)
    except smtplib.SMTPAuthenticationError:
        status, feedback = "pending", "Gmail rejected the credentials. Check your app password."
    except (OSError, ValueError):
        status, feedback = "uncertain", "Gmail delivery could not be confirmed. Check Gmail Sent."
    else:
        status, feedback = "sent", "Gmail accepted the test email."
    with session_factory.begin() as session:
        session.get(EmailDraftModel, int(job_id)).gmail_test_status = status
    return feedback


def _record_employer_email(callback: dict, chat_id: int, session_factory) -> str:
    if not _authorized_callback(callback, chat_id):
        return "This action is unavailable in this chat."
    action = re.fullmatch(r"gmail-send:([1-9][0-9]{0,17}):([a-f0-9]{24})", callback.get("data") or "")
    if not action:
        return "Invalid email approval."
    job_id, signature = action.groups()
    try:
        sender, password = gmail_address(), gmail_app_password()
        resume = load_resume()
    except ValueError as exc:
        return str(exc)
    with session_factory.begin() as session:
        draft = session.get(EmailDraftModel, int(job_id))
        if not draft or not hmac.compare_digest(signature, _employer_signature(draft, sender, resume)):
            return "Draft, sender, or resume changed. Open a new review card."
        if not _valid_recipient(draft.recipient):
            return "This draft needs a published employer email address."
        open_job = (
            JobModel.__table__.select()
            .where(JobModel.id == int(job_id), JobModel.status == "open")
            .exists()
        )
        result = session.execute(
            update(EmailDraftModel)
            .where(
                EmailDraftModel.job_id == int(job_id), EmailDraftModel.gmail_status == "pending", open_job,
                EmailDraftModel.recipient == draft.recipient, EmailDraftModel.subject == draft.subject,
                EmailDraftModel.body == draft.body,
            )
            .values(gmail_status="sending")
        )
        if result.rowcount != 1:
            return "Email already handled or job no longer open. Check Gmail Sent."
        recipient, subject, body = draft.recipient, draft.subject, draft.body
    try:
        send_gmail(sender, password, recipient, subject, body, resume=resume)
    except smtplib.SMTPAuthenticationError:
        status, feedback = "pending", "Gmail rejected the credentials. Check your app password."
    except (OSError, ValueError):
        status, feedback = "uncertain", "Gmail delivery could not be confirmed. Check Gmail Sent."
    else:
        status, feedback = "sent", "Gmail accepted your email to the employer."
    with session_factory.begin() as session:
        session.get(EmailDraftModel, int(job_id)).gmail_status = status
    return feedback


def _record_job_action(callback: dict, chat_id: int, session_factory) -> str:
    if not _authorized_callback(callback, chat_id):
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


def _request_email_edit(callback: dict, chat_id: int, session_factory) -> str:
    if not _authorized_callback(callback, chat_id):
        return "This action is unavailable in this chat."
    match = re.fullmatch(r"gmail-(preview-)?edit:([1-9][0-9]{0,17}):([a-f0-9]{24})", callback.get("data") or "")
    if not match:
        return "Invalid draft edit."
    preview, job_id, signature = match.groups()
    try:
        sender, resume = gmail_address(), load_resume()
        with session_factory() as session:
            draft = session.get(EmailDraftModel, int(job_id))
            if not draft or (not preview and draft.gmail_status != "pending") or not hmac.compare_digest(
                signature, _employer_signature(draft, sender, resume),
            ):
                return "This card is out of date. Open a new review card."
        _request("sendMessage", {
            "chat_id": chat_id,
            "text": (
                f"{'Preview edit' if preview else 'Edit email'} #{job_id} ({signature})\n"
                "Copy the subject and body from the card and reply here with your changes. "
                "Put the subject on the first line and the body on the following lines."
            ),
            "reply_markup": {"force_reply": True, "input_field_placeholder": "Subject, then body"},
        })
    except (ValueError, RuntimeError) as exc:
        return str(exc)
    return "Reply to the edit prompt."


def _save_email_edit(message: dict, chat_id: int, session_factory) -> None:
    chat = message.get("chat", {})
    if chat.get("type") != "private" or chat.get("id") != chat_id or message.get("from", {}).get("id") != chat_id:
        return
    reply = message.get("reply_to_message", {})
    if not reply.get("from", {}).get("is_bot"):
        return
    prompt = (reply.get("text") or "").partition("\n")[0]
    match = re.fullmatch(r"(Edit email|Preview edit) #([1-9][0-9]{0,17}) \(([a-f0-9]{24})\)", prompt)
    if not match:
        return
    mode, job_id, signature = match.groups()
    subject, _, body = (message.get("text") or "").partition("\n")
    subject, body = subject.strip(), body.strip()
    if not subject or not body or len(subject) > 150 or "\r" in subject or len(body.encode("utf-16-le")) // 2 > 3000:
        _request("sendMessage", {"chat_id": chat_id, "text": "Reply to the edit prompt with a subject (up to 150 characters) and a body (up to 3,000 characters)."})
        return
    try:
        sender, resume = gmail_address(), load_resume()
        with session_factory.begin() as session:
            draft = session.get(EmailDraftModel, int(job_id))
            if not draft or not hmac.compare_digest(signature, _employer_signature(draft, sender, resume)):
                raise ValueError("This edit prompt is out of date. Open a new review card.")
            if mode == "Preview edit":
                preview_draft = EmailDraftModel(
                    job_id=draft.job_id, recipient=draft.recipient, listing_url=draft.listing_url,
                    subject=subject, body=body,
                )
                send_employer_email_card(preview_draft, preview=True, preview_signature=signature)
                return
            result = session.execute(
                update(EmailDraftModel)
                .where(
                    EmailDraftModel.job_id == int(job_id), EmailDraftModel.gmail_status == "pending",
                    EmailDraftModel.subject == draft.subject, EmailDraftModel.body == draft.body,
                )
                .values(subject=subject, body=body)
            )
            if result.rowcount != 1:
                raise ValueError("This draft has changed or is already being sent.")
        send_employer_email_card(draft)
    except (ValueError, RuntimeError) as exc:
        _request("sendMessage", {"chat_id": chat_id, "text": str(exc)})


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
                prefix = (callback.get("data") or "").partition(":")[0]
                handler = {
                    "gmail-test": _record_gmail_test, "gmail-send": _record_employer_email,
                    "gmail-edit": _request_email_edit, "gmail-preview-edit": _request_email_edit,
                }.get(prefix, _record_job_action)
                if prefix == "gmail-preview" and _authorized_callback(callback, chat_id):
                    message = "Preview only. No changes or email sent."
                else:
                    message = handler(callback, chat_id, session_factory)
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
            elif item.get("message"):
                try:
                    _save_email_edit(item["message"], chat_id, session_factory)
                except RuntimeError:
                    logger.warning("Could not deliver Telegram edit feedback. Reopen the draft review card.")
            offset = item["update_id"] + 1
