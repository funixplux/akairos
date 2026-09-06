from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from engine import AssociateWeek, Rules, evaluate, highest_severity
from importers import (
    read_table, guess_column, NAME_CANDIDATES, ID_CANDIDATES, DATE_CANDIDATES,
    HOURS_CANDIDATES, START_CANDIDATES, END_CANDIDATES, STATION_CANDIDATES,
    MANAGER_CANDIDATES, DOT_CANDIDATES, PHONE_CANDIDATES, EMAIL_CANDIDATES,
    prepare_actuals, prepare_schedule, combine_actuals_schedule,
)
from notifier import format_alert_message, send_email, send_slack, send_sms_twilio
from storage import init_db, recent_alerts

st.set_page_config(page_title="AKAIROS Hours Guard", page_icon="⏱️", layout="wide")
init_db()

if "combined" not in st.session_state:
    st.session_state.combined = pd.DataFrame()
if "actuals" not in st.session_state:
    st.session_state.actuals = pd.DataFrame()
if "schedule" not in st.session_state:
    st.session_state.schedule = pd.DataFrame()

st.title("AKAIROS Hours Guard")
st.caption("Payroll + schedule early-warning system for 30 / 40 / 50 hour thresholds, working-hour policy, and DOT HOS checks.")

with st.sidebar:
    st.subheader("Alert rules")
    t30 = st.number_input("30h watch", min_value=1.0, max_value=100.0, value=30.0, step=0.5)
    t40 = st.number_input("OT threshold", min_value=1.0, max_value=100.0, value=40.0, step=0.5)
    t50 = st.number_input("Critical threshold", min_value=1.0, max_value=100.0, value=50.0, step=0.5)
    lead = st.number_input("Warn this many hours early", min_value=0.0, max_value=12.0, value=2.0, step=0.5)
    st.divider()
    week_start_default = date.today() - timedelta(days=date.today().weekday())
    week_start = st.date_input("Week start", value=week_start_default)
    st.caption("30h is used as an AKAIROS planning/benefit-status watch. 40h is the overtime threshold. 50h is your critical management threshold. 60h is tracked as a separate Amazon working-hours limit.")

rules = Rules(watch_30=t30, overtime_40=t40, critical_50=t50, lead_hours=lead)

tab_dash, tab_import, tab_people, tab_notify, tab_rules = st.tabs(["Dashboard", "Import data", "Associates", "Notifications", "Rules"])


def row_to_assoc(row):
    return AssociateWeek(
        employee_id=str(row.get("employee_id", "")),
        name=str(row.get("name", "")),
        station=str(row.get("station", "")),
        actual_hours=float(row.get("actual_hours", 0) or 0),
        scheduled_remaining_hours=float(row.get("scheduled_remaining_hours", 0) or 0),
        days_worked=int(row.get("days_worked", 0) or 0),
        next_shift_hours=float(row.get("next_shift_hours", 0) or 0),
        max_daily_hours=float(row.get("max_daily_hours", 0) or 0),
        dot_regulated=bool(row.get("dot_regulated", False)),
        missing_punch=bool(row.get("missing_punch", False)),
        manager=str(row.get("manager", "")),
        phone=str(row.get("phone", "")),
        email=str(row.get("email", "")),
    )


def scored_df(df):
    if df is None or df.empty:
        return pd.DataFrame()
    rows=[]
    for _, r in df.iterrows():
        a=row_to_assoc(r)
        alerts=evaluate(a, rules)
        primary=max(alerts, key=lambda x:{"watch":1,"warning":2,"critical":3}.get(x.severity,0), default=None)
        rows.append({**r.to_dict(), "status": highest_severity(alerts).upper(), "alert_code": primary.code if primary else "OK", "alert_count": len(alerts)})
    return pd.DataFrame(rows)

with tab_dash:
    scored = scored_df(st.session_state.combined)
    if scored.empty:
        st.info("Import payroll/time data and the Amazon schedule in the Import data tab. You can also load the sample data to test the workflow immediately.")
        if st.button("Load sample AKAIROS data", type="primary"):
            base=Path(__file__).with_name("sample_data")
            actual_raw=read_table(base/"payroll.csv")
            sched_raw=read_table(base/"schedule.csv")
            amap={"name":"name","id":"employee_id","date":"date","hours":"hours","station":"station","manager":"manager","dot":"dot_regulated","phone":"phone","email":"email"}
            smap={"name":"name","id":"employee_id","date":"date","hours":"hours","station":"station","manager":"manager","dot":"dot_regulated","phone":"phone","email":"email"}
            ws=pd.Timestamp(week_start)
            st.session_state.actuals=prepare_actuals(actual_raw,amap,week_start=ws)
            st.session_state.schedule=prepare_schedule(sched_raw,smap,now=pd.Timestamp(week_start)+pd.Timedelta(days=3),week_start=ws)
            st.session_state.combined=combine_actuals_schedule(st.session_state.actuals,st.session_state.schedule)
            st.rerun()
    else:
        c1,c2,c3,c4,c5=st.columns(5)
        c1.metric("Associates", len(scored))
        c2.metric("30h watch", int((scored.status=="WATCH").sum()))
        c3.metric("40h/OT risk", int((scored.status=="WARNING").sum()))
        c4.metric("Critical", int((scored.status=="CRITICAL").sum()))
        c5.metric("Projected OT hrs", f"{(scored.projected_hours-rules.overtime_40).clip(lower=0).sum():.1f}")
        st.subheader("Current risk list")
        cols=["name","station","actual_hours","scheduled_remaining_hours","projected_hours","days_worked","status","alert_code"]
        st.dataframe(scored[cols], use_container_width=True, hide_index=True)

        st.subheader("Action queue")
        for _, row in scored[scored.status!="OK"].head(20).iterrows():
            a=row_to_assoc(row)
            alerts=evaluate(a,rules)
            with st.expander(f"{row['status']} · {a.name} · {a.projected_hours:.1f} projected hours"):
                for alert in alerts:
                    st.write(f"**{alert.code}:** {alert.message}")
                if a.projected_hours >= rules.overtime_40:
                    st.write("**Suggested manager action:** review remaining scheduled shifts, available backups, and overtime authorization before assigning additional work.")
                elif a.projected_hours >= rules.watch_30:
                    st.write("**Suggested manager action:** monitor the next shift and benefit/full-time eligibility implications; no automatic schedule reduction is required by this app.")

with tab_import:
    st.subheader("1. Import payroll / actual worked time")
    payroll_file=st.file_uploader("Payroll/timekeeping CSV or Excel", type=["csv","xlsx","xls"], key="payroll")
    if payroll_file:
        df=read_table(payroll_file)
        st.dataframe(df.head(10), use_container_width=True)
        cols=[""]+list(df.columns)
        def sel(label,cands,key):
            guess=guess_column(df,cands)
            idx=cols.index(guess) if guess in cols else 0
            return st.selectbox(label,cols,index=idx,key=key) or None
        with st.expander("Map payroll columns", expanded=True):
            p_name=sel("Associate name",NAME_CANDIDATES,"pn")
            p_id=sel("Employee ID (optional)",ID_CANDIDATES,"pi")
            p_date=sel("Work date",DATE_CANDIDATES,"pd")
            p_hours=sel("Worked hours (use this OR start/end)",HOURS_CANDIDATES,"ph")
            p_start=sel("Clock in / start",START_CANDIDATES,"ps")
            p_end=sel("Clock out / end",END_CANDIDATES,"pe")
            p_station=sel("Station",STATION_CANDIDATES,"pst")
            p_manager=sel("Manager",MANAGER_CANDIDATES,"pm")
            p_dot=sel("DOT status",DOT_CANDIDATES,"pdt")
            p_phone=sel("Phone",PHONE_CANDIDATES,"pph")
            p_email=sel("Email",EMAIL_CANDIDATES,"pem")
        if st.button("Process payroll file"):
            mapping={"name":p_name,"id":p_id,"date":p_date,"hours":p_hours,"start":p_start,"end":p_end,"station":p_station,"manager":p_manager,"dot":p_dot,"phone":p_phone,"email":p_email}
            try:
                st.session_state.actuals=prepare_actuals(df,mapping,week_start=pd.Timestamp(week_start))
                st.success(f"Processed {len(st.session_state.actuals)} associates from payroll/timekeeping.")
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.subheader("2. Import Amazon schedule / roster")
    schedule_file=st.file_uploader("Schedule CSV or Excel", type=["csv","xlsx","xls"], key="schedule")
    if schedule_file:
        df2=read_table(schedule_file)
        st.dataframe(df2.head(10), use_container_width=True)
        cols2=[""]+list(df2.columns)
        def sel2(label,cands,key):
            guess=guess_column(df2,cands)
            idx=cols2.index(guess) if guess in cols2 else 0
            return st.selectbox(label,cols2,index=idx,key=key) or None
        with st.expander("Map schedule columns", expanded=True):
            s_name=sel2("Associate name",NAME_CANDIDATES,"sn")
            s_id=sel2("Employee ID (optional)",ID_CANDIDATES,"si")
            s_date=sel2("Shift date",DATE_CANDIDATES,"sd")
            s_hours=sel2("Scheduled hours (use this OR start/end)",HOURS_CANDIDATES,"sh")
            s_start=sel2("Shift start",START_CANDIDATES,"ss")
            s_end=sel2("Shift end",END_CANDIDATES,"se")
            s_station=sel2("Station",STATION_CANDIDATES,"sst")
            s_manager=sel2("Manager",MANAGER_CANDIDATES,"sm")
            s_dot=sel2("DOT status",DOT_CANDIDATES,"sdt")
            s_phone=sel2("Phone",PHONE_CANDIDATES,"sph")
            s_email=sel2("Email",EMAIL_CANDIDATES,"sem")
        if st.button("Process schedule file"):
            mapping={"name":s_name,"id":s_id,"date":s_date,"hours":s_hours,"start":s_start,"end":s_end,"station":s_station,"manager":s_manager,"dot":s_dot,"phone":s_phone,"email":s_email}
            try:
                st.session_state.schedule=prepare_schedule(df2,mapping,now=pd.Timestamp.today(),week_start=pd.Timestamp(week_start))
                st.success(f"Processed {len(st.session_state.schedule)} associates from the schedule.")
            except Exception as e:
                st.error(str(e))

    st.divider()
    if st.button("Combine payroll + schedule", type="primary"):
        st.session_state.combined=combine_actuals_schedule(st.session_state.actuals, st.session_state.schedule)
        st.success(f"Combined {len(st.session_state.combined)} associates. Open Dashboard.")

    st.caption("For a production connection to the DSP Scheduling Portal, use an approved export/API or a controlled integration. Do not place Amazon passwords in the app or source code.")

with tab_people:
    scored=scored_df(st.session_state.combined)
    if scored.empty:
        st.info("No associate data loaded yet.")
    else:
        names=scored["name"].tolist()
        selected=st.selectbox("Associate", names)
        row=scored[scored.name==selected].iloc[0]
        a=row_to_assoc(row)
        c1,c2,c3,c4=st.columns(4)
        c1.metric("Worked",f"{a.actual_hours:.1f}h")
        c2.metric("Remaining scheduled",f"{a.scheduled_remaining_hours:.1f}h")
        c3.metric("Projected",f"{a.projected_hours:.1f}h")
        c4.metric("Days worked",a.days_worked)
        alerts=evaluate(a,rules)
        if not alerts: st.success("No active threshold or policy alert.")
        for alert in alerts:
            (st.error if alert.severity=="critical" else st.warning if alert.severity=="warning" else st.info)(f"{alert.code}: {alert.message}")
        st.text_area("Owner notification preview", format_alert_message(alerts[0]) if alerts else f"{a.name} has no current alert.", height=150)

with tab_notify:
    st.subheader("Send a test notification")
    scored=scored_df(st.session_state.combined)
    if scored.empty:
        st.info("Load data first.")
    else:
        risk=scored[scored.status!="OK"]
        if risk.empty:
            st.success("No active alerts.")
        else:
            pick=st.selectbox("Alert", risk.index, format_func=lambda i:f"{risk.loc[i,'name']} · {risk.loc[i,'alert_code']} · {risk.loc[i,'projected_hours']:.1f}h")
            a=row_to_assoc(risk.loc[pick])
            alerts=evaluate(a,rules)
            alert=alerts[0]
            msg=st.text_area("Message",format_alert_message(alert),height=160)
            channel=st.selectbox("Channel",["Preview only","Slack webhook","Email","SMS (Twilio)"])
            recipient=st.text_input("Recipient (email or phone; Slack uses configured webhook)", value=a.email if channel=="Email" else a.phone if channel.startswith("SMS") else "")
            if st.button("Send notification", type="primary"):
                try:
                    if channel=="Preview only": st.success("Preview generated; nothing was sent.")
                    elif channel=="Slack webhook": send_slack(msg); st.success("Slack notification sent.")
                    elif channel=="Email": send_email(recipient,"AKAIROS Hours Alert",msg); st.success("Email sent.")
                    elif channel.startswith("SMS"): send_sms_twilio(recipient,msg); st.success("SMS sent.")
                except Exception as e:
                    st.error(str(e))
    st.subheader("Recent sent-alert log")
    logs=recent_alerts(50)
    if logs: st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)
    else: st.caption("No logged automated sends yet. Use monitor.py for scheduled sending with deduplication.")

with tab_rules:
    st.markdown("""
### Rules implemented
- **30 hours:** AKAIROS planning / benefit-status watch threshold. This app treats it as a warning, not an overtime trigger.
- **40 hours:** weekly overtime threshold used for early warning and schedule review.
- **50 hours:** AKAIROS management critical threshold requested for this app.
- **60 hours:** Amazon working-hours policy limit in a rolling seven-day period, except special/emergency situations.
- **12 hours/day:** Amazon Supplier working-hours limit tracked as a critical exception.
- **10 hours rest:** minimum rest between shifts tracked as a critical exception.
- **DOT HOS:** 10 hours off between blocks, 11-hour driving limit after rest, 14-hour duty window, and 70 hours on duty in 8 consecutive days when the required data is available.
- **Missing punch:** always flagged because incomplete time data can understate actual hours.

The application does not alter payroll punches or schedules automatically. It signals managers for review and keeps the actual time record separate from schedule planning.
""")
