from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from amazon_portal import parse_work_summary_payload, portal_snapshot_to_actuals
from importers import combine_actuals_schedule

st.set_page_config(page_title="Amazon Site Import | AKAIROS Hours Guard", page_icon="🔗", layout="wide")

st.title("Amazon DSP Scheduling Site Import")
st.caption("Import the Working Hour Visibility response captured from the DSP Scheduling site without storing Amazon passwords, cookies, or tokens.")

st.info(
    "This importer understands the `daWorkSummaryAndEligibility` response from the DSP Scheduling site. "
    "It converts Amazon minute fields to hours and preserves each field separately so rolling schedule data is not double-counted."
)

source = st.radio("How do you want to provide the site data?", ["Upload JSON file", "Paste JSON response"], horizontal=True)

payload = None
if source == "Upload JSON file":
    f = st.file_uploader("Upload the JSON response", type=["json", "txt"])
    if f is not None:
        try:
            payload = json.loads(f.getvalue().decode("utf-8"))
        except Exception as exc:
            st.error(f"Could not read JSON: {exc}")
else:
    raw = st.text_area("Paste the JSON response", height=260, placeholder='{"data":{"daWorkSummaryAndEligibility":{...}}}')
    if raw.strip():
        try:
            payload = json.loads(raw)
        except Exception as exc:
            st.error(f"Could not read JSON: {exc}")

name_map: dict[str, str] = {}
st.subheader("Optional associate-name mapping")
st.caption("The Amazon response is keyed by DA IDs (for example, A34FQCJF4ID9T6). Upload a CSV with `employee_id,name` to show associate names in the dashboard.")
map_file = st.file_uploader("DA ID → name CSV", type=["csv"], key="da_name_map")
if map_file is not None:
    try:
        m = pd.read_csv(map_file)
        if {"employee_id", "name"}.issubset(m.columns):
            name_map = dict(zip(m["employee_id"].astype(str), m["name"].astype(str)))
            st.success(f"Loaded {len(name_map)} associate names.")
        else:
            st.warning("Mapping CSV needs columns named `employee_id` and `name`.")
    except Exception as exc:
        st.error(f"Could not read mapping CSV: {exc}")

if payload is not None:
    try:
        snapshot = parse_work_summary_payload(payload, name_map=name_map)
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    st.subheader("Amazon working-hour snapshot")
    st.dataframe(snapshot, use_container_width=True, hide_index=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Associates", len(snapshot))
    c2.metric("30h+ scheduled / last 7 days", int((snapshot["scheduled_last_7_days_hours"] >= 30).sum()))
    c3.metric("40h+ scheduled / last 7 days", int((snapshot["scheduled_last_7_days_hours"] >= 40).sum()))
    c4.metric("50h+ scheduled / last 7 days", int((snapshot["scheduled_last_7_days_hours"] >= 50).sum()))

    high = snapshot[snapshot["scheduled_last_7_days_hours"] >= 30].copy()
    if not high.empty:
        st.subheader("Scheduled-hour watch list from Amazon response")
        st.dataframe(
            high[[
                "name",
                "employee_id",
                "actual_work_week_hours",
                "actual_work_day_hours",
                "scheduled_week_hours",
                "scheduled_last_7_days_hours",
                "daily_leap_threshold_breached",
            ]].sort_values("scheduled_last_7_days_hours", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

    st.warning(
        "Important: `daScheduledLast7DaysMins` is a rolling scheduled-hours field. "
        "This importer does not assume it means future remaining hours. Future projection should come from the weekly schedule/roster dates to avoid double-counting."
    )

    if st.button("Use Amazon actual worked hours in Hours Guard", type="primary"):
        actuals = portal_snapshot_to_actuals(snapshot)
        st.session_state.actuals = actuals
        if "schedule" not in st.session_state:
            st.session_state.schedule = pd.DataFrame()
        st.session_state.combined = combine_actuals_schedule(st.session_state.actuals, st.session_state.schedule)
        st.session_state.amazon_work_summary = snapshot
        st.success(
            "Imported Amazon actual work-week hours into Hours Guard. "
            "Now load the dated weekly schedule/roster in the main app to calculate projected hours."
        )

    csv = snapshot.to_csv(index=False).encode("utf-8")
    st.download_button("Download normalized Amazon snapshot CSV", csv, file_name="amazon_work_summary_normalized.csv", mime="text/csv")

st.divider()
st.markdown(
    """
### What each Amazon field means in this importer
- `daActualWorkWeekMins` → actual work-week hours reported by the site.
- `daActualWorkDayMins` → actual work hours for the day represented by the response.
- `daScheduledDayMins` → scheduled minutes for that day.
- `daScheduledWeekMins` → scheduled minutes for the week context returned by the site.
- `daScheduledLast7DaysMins` → rolling scheduled minutes across the last seven days.
- `isDailyLeapThresholdBreached` → Amazon's daily threshold flag from the response.

The app keeps these concepts separate. It does not log in to Amazon or store browser-session secrets.
"""
)
