from __future__ import annotations

import argparse
import os
import time
from datetime import date, timedelta

import pandas as pd
from dotenv import load_dotenv

from connectors import STANDARD_MAPPING, load_live_inputs
from engine import AssociateWeek, Rules, evaluate, alert_fingerprint
from importers import read_table, prepare_actuals, prepare_schedule, combine_actuals_schedule
from notifier import format_alert_message, send_email, send_slack, send_sms_twilio
from storage import init_db, was_sent, mark_sent, save_snapshot

load_dotenv()


def week_start_for(d: date):
    return d - timedelta(days=d.weekday())


def load_inputs(payroll_path: str | None, schedule_path: str | None, week_start: pd.Timestamp, use_connectors: bool):
    if use_connectors:
        live = load_live_inputs(week_start=week_start, now=pd.Timestamp.today())
        return live.combined

    if not (payroll_path and schedule_path):
        raise ValueError("Provide --payroll and --schedule, or pass --use-connectors.")

    payroll_raw = read_table(payroll_path)
    schedule_raw = read_table(schedule_path)
    actuals = prepare_actuals(payroll_raw, STANDARD_MAPPING, week_start=week_start)
    schedule = prepare_schedule(schedule_raw, STANDARD_MAPPING, now=pd.Timestamp.today(), week_start=week_start)
    return combine_actuals_schedule(actuals, schedule)


def run_once(
    payroll_path: str | None,
    schedule_path: str | None,
    channel: str,
    recipient: str | None = None,
    use_connectors: bool = False,
):
    init_db()
    ws = pd.Timestamp(week_start_for(date.today()))
    combined = load_inputs(payroll_path, schedule_path, ws, use_connectors)
    week_key = ws.strftime("%Y-%m-%d")
    save_snapshot(week_key, combined.to_dict("records"))
    rules = Rules(
        watch_30=float(os.getenv("WATCH_30", "30")),
        overtime_40=float(os.getenv("OVERTIME_40", "40")),
        critical_50=float(os.getenv("CRITICAL_50", "50")),
        lead_hours=float(os.getenv("LEAD_HOURS", "2")),
    )
    sent = 0
    for _, r in combined.iterrows():
        a = AssociateWeek(
            employee_id=str(r.employee_id), name=str(r["name"]), station=str(r.station),
            actual_hours=float(r.actual_hours), scheduled_remaining_hours=float(r.scheduled_remaining_hours),
            days_worked=int(r.days_worked), next_shift_hours=float(r.next_shift_hours), max_daily_hours=float(r.max_daily_hours),
            dot_regulated=bool(r.dot_regulated), missing_punch=bool(r.missing_punch), manager=str(r.manager), phone=str(r.phone), email=str(r.email)
        )
        for alert in evaluate(a, rules):
            fp = alert_fingerprint(alert, week_key)
            if was_sent(fp):
                continue
            msg = format_alert_message(alert)
            if channel == "slack":
                send_slack(msg); rec = "configured webhook"
            elif channel == "email":
                rec = recipient or os.getenv("ALERT_EMAIL") or a.email
                if not rec: continue
                send_email(rec, "AKAIROS Hours Alert", msg)
            elif channel == "sms":
                rec = recipient or os.getenv("ALERT_PHONE") or a.phone
                if not rec: continue
                send_sms_twilio(rec, msg)
            else:
                print(msg); rec = "stdout"
            mark_sent(fp, alert.severity, channel, rec, msg)
            sent += 1
    print(f"Processed {len(combined)} associates; sent {sent} new alerts.")


def run_repeating(
    payroll_path: str | None,
    schedule_path: str | None,
    channel: str,
    recipient: str | None,
    use_connectors: bool,
    repeat_hours: float,
    max_runs: int | None = None,
):
    if repeat_hours <= 0:
        raise ValueError("--repeat-hours must be greater than 0.")

    runs = 0
    while True:
        run_once(payroll_path, schedule_path, channel, recipient, use_connectors)
        runs += 1
        if max_runs is not None and runs >= max_runs:
            return
        time.sleep(repeat_hours * 3600)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--payroll")
    ap.add_argument("--schedule")
    ap.add_argument("--use-connectors", action="store_true")
    ap.add_argument("--repeat-hours", type=float, default=None, help="Run continuously and refresh on this interval. Use 2 for a two-hour refresh.")
    ap.add_argument("--max-runs", type=int, default=None, help="Optional safety/testing limit for --repeat-hours.")
    ap.add_argument("--channel", choices=["stdout", "slack", "email", "sms"], default="stdout")
    ap.add_argument("--recipient", default=None)
    args = ap.parse_args()
    if args.repeat_hours is None:
        run_once(args.payroll, args.schedule, args.channel, args.recipient, args.use_connectors)
    else:
        run_repeating(
            args.payroll,
            args.schedule,
            args.channel,
            args.recipient,
            args.use_connectors,
            args.repeat_hours,
            args.max_runs,
        )
