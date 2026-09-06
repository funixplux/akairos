from __future__ import annotations

import argparse
import os
from datetime import date, timedelta

import pandas as pd
from dotenv import load_dotenv

from engine import AssociateWeek, Rules, evaluate, alert_fingerprint
from importers import read_table, prepare_actuals, prepare_schedule, combine_actuals_schedule
from notifier import format_alert_message, send_email, send_slack, send_sms_twilio
from storage import init_db, was_sent, mark_sent, save_snapshot

load_dotenv()


def week_start_for(d: date):
    return d - timedelta(days=d.weekday())


def run_once(payroll_path: str, schedule_path: str, channel: str, recipient: str | None = None):
    init_db()
    ws=pd.Timestamp(week_start_for(date.today()))
    p=read_table(payroll_path)
    s=read_table(schedule_path)
    mapping={"name":"name","id":"employee_id","date":"date","hours":"hours","station":"station","manager":"manager","dot":"dot_regulated","phone":"phone","email":"email"}
    actual=prepare_actuals(p,mapping,week_start=ws)
    sched=prepare_schedule(s,mapping,now=pd.Timestamp.today(),week_start=ws)
    combined=combine_actuals_schedule(actual,sched)
    week_key=ws.strftime("%Y-%m-%d")
    save_snapshot(week_key, combined.to_dict("records"))
    rules=Rules(
        watch_30=float(os.getenv("WATCH_30","30")),
        overtime_40=float(os.getenv("OVERTIME_40","40")),
        critical_50=float(os.getenv("CRITICAL_50","50")),
        lead_hours=float(os.getenv("LEAD_HOURS","2")),
    )
    sent=0
    for _,r in combined.iterrows():
        a=AssociateWeek(
            employee_id=str(r.employee_id),name=str(r["name"]),station=str(r.station),
            actual_hours=float(r.actual_hours),scheduled_remaining_hours=float(r.scheduled_remaining_hours),
            days_worked=int(r.days_worked),next_shift_hours=float(r.next_shift_hours),max_daily_hours=float(r.max_daily_hours),
            dot_regulated=bool(r.dot_regulated),missing_punch=bool(r.missing_punch),manager=str(r.manager),phone=str(r.phone),email=str(r.email)
        )
        for alert in evaluate(a,rules):
            fp=alert_fingerprint(alert,week_key)
            if was_sent(fp):
                continue
            msg=format_alert_message(alert)
            if channel=="slack":
                send_slack(msg); rec="configured webhook"
            elif channel=="email":
                rec=recipient or os.getenv("ALERT_EMAIL") or a.email
                if not rec: continue
                send_email(rec,"AKAIROS Hours Alert",msg)
            elif channel=="sms":
                rec=recipient or os.getenv("ALERT_PHONE") or a.phone
                if not rec: continue
                send_sms_twilio(rec,msg)
            else:
                print(msg); rec="stdout"
            mark_sent(fp,alert.severity,channel,rec,msg)
            sent+=1
    print(f"Processed {len(combined)} associates; sent {sent} new alerts.")


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--payroll",required=True)
    ap.add_argument("--schedule",required=True)
    ap.add_argument("--channel",choices=["stdout","slack","email","sms"],default="stdout")
    ap.add_argument("--recipient",default=None)
    args=ap.parse_args()
    run_once(args.payroll,args.schedule,args.channel,args.recipient)
