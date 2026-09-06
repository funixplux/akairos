from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

import requests


def format_alert_message(alert) -> str:
    return (
        f"AKAIROS HOURS ALERT — {alert.name} ({alert.station or 'No station'})\n"
        f"Worked: {alert.actual_hours:.1f}h | Projected: {alert.projected_hours:.1f}h\n"
        f"Status: {alert.code}\n"
        f"{alert.message}"
    )


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
