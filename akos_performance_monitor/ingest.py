"""IMAP ingest for Cortex/Gmail scheduled deliveries (authorized mailbox only)."""
from __future__ import annotations

import email
import hashlib
import imaplib
import os
from pathlib import Path

SUPPORTED = {".csv", ".xlsx", ".xls", ".pdf"}


def pull_imap(destination: Path, config: dict) -> list[str]:
    """Optional authorized email attachment source. Does not scrape the DSP portal."""
    host = os.getenv("AKOS_IMAP_HOST")
    user = os.getenv("AKOS_IMAP_USER")
    password = os.getenv("AKOS_IMAP_PASSWORD")
    if not any((host, user, password)):
        return []
    if not all((host, user, password)):
        raise RuntimeError("Set all three AKOS_IMAP_* variables")
    destination.mkdir(parents=True, exist_ok=True)

    filters = config.get("mail_subject_filters") or []
    single = config.get("mail_subject_filter")
    if single and single not in filters:
        filters = [single, *filters]
    filters = [f for f in filters if f]
    if not filters:
        filters = ["AKOS", "DVA5", "Cortex", "DVIC", "Supplementary"]

    downloaded: list[str] = []
    import datetime as dt

    with imaplib.IMAP4_SSL(host) as client:
        client.login(user, password)
        client.select("INBOX", readonly=True)
        since = (dt.date.today() - dt.timedelta(days=14)).strftime("%d-%b-%Y")
        status, items = client.search(None, "SINCE", since)
        if status != "OK":
            raise RuntimeError("IMAP search failed")
        for msg_id in items[0].split():
            status, result = client.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue
            msg = email.message_from_bytes(result[0][1])
            subject = str(msg.get("Subject", ""))
            if not any(f.casefold() in subject.casefold() for f in filters):
                continue
            for part in msg.walk():
                filename = Path(part.get_filename() or "").name
                if Path(filename).suffix.lower() not in SUPPORTED:
                    continue
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                digest = hashlib.sha256(payload).hexdigest()[:12]
                target = destination / f"{digest}_{filename}"
                if not target.exists():
                    target.write_bytes(payload)
                    downloaded.append(target.name)
    return downloaded
