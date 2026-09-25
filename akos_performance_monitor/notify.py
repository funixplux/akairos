"""SMTP notification with per-recipient content de-duplication."""
from __future__ import annotations

import hashlib
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path


DEFAULT_NOTIFY_TO = "etimbassey@akairos.net"


def resolve_recipients(config: dict) -> list[str]:
    """Prefer env AKOS_NOTIFY_TO; else config notify_to; else authorized default when enabled."""
    env = os.getenv("AKOS_NOTIFY_TO", "").strip()
    if env:
        return [x.strip() for x in env.split(",") if x.strip()]
    cfg = config.get("notify_to") or config.get("notify_to_default")
    if isinstance(cfg, str) and cfg.strip():
        return [x.strip() for x in cfg.split(",") if x.strip()]
    if isinstance(cfg, list):
        return [str(x).strip() for x in cfg if str(x).strip()]
    if config.get("email_named_driver_details", True):
        return [DEFAULT_NOTIFY_TO]
    return []


def notify(subject: str, body: str, recipients: list[str]) -> None:
    host = os.environ["AKOS_SMTP_HOST"]
    sender = os.environ["AKOS_SMTP_FROM"]
    port = int(os.getenv("AKOS_SMTP_PORT", "465"))
    use_starttls = os.getenv("AKOS_SMTP_STARTTLS", "").strip() in {"1", "true", "yes"} or port == 587
    user = os.getenv("AKOS_SMTP_USER")
    password = os.getenv("AKOS_SMTP_PASSWORD")

    for recipient in recipients:
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        if use_starttls:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls(context=ssl.create_default_context())
                if user and password:
                    server.login(user, password)
                server.send_message(message)
        else:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as server:
                if user and password:
                    server.login(user, password)
                server.send_message(message)


def maybe_send(subject: str, body: str, recipients: list[str], state_path: Path, send: bool) -> dict:
    """
    Send when --send and content signature differs from last successful send
    for this recipient set. Returns de-dupe state info.
    """
    signature = hashlib.sha256(body.encode()).hexdigest()
    previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    info = {
        "signature": signature,
        "previous_signature": previous.get("signature"),
        "sent": False,
        "skipped_duplicate": False,
        "recipients": recipients,
    }
    if not send:
        return info
    if not recipients:
        raise RuntimeError("No notification recipients configured (AKOS_NOTIFY_TO / config.notify_to)")
    if previous.get("signature") == signature and previous.get("recipients") == recipients:
        info["skipped_duplicate"] = True
        return info
    notify(subject, body, recipients)
    state_path.write_text(
        json.dumps({"signature": signature, "recipients": recipients, "subject": subject}, indent=2) + "\n",
        encoding="utf-8",
    )
    info["sent"] = True
    return info
