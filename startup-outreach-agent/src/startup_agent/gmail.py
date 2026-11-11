"""Send a test email to the authenticated Gmail account."""

from email.message import EmailMessage
from pathlib import Path
import os
import re
import smtplib
import ssl


def gmail_address() -> str:
    address = os.getenv("GMAIL_ADDRESS", "").strip().lower()
    if not re.fullmatch(r"[a-z0-9.+_-]+@gmail\.com", address):
        raise ValueError("Set GMAIL_ADDRESS to your Gmail address in .env.")
    return address


def gmail_app_password() -> str:
    password = "".join(os.getenv("GMAIL_APP_PASSWORD", "").split())
    if not password:
        raise ValueError("Set GMAIL_APP_PASSWORD to your Google app password in .env.")
    return password


def send_gmail_self_test(address: str, password: str, subject: str, body: str) -> None:
    send_gmail(address, password, address, subject, body)


def load_resume() -> tuple[str, bytes]:
    configured = os.getenv("OUTREACH_RESUME_PATH", "").strip()
    if not configured:
        raise ValueError("Set OUTREACH_RESUME_PATH to your resume PDF in .env.")
    path = Path(configured).expanduser()
    try:
        with path.open("rb") as resume:
            content = resume.read(10 * 1024 * 1024 + 1)
    except OSError:
        raise ValueError("Could not open the resume PDF configured in .env.") from None
    if path.suffix.lower() != ".pdf" or not content.startswith(b"%PDF-") or len(content) > 10 * 1024 * 1024:
        raise ValueError("The resume must be a readable PDF under 10 MB.")
    return path.name, content


def send_gmail(
    address: str, password: str, recipient: str, subject: str, body: str,
    *, resume: tuple[str, bytes] | None = None,
) -> None:
    message = EmailMessage()
    message["From"] = address
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    if resume:
        filename, content = resume
        message.add_attachment(content, maintype="application", subtype="pdf", filename=filename)
    smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=10)
    try:
        smtp.login(address, password)
        smtp.send_message(message, from_addr=address, to_addrs=[recipient])
    finally:
        smtp.close()
