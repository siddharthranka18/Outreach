"""Send a test email to the authenticated Gmail account."""

from email.message import EmailMessage
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
    message = EmailMessage()
    message["From"] = address
    message["To"] = address
    message["Subject"] = subject
    message.set_content(body)
    smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=10)
    try:
        smtp.login(address, password)
        smtp.send_message(message, from_addr=address, to_addrs=[address])
    finally:
        smtp.close()
