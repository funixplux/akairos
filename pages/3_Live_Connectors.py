from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from connectors import connector_statuses, load_live_inputs
from workweek import week_start_for, week_end_for

load_dotenv()
st.set_page_config(page_title="AKAIROS Live Connectors", page_icon="AK", layout="wide")

st.title("Live Schedule / Payroll Connectors")
st.caption("Worked hours → future shifts → projected hours → exact threshold date → manager notification")

week_start = st.date_input("AKAIROS workweek start", value=week_start_for(date.today()))
st.caption(f"Sunday–Saturday: {week_start:%b %d} – {week_end_for(week_start):%b %d}")

statuses = connector_statuses()
rows = []
for status in statuses:
    row = status.to_dict()
    row["ready"] = "Ready" if status.ready else "Needs setup"
    row["secret_configured"] = "Yes" if status.secret_configured else "No"
    rows.append(row)

st.subheader("Connector readiness")
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

ready = all(status.ready for status in statuses)
if st.button("Load live connector data", type="primary", disabled=not ready):
    try:
        live = load_live_inputs(week_start=pd.Timestamp(week_start), now=pd.Timestamp.now())
        st.session_state.actuals = live.actuals
        st.session_state.actual_detail = live.actual_detail
        st.session_state.schedule = live.schedule
        st.session_state.schedule_detail = live.schedule_detail
        st.session_state.combined = live.combined
        st.session_state.data_source = "Configured live connectors"
        st.session_state.last_loaded_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
        st.success(f"Loaded {len(live.combined)} associates. Return to the dashboard to review risk.")
    except Exception as exc:
        st.error(str(exc))

st.caption("Connector inputs must include: employee_id, name, date, hours. Station, manager, DOT, phone and email are recommended.")
st.caption("ROSTER_FILE_PATH can enrich manager email/phone routing without putting those details into schedule exports.")
st.caption("For unattended checks, run monitor.py --use-connectors --repeat-hours 2 --channel email (or sms/slack).")
