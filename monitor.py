from __future__ import annotations

import argparse
import os
import time
from datetime import date

import pandas as pd
from dotenv import load_dotenv

from connectors import STANDARD_MAPPING, load_live_inputs
from engine import AssociateWeek, Rules, evaluate, alert_fingerprint
from importers import (
    read_table, normalize_actual_rows, normalize_schedule_rows,
    prepare_actuals, prepare_schedule, combine_actuals_schedule,
)
from notifier import format_alert_message, send_email, send_slack, send_sms_twilio
from planner import project_threshold_crossings, crossing_summary
from roster import normalize_roster, enrich_with_roster
from storage import init_db, was_sent, mark_sent, save_snapshot
from workweek import week_start_for, week_key_for

load_dotenv()


def truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def build_from_files(payroll_path: str, schedule_path: str, roster_path: str | None, ws: pd.Timestamp, now: pd.Timestamp) -> pd.DataFrame:
    p = read_table(payroll_path)
    s = read_table(schedule_path)
    actual_detail = normalize_actual_rows(p, STANDARD_MAPPING, week_start=ws)
    actual = prepare_actuals(p, STANDARD_MAPPING, week_start=ws)
    schedule_detail = normalize_schedule_rows(s, STANDARD_MAPPING, now=now, week_start=ws, actual_detail=actual_detail)
    sched = prepare_schedule(s, STANDARD_MAPPING, now=now, week_start=ws, actual_detail=actual_detail)
    combined = combine_actuals_schedule(actual, sched)
    summary = crossing_summary(project_threshold_crossings(actual, schedule_detail, thresholds=(30, 40, 50, 60)))
    if not summary.empty:
        combined = combined.merge(summary, on="employee_id", how="left")
    if roster_path:
        combined = enrich_with_roster(combined, normalize_roster(read_table(roster_path)))
    else:
        combined = enrich_with_roster(combined, pd.DataFrame())
    return combined


def row_to_assoc(r: pd.Series) -> AssociateWeek:
    def text(name):
        value = r.get(name, "")
        return "" if pd.isna(value) else str(value)
    return AssociateWeek(
        employee_id=text("employee_id"), name=text("name"), station=text("station"),
        actual_hours=float(r.get("actual_hours", 0) or 0), scheduled_remaining_hours=float(r.get("scheduled_remaining_hours", 0) or 0),
        days_worked=int(r.get("days_worked", 0) or 0), scheduled_days=int(r.get("scheduled_days", 0) or 0),
        next_shift_hours=float(r.get("next_shift_hours", 0) or 0), next_shift_date=text("next_shift_date")[:10],
        max_daily_hours=float(r.get("max_daily_hours", 0) or 0), max_scheduled_shift_hours=float(r.get("max_scheduled_shift_hours", 0) or 0),
        dot_regulated=bool(r.get("dot_regulated", False)), missing_punch=bool(r.get("missing_punch", False)),
        manager=text("manager"), manager_email=text("manager_email"), manager_phone=text("manager_phone"),
        phone=text("phone"), email=text("email"),
        cross_30_date=text("cross_30_date"), cross_40_date=text("cross_40_date"),
        cross_50_date=text("cross_50_date"), cross_60_date=text("cross_60_date"),
    )


def recipients_for(channel: str, associate: AssociateWeek, explicit: str | None = None) -> list[str]:
    if channel == "stdout":
        return ["stdout"]
    if channel == "slack":
        return ["configured webhook"]
    if explicit:
        return [explicit]
    recipients: list[str] = []
    if channel == "email":
        owner = os.getenv("ALERT_EMAIL", "").strip()
        if owner:
            recipients.append(owner)
        if truthy("SEND_MANAGER_ALERTS", True) and associate.manager_email:
            recipients.append(associate.manager_email)
        if truthy("SEND_ASSOCIATE_ALERTS", False) and associate.email:
            recipients.append(associate.email)
    elif channel == "sms":
        owner = os.getenv("ALERT_PHONE", "").strip()
        if owner:
            recipients.append(owner)
        if truthy("SEND_MANAGER_ALERTS", True) and associate.manager_phone:
            recipients.append(associate.manager_phone)
        if truthy("SEND_ASSOCIATE_ALERTS", False) and associate.phone:
            recipients.append(associate.phone)
    return list(dict.fromkeys(recipients))


def dispatch(channel: str, recipient: str, message: str):
    if channel == "slack":
        return send_slack(message)
    if channel == "email":
        return send_email(recipient, "AKAIROS Hours Alert", message)
    if channel == "sms":
        return send_sms_twilio(recipient, message)
    print(message)
    return True


def run_once(payroll_path: str | None, schedule_path: str | None, channel: str, recipient: str | None = None, roster_path: str | None = None, use_connectors: bool = False):
    init_db()
    today = date.today()
    ws = pd.Timestamp(week_start_for(today))
    now = pd.Timestamp.now()
    if use_connectors:
        combined = load_live_inputs(week_start=ws, now=now).combined
    else:
        if not payroll_path or not schedule_path:
            raise ValueError("Provide --payroll and --schedule, or pass --use-connectors.")
        combined = build_from_files(payroll_path, schedule_path, roster_path, ws, now)

    week_key = week_key_for(ws)
    save_snapshot(week_key, combined.to_dict("records"))
    rules = Rules(
        watch_30=float(os.getenv("WATCH_30", "30")), overtime_40=float(os.getenv("OVERTIME_40", "40")),
        critical_50=float(os.getenv("CRITICAL_50", "50")), amazon_weekly_max=float(os.getenv("AMAZON_WEEKLY_MAX", "60")),
        daily_max=float(os.getenv("DAILY_MAX", "12")), min_rest_hours=float(os.getenv("MIN_REST_HOURS", "10")),
        lead_hours=float(os.getenv("LEAD_HOURS", "2")),
    )
    sent = 0
    for _, r in combined.iterrows():
        associate = row_to_assoc(r)
        for alert in evaluate(associate, rules):
            message = format_alert_message(alert, associate)
            targets = recipients_for(channel, associate, recipient)
            if not targets:
                print(f"Skipped {associate.name} {alert.code}: no {channel} recipient configured.")
                continue
            base = alert_fingerprint(alert, week_key)
            for target in targets:
                fp = f"{base}|{channel}|{target}"
                if was_sent(fp):
                    continue
                dispatch(channel, target, message)
                mark_sent(fp, alert.severity, channel, target, message)
                sent += 1
    print(f"Processed {len(combined)} associates; sent {sent} new alert deliveries.")


def run_repeating(
    payroll_path: str | None,
    schedule_path: str | None,
    channel: str,
    recipient: str | None,
    use_connectors: bool,
    repeat_hours: float,
    max_runs: int | None = None,
    roster_path: str | None = None,
):
    repeat_hours = float(repeat_hours)
    if repeat_hours <= 0:
        raise ValueError("--repeat-hours must be greater than 0.")
    runs = 0
    while True:
        run_once(payroll_path, schedule_path, channel, recipient, roster_path, use_connectors)
        runs += 1
        if max_runs is not None and runs >= max_runs:
            return
        time.sleep(repeat_hours * 3600)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--payroll")
    ap.add_argument("--schedule")
    ap.add_argument("--roster", default=os.getenv("ROSTER_FILE_PATH"))
    ap.add_argument("--use-connectors", action="store_true")
    ap.add_argument("--repeat-hours", type=float, default=None)
    ap.add_argument("--max-runs", type=int, default=None)
    ap.add_argument("--channel", choices=["stdout", "slack", "email", "sms"], default=os.getenv("ALERT_CHANNEL", "stdout"))
    ap.add_argument("--recipient", default=None)
    args = ap.parse_args()
    common = dict(payroll_path=args.payroll, schedule_path=args.schedule, channel=args.channel, recipient=args.recipient, roster_path=args.roster, use_connectors=args.use_connectors)
    if args.repeat_hours is None:
        run_once(**common)
    else:
        run_repeating(**common, repeat_hours=args.repeat_hours, max_runs=args.max_runs)
