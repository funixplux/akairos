from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

import requests


def format_alert_message(alert, associate=None) -> str:
    lines = [
        f"AKAIROS HOURS ALERT — {alert.name} ({alert.station or 'No station'})",
        f"Worked: {alert.actual_hours:.1f}h | Projected: {alert.projected_hours:.1f}h",
        f"Status: {alert.code}",
    ]
    if alert.crossing_date:
        lines.append(f"Scheduled threshold crossing: {alert.crossing_date}")
    if associate is not None:
        next_date = getattr(associate, "next_shift_date", "") or ""
        next_hours = float(getattr(associate, "next_shift_hours", 0) or 0)
        if next_date or next_hours:
            lines.append(f"Next shift: {next_date or 'date not provided'} | {next_hours:.1f}h")
        manager = getattr(associate, "manager", "") or ""
        if manager:
            lines.append(f"Manager: {manager}")
    lines.append(alert.message)
    lines.append("Action: review the remaining schedule before assigning or working additional time. Do not alter actual time records to reduce hours.")
    return "\n".join(lines)


def send_slack(message: str, webhook_url: str | None = None):
    url = webhook_url or os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        raise RuntimeError("SLACK_WEBHOOK_URL is not configured")
    r = requests.post(url, json={"text": message}, timeout=20)
    r.raise_for_status()
    return True


def send_sms_twilio(to_number: str, message: str):
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER")
    if not (sid and token and from_number):
        raise RuntimeError("Twilio environment variables are not configured")
    if not to_number:
        raise RuntimeError("SMS recipient is blank")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    r = requests.post(url, data={"To": to_number, "From": from_number, "Body": message}, auth=(sid, token), timeout=20)
    r.raise_for_status()
    return True


def send_email(to_email: str, subject: str, message: str):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("SMTP_FROM", user or "")
    if not (host and user and password and from_email):
        raise RuntimeError("SMTP environment variables are not configured")
    if not to_email:
        raise RuntimeError("Email recipient is blank")
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(message)
    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)
    return True
