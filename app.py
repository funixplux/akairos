from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from engine import AssociateWeek, Rules, evaluate, highest_severity
from importers import (
    DATE_CANDIDATES, DOT_CANDIDATES, EMAIL_CANDIDATES, END_CANDIDATES,
    HOURS_CANDIDATES, ID_CANDIDATES, MANAGER_CANDIDATES, NAME_CANDIDATES,
    PHONE_CANDIDATES, START_CANDIDATES, STATION_CANDIDATES,
    combine_actuals_schedule, guess_column, normalize_actual_rows,
    normalize_schedule_rows, prepare_actuals, prepare_schedule, read_table,
)
from notifier import format_alert_message, send_email, send_slack, send_sms_twilio
from planner import crossing_summary, project_threshold_crossings
from roster import enrich_with_roster, normalize_roster
from storage import init_db, recent_alerts
from workweek import week_end_for, week_start_for

st.set_page_config(page_title="AKAIROS Hours Guard", page_icon="⏱️", layout="wide")
init_db()
for key in ["actuals", "actual_detail", "schedule", "schedule_detail", "roster", "combined"]:
    st.session_state.setdefault(key, pd.DataFrame())

st.title("AKAIROS Hours Guard")
st.caption("Actual payroll time + future schedule = early warning before 30, 40 and 50 hours.")

with st.sidebar:
    t30 = st.number_input("30h watch", 1.0, 100.0, 30.0, 0.5)
    t40 = st.number_input("OT threshold", 1.0, 100.0, 40.0, 0.5)
    t50 = st.number_input("Critical threshold", 1.0, 100.0, 50.0, 0.5)
    lead = st.number_input("Warn hours early", 0.0, 12.0, 2.0, 0.5)
    week_start = st.date_input("AKAIROS week start", week_start_for(date.today()))
    st.caption(f"Sunday–Saturday: {week_start:%b %d} – {week_end_for(week_start):%b %d}")

rules = Rules(watch_30=t30, overtime_40=t40, critical_50=t50, lead_hours=lead)


def text(v):
    return "" if v is None or pd.isna(v) else str(v)


def associate(row) -> AssociateWeek:
    return AssociateWeek(
        employee_id=text(row.get("employee_id")), name=text(row.get("name")), station=text(row.get("station")),
        actual_hours=float(row.get("actual_hours", 0) or 0), scheduled_remaining_hours=float(row.get("scheduled_remaining_hours", 0) or 0),
        days_worked=int(row.get("days_worked", 0) or 0), scheduled_days=int(row.get("scheduled_days", 0) or 0),
        next_shift_hours=float(row.get("next_shift_hours", 0) or 0), next_shift_date=text(row.get("next_shift_date"))[:10],
        max_daily_hours=float(row.get("max_daily_hours", 0) or 0), max_scheduled_shift_hours=float(row.get("max_scheduled_shift_hours", 0) or 0),
        dot_regulated=bool(row.get("dot_regulated", False)), missing_punch=bool(row.get("missing_punch", False)),
        manager=text(row.get("manager")), manager_email=text(row.get("manager_email")), manager_phone=text(row.get("manager_phone")),
        phone=text(row.get("phone")), email=text(row.get("email")),
        cross_30_date=text(row.get("cross_30_date")), cross_40_date=text(row.get("cross_40_date")),
        cross_50_date=text(row.get("cross_50_date")), cross_60_date=text(row.get("cross_60_date")),
    )


def rebuild():
    combined = combine_actuals_schedule(st.session_state.actuals, st.session_state.schedule)
    crossings = project_threshold_crossings(st.session_state.actuals, st.session_state.schedule_detail, (30, 40, 50, 60))
    summary = crossing_summary(crossings)
    if not summary.empty:
        combined = combined.merge(summary, on="employee_id", how="left")
    st.session_state.combined = enrich_with_roster(combined, st.session_state.roster)


def score(df):
    rows = []
    for _, r in df.iterrows():
        a = associate(r)
        alerts = evaluate(a, rules)
        primary = max(alerts, key=lambda x: {"watch": 1, "warning": 2, "critical": 3}.get(x.severity, 0), default=None)
        rows.append({**r.to_dict(), "status": highest_severity(alerts).upper(), "alert_code": primary.code if primary else "OK", "crossing_date": primary.crossing_date if primary else ""})
    return pd.DataFrame(rows)


def mapping_controls(df, prefix):
    cols = [""] + list(df.columns)
    def pick(label, candidates, suffix):
        guess = guess_column(df, candidates)
        idx = cols.index(guess) if guess in cols else 0
        return st.selectbox(label, cols, idx, key=f"{prefix}_{suffix}") or None
    return {
        "name": pick("Associate name", NAME_CANDIDATES, "name"),
        "id": pick("Employee ID", ID_CANDIDATES, "id"),
        "date": pick("Date", DATE_CANDIDATES, "date"),
        "hours": pick("Hours (or map start/end)", HOURS_CANDIDATES, "hours"),
        "start": pick("Start / Day In", START_CANDIDATES, "start"),
        "end": pick("End / Day Out", END_CANDIDATES, "end"),
        "station": pick("Station", STATION_CANDIDATES, "station"),
        "manager": pick("Manager", MANAGER_CANDIDATES, "manager"),
        "dot": pick("DOT status", DOT_CANDIDATES, "dot"),
        "phone": pick("Phone", PHONE_CANDIDATES, "phone"),
        "email": pick("Email", EMAIL_CANDIDATES, "email"),
    }


tab1, tab2, tab3, tab4 = st.tabs(["Dashboard", "Data sources", "Associate detail", "Notifications"])

with tab1:
    if st.session_state.combined.empty:
        st.info("Load payroll and schedule data in Data sources.")
        if st.button("Load sample data"):
            base = Path(__file__).with_name("sample_data")
            p, s = read_table(base / "payroll.csv"), read_table(base / "schedule.csv")
            m = {"name":"name","id":"employee_id","date":"date","hours":"hours","station":"station","manager":"manager","dot":"dot_regulated","phone":"phone","email":"email"}
            ws = pd.Timestamp(week_start)
            source_ws = pd.Timestamp(week_start_for(pd.to_datetime(p["date"]).min()))
            for frame in (p, s):
                frame["date"] = ws + pd.to_timedelta((pd.to_datetime(frame["date"]).dt.normalize() - source_ws).dt.days, unit="D")
            st.session_state.actual_detail = normalize_actual_rows(p, m, ws)
            st.session_state.actuals = prepare_actuals(p, m, ws)
            demo_now = ws + pd.Timedelta(days=4, hours=23)
            st.session_state.schedule_detail = normalize_schedule_rows(s, m, demo_now, ws, st.session_state.actual_detail)
            st.session_state.schedule = prepare_schedule(s, m, demo_now, ws, st.session_state.actual_detail)
            rebuild(); st.rerun()
    else:
        scored = score(st.session_state.combined)
        stations = ["All"] + sorted(x for x in scored.station.fillna("").unique() if x)
        managers = ["All"] + sorted(x for x in scored.manager.fillna("").unique() if x)
        c1, c2 = st.columns(2)
        sf, mf = c1.selectbox("Station", stations), c2.selectbox("Manager", managers)
        view = scored[(scored.station == sf) if sf != "All" else pd.Series(True, index=scored.index)]
        if mf != "All": view = view[view.manager == mf]
        a,b,c,d,e = st.columns(5)
        a.metric("Associates", len(view)); b.metric("30h watch", int((view.status=="WATCH").sum())); c.metric("OT risk", int((view.status=="WARNING").sum())); d.metric("Critical", int((view.status=="CRITICAL").sum())); e.metric("Projected OT", f"{(view.projected_hours-t40).clip(lower=0).sum():.1f}h")
        cols = ["name","station","manager","actual_hours","scheduled_remaining_hours","projected_hours","next_shift_date","status","alert_code","crossing_date"]
        st.dataframe(view[[x for x in cols if x in view]], use_container_width=True, hide_index=True)
        risk = view[view.status != "OK"]
        st.download_button("Download manager action queue", risk.to_csv(index=False).encode(), f"hours_action_queue_{week_start}.csv", "text/csv", disabled=risk.empty)
        for _, r in risk.head(30).iterrows():
            arow = associate(r)
            with st.expander(f"{r.status} · {arow.name} · {arow.actual_hours:.1f} worked / {arow.projected_hours:.1f} projected"):
                for al in evaluate(arow, rules): st.write(f"**{al.code}:** {al.message}")

with tab2:
    st.subheader("Payroll / actual time")
    pf = st.file_uploader("Payroll/timekeeping CSV or Excel", type=["csv","xlsx","xls"], key="payroll")
    if pf:
        pdf = read_table(pf); st.dataframe(pdf.head(10), use_container_width=True)
        pm = mapping_controls(pdf, "p")
        if st.button("Process payroll"):
            ws = pd.Timestamp(week_start)
            st.session_state.actual_detail = normalize_actual_rows(pdf, pm, ws)
            st.session_state.actuals = prepare_actuals(pdf, pm, ws)
            st.success(f"Loaded {len(st.session_state.actuals)} associates.")

    st.subheader("Amazon future schedule / roster")
    sf = st.file_uploader("Schedule CSV or Excel", type=["csv","xlsx","xls"], key="schedule")
    if sf:
        sdf = read_table(sf); st.dataframe(sdf.head(10), use_container_width=True)
        sm = mapping_controls(sdf, "s")
        if st.button("Process schedule"):
            ws = pd.Timestamp(week_start); now = pd.Timestamp.now()
            st.session_state.schedule_detail = normalize_schedule_rows(sdf, sm, now, ws, st.session_state.actual_detail)
            st.session_state.schedule = prepare_schedule(sdf, sm, now, ws, st.session_state.actual_detail)
            st.success(f"Loaded future shifts for {len(st.session_state.schedule)} associates.")

    st.subheader("Manager routing roster")
    rf = st.file_uploader("Roster CSV or Excel", type=["csv","xlsx","xls"], key="roster")
    if rf:
        st.session_state.roster = normalize_roster(read_table(rf))
        st.dataframe(st.session_state.roster, use_container_width=True, hide_index=True)

    if st.button("Combine and run alerts", type="primary"):
        rebuild(); st.success("Hours Guard refreshed. Open Dashboard.")
    st.caption("For unattended use, configure file/API connectors or sync_inputs.py. Amazon passwords are never stored in source code.")

with tab3:
    if st.session_state.combined.empty:
        st.info("Load data first.")
    else:
        scored = score(st.session_state.combined)
        name = st.selectbox("Associate", scored.name.tolist())
        r = scored[scored.name == name].iloc[0]; arow = associate(r)
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Worked", f"{arow.actual_hours:.1f}h"); c2.metric("Future scheduled", f"{arow.scheduled_remaining_hours:.1f}h"); c3.metric("Projected", f"{arow.projected_hours:.1f}h"); c4.metric("Projected days", arow.projected_days)
        if arow.next_shift_date: st.write(f"**Next shift:** {arow.next_shift_date} · {arow.next_shift_hours:.1f}h")
        alerts = evaluate(arow, rules)
        if not alerts: st.success("No active alert.")
        for al in alerts: (st.error if al.severity=="critical" else st.warning if al.severity=="warning" else st.info)(f"{al.code}: {al.message}")

with tab4:
    if st.session_state.combined.empty:
        st.info("Load data first.")
    else:
        scored = score(st.session_state.combined); risk = scored[scored.status != "OK"]
        if risk.empty: st.success("No active alerts.")
        else:
            idx = st.selectbox("Alert", risk.index, format_func=lambda i: f"{risk.loc[i,'name']} · {risk.loc[i,'alert_code']}")
            arow = associate(risk.loc[idx]); al = evaluate(arow, rules)[0]
            msg = st.text_area("Message", format_alert_message(al, arow), 190)
            channel = st.selectbox("Channel", ["Preview only","Slack webhook","Email","SMS (Twilio)"])
            recipient = st.text_input("Recipient", arow.manager_email if channel=="Email" else arow.manager_phone if channel.startswith("SMS") else "")
            if st.button("Send notification"):
                try:
                    if channel=="Preview only": st.success("Preview only; nothing sent.")
                    elif channel=="Slack webhook": send_slack(msg); st.success("Sent.")
                    elif channel=="Email": send_email(recipient, "AKAIROS Hours Alert", msg); st.success("Sent.")
                    else: send_sms_twilio(recipient, msg); st.success("Sent.")
                except Exception as exc: st.error(str(exc))
    logs = recent_alerts(50)
    if logs: st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)
