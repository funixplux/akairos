"""AKAIROS Cortex Performance Monitor — Streamlit page for Hours Guard."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from akos_performance_monitor.evaluate import evaluate_catalog, load_roster, render_summary
from akos_performance_monitor.notify import maybe_send, resolve_recipients
from akos_performance_monitor.results_view import (
    bridge_hours_guard_smtp_env,
    flatten_data_gaps,
    flatten_flagged_drivers,
    flatten_report_status,
    save_uploads,
    smtp_ready,
)

load_dotenv()

PKG = Path(__file__).resolve().parents[1] / "akos_performance_monitor"
DEFAULT_CONFIG = PKG / "config.json"
DEFAULT_REPORTS = PKG / "reports"
DEFAULT_ROSTER = PKG / "roster.csv"
RUNTIME_UPLOADS = Path(__file__).resolve().parents[1] / "runtime" / "performance_monitor_uploads"
RUNTIME_OUTPUT = Path(__file__).resolve().parents[1] / "runtime" / "performance_monitor_output"

st.set_page_config(page_title="Performance Monitor | AKAIROS", page_icon="AK", layout="wide")

st.title("Cortex Performance Monitor")
st.caption(
    "Review AKOS DVA5 Cortex reports (DVIC, Compliance, break utilization, and related packs). "
    "DVIC alert cutover is 6 minutes (360 seconds) for all fleets. "
    "Does not automate Amazon login or credential capture."
)

with st.sidebar:
    st.subheader("Review settings")
    as_of = st.date_input("Review date", value=date.today())
    config_path = st.text_input("Config path", value=str(DEFAULT_CONFIG))
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except Exception as exc:
        st.error(f"Could not load config: {exc}")
        st.stop()

    dvic = config.setdefault("dvic", {})
    alert_seconds = float(dvic.get("alert_max_seconds") or (float(dvic.get("alert_max_minutes", 6)) * 60))
    st.metric("DVIC alert threshold", f"{alert_seconds:.0f}s", help="AKAIROS flat cutover for NonDOT and DOT")
    override = st.number_input(
        "Override DVIC max seconds",
        min_value=60,
        max_value=3600,
        value=int(alert_seconds),
        step=30,
    )
    config["dvic"]["alert_max_seconds"] = float(override)
    config["dvic"]["alert_max_minutes"] = float(override) / 60.0
    config["email_named_driver_details"] = st.checkbox(
        "Include named-driver details in email",
        value=bool(config.get("email_named_driver_details", True)),
    )
    notify_to = st.text_input(
        "Email recipient",
        value=(config.get("notify_to_default") or "etimbassey@akairos.net"),
    )
    config["notify_to"] = notify_to

st.subheader("1. Report source")
source_mode = st.radio(
    "How do you want to provide Cortex files?",
    ["Upload report files", "Use a reports folder"],
    horizontal=True,
    index=1,  # folder path is the usual Cortex drop location
)

reports_dir: Path | None = None
uploaded_names: list[str] = []

if source_mode == "Upload report files":
    uploads = st.file_uploader(
        "Upload Cortex CSV / XLSX / PDF files",
        type=["csv", "xlsx", "xls", "pdf"],
        accept_multiple_files=True,
    )
    if uploads:
        reports_dir = RUNTIME_UPLOADS / as_of.isoformat()
        # Fresh folder per review date so stale uploads do not mix in
        if reports_dir.exists():
            for old in reports_dir.iterdir():
                if old.is_file():
                    old.unlink()
        uploaded_names = save_uploads(uploads, reports_dir)
        st.success(f"Staged {len(uploaded_names)} file(s) under `{reports_dir}`")
else:
    folder = st.text_input("Reports folder path", value=str(DEFAULT_REPORTS))
    reports_dir = Path(folder)
    if reports_dir.exists():
        files = sorted(p.name for p in reports_dir.iterdir() if p.is_file())
        st.caption(f"{len(files)} file(s) in folder")
        if files:
            st.code("\n".join(files), language=None)
    else:
        st.warning(f"Folder does not exist yet: `{reports_dir}` — create it or upload files instead.")

st.subheader("2. Roster (optional)")
roster_mode = st.radio("Roster source", ["Example / package roster", "Upload CSV", "Skip"], horizontal=True)
roster: dict[str, str] = {}
if roster_mode == "Example / package roster":
    roster_path = DEFAULT_ROSTER if DEFAULT_ROSTER.exists() else PKG / "roster.example.csv"
    if roster_path.exists():
        roster = load_roster(roster_path, as_of.isoformat())
        st.caption(f"Loaded {len(roster)} scheduled driver(s) from `{roster_path.name}`")
    else:
        st.caption("No roster file found.")
elif roster_mode == "Upload CSV":
    roster_file = st.file_uploader("Roster CSV (`date,driver,scheduled`)", type=["csv"], key="pm_roster")
    if roster_file is not None:
        tmp = RUNTIME_OUTPUT / "roster_upload.csv"
        RUNTIME_OUTPUT.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(roster_file.getvalue())
        roster = load_roster(tmp, as_of.isoformat())
        st.success(f"Loaded {len(roster)} scheduled driver(s)")

ready = bool(reports_dir and reports_dir.exists() and any(reports_dir.iterdir()))
col_run, col_auto = st.columns([1, 2])
with col_run:
    run_clicked = st.button("Run performance review", type="primary", disabled=not ready)
with col_auto:
    auto_run = st.checkbox("Auto-run when reports are ready", value=True)

run_key = None
if ready and reports_dir is not None:
    names = sorted(p.name for p in reports_dir.iterdir() if p.is_file())
    run_key = f"{reports_dir}|{as_of.isoformat()}|{override}|{','.join(names)}|{len(roster)}"

should_run = False
if run_clicked:
    should_run = True
elif auto_run and run_key and st.session_state.get("pm_run_key") != run_key:
    should_run = True

if should_run:
    if reports_dir is None or not reports_dir.exists():
        st.error("Provide report files or a valid reports folder.")
    else:
        with st.spinner("Evaluating Cortex catalog…"):
            result = evaluate_catalog(reports_dir, roster, config, as_of=as_of)
            body = render_summary(result, include_named_details=bool(config.get("email_named_driver_details", True)))
            RUNTIME_OUTPUT.mkdir(parents=True, exist_ok=True)
            out_json = RUNTIME_OUTPUT / f"review_{as_of.isoformat()}.json"
            out_txt = RUNTIME_OUTPUT / f"review_{as_of.isoformat()}.txt"
            out_json.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
            out_txt.write_text(body, encoding="utf-8")
            st.session_state["pm_result"] = result
            st.session_state["pm_body"] = body
            st.session_state["pm_as_of"] = as_of.isoformat()
            st.session_state["pm_config"] = config
            st.session_state["pm_run_key"] = run_key

result = st.session_state.get("pm_result")
body = st.session_state.get("pm_body")

if result:
    st.subheader("3. Results")
    c1, c2, c3, c4 = st.columns(4)
    flagged = flatten_flagged_drivers(result)
    gaps = flatten_data_gaps(result)
    c1.metric("Files seen", len(result.get("files_seen") or []))
    c2.metric("Flagged findings", len(flagged))
    c3.metric("Data gaps", len(gaps))
    c4.metric("Absent from reports", len(result.get("absent_from_report") or []))

    st.markdown("#### Data gaps")
    if gaps:
        st.dataframe(pd.DataFrame(gaps), use_container_width=True, hide_index=True)
    else:
        st.success("No data gaps for expected daily/weekly kinds.")

    st.markdown("#### Flagged drivers")
    if flagged:
        st.dataframe(pd.DataFrame(flagged), use_container_width=True, hide_index=True)
    else:
        st.info("No drivers flagged from available columns (or no driver-level metrics matched).")

    absent = result.get("absent_from_report") or []
    if absent:
        st.markdown("#### Scheduled drivers absent from driver-level reports")
        st.write(", ".join(absent))

    st.markdown("#### Reports processed")
    st.dataframe(pd.DataFrame(flatten_report_status(result)), use_container_width=True, hide_index=True)

    with st.expander("Full text summary", expanded=False):
        st.text(body or "")

    st.subheader("4. Email authorized recipient")
    bridge_hours_guard_smtp_env()
    recipients = resolve_recipients(st.session_state.get("pm_config") or config)
    st.caption(
        f"Recipient(s): {', '.join(recipients) or '(none)'}. "
        "Named-driver DVIC/performance details are authorized for etimbassey@akairos.net."
    )
    if not smtp_ready():
        st.warning(
            "SMTP not configured. Set `AKOS_SMTP_*` or Hours Guard `SMTP_*` in `.env`, then restart Streamlit."
        )
    force = st.checkbox("Send even if content matches last email (bypass de-dupe)", value=False)
    if st.button("Send email summary", disabled=not smtp_ready() or not body):
        try:
            state_path = RUNTIME_OUTPUT / "last_sent.json"
            if force and state_path.exists():
                state_path.unlink()
            info = maybe_send(
                subject=f"AKAIROS Cortex performance review - {st.session_state.get('pm_as_of', as_of.isoformat())}",
                body=body,
                recipients=recipients,
                state_path=state_path,
                send=True,
            )
            if info.get("sent"):
                st.success(f"Email sent to {', '.join(recipients)}")
            elif info.get("skipped_duplicate"):
                st.info("Email skipped — identical content already sent to these recipients. Enable bypass to resend.")
            else:
                st.warning("Email was not sent.")
        except Exception as exc:
            st.error(f"Send failed: {exc}")
else:
    st.info("Upload or select reports (auto-run is on by default for a folder with files).")
