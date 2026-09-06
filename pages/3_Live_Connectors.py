from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from connectors import connector_statuses, load_live_inputs


load_dotenv()
st.set_page_config(page_title="AKAIROS Live Connectors", page_icon="AK", layout="wide")


def week_start_default() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


st.title("Live Schedule / Payroll Connectors")
st.caption("Worked hours -> remaining shifts -> projected hours -> OT risk -> manager notification")

week_start = st.date_input("Week start", value=week_start_default())
statuses = connector_statuses()
rows = []
for status in statuses:
    row = status.to_dict()
    row["ready"] = "Ready" if status.ready else "Needs setup"
    row["secret_configured"] = "Yes" if status.secret_configured else "No"
    rows.append(row)

st.subheader("Connector readiness")
st.dataframe(
    pd.DataFrame(rows),
    width="stretch",
    hide_index=True,
    column_config={
        "key": "Connector",
        "source": "Source",
        "mode": "Mode",
        "ready": "Status",
        "detail": "Detail",
        "secret_configured": "Secret",
    },
)

ready = all(status.ready for status in statuses)
if st.button("Load live connector data", type="primary", disabled=not ready):
    try:
        live = load_live_inputs(week_start=pd.Timestamp(week_start), now=pd.Timestamp.today())
        st.session_state.actuals = live.actuals
        st.session_state.schedule = live.schedule
        st.session_state.combined = live.combined
        st.session_state.data_source = "Configured live connectors"
        st.session_state.last_loaded_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
        st.success(f"Loaded {len(live.combined)} associates from live connectors. Return to the dashboard to review risk.")
    except Exception as exc:
        st.error(str(exc))

st.caption("Connector inputs must use standardized columns: employee_id, name, date, hours, station, manager, dot_regulated, phone, email.")
st.caption("API tokens are read from environment variables only and are not shown in the app.")
st.caption("For two-hour automated refresh and notifications, run monitor.py with --use-connectors --repeat-hours 2.")
