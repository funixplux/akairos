from __future__ import annotations

from dataclasses import asdict, dataclass
from io import StringIO
import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from importers import (
    combine_actuals_schedule,
    normalize_actual_rows,
    normalize_schedule_rows,
    prepare_actuals,
    prepare_schedule,
    read_table,
)
from planner import project_threshold_crossings, crossing_summary
from roster import enrich_with_roster, normalize_roster

STANDARD_MAPPING = {
    "name": "name",
    "id": "employee_id",
    "date": "date",
    "hours": "hours",
    "station": "station",
    "manager": "manager",
    "dot": "dot_regulated",
    "phone": "phone",
    "email": "email",
}
STANDARD_COLUMNS = ("employee_id", "name", "date", "hours")


@dataclass(frozen=True)
class ConnectorSpec:
    key: str
    label: str
    env_prefix: str
    default_token_env: str


@dataclass(frozen=True)
class ConnectorStatus:
    key: str
    source: str
    mode: str
    ready: bool
    detail: str
    secret_configured: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiveInputs:
    actuals: pd.DataFrame
    actual_detail: pd.DataFrame
    schedule: pd.DataFrame
    schedule_detail: pd.DataFrame
    combined: pd.DataFrame
    statuses: list[ConnectorStatus]


PAYROLL_SPEC = ConnectorSpec("payroll", "Payroll / timekeeping", "PAYROLL", "PAYROLL_API_TOKEN")
SCHEDULE_SPEC = ConnectorSpec("schedule", "Amazon DSP schedule", "DSP_SCHEDULE", "DSP_SCHEDULE_API_TOKEN")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _mode(spec: ConnectorSpec) -> str:
    raw = _env(f"{spec.env_prefix}_CONNECTOR_TYPE", "disabled").lower()
    return {"api": "http", "csv": "file", "xlsx": "file"}.get(raw, raw)


def connector_status(spec: ConnectorSpec) -> ConnectorStatus:
    mode = _mode(spec)
    if mode == "disabled":
        return ConnectorStatus(spec.key, spec.label, mode, False, f"Set {spec.env_prefix}_CONNECTOR_TYPE to file or http.")
    if mode == "file":
        path = _env(f"{spec.env_prefix}_FILE_PATH")
        ready = bool(path and Path(path).expanduser().exists())
        detail = f"Path configured: {Path(path).name}" if ready else "Configured file path was not found." if path else "No file path configured."
        return ConnectorStatus(spec.key, spec.label, mode, ready, detail)
    if mode == "http":
        url = _env(f"{spec.env_prefix}_API_URL")
        token_env = _env(f"{spec.env_prefix}_API_TOKEN_ENV", spec.default_token_env)
        secret_configured = bool(_env(token_env))
        detail = "Endpoint and token environment variable are configured." if url and secret_configured else f"Set {spec.env_prefix}_API_URL and secret in {token_env}."
        return ConnectorStatus(spec.key, spec.label, mode, bool(url and secret_configured), detail, secret_configured)
    return ConnectorStatus(spec.key, spec.label, mode or "unknown", False, "Unsupported connector type. Use disabled, file, or http.")


def connector_statuses() -> list[ConnectorStatus]:
    return [connector_status(PAYROLL_SPEC), connector_status(SCHEDULE_SPEC)]


def _load_http_table(spec: ConnectorSpec) -> pd.DataFrame:
    url = _env(f"{spec.env_prefix}_API_URL")
    token_env = _env(f"{spec.env_prefix}_API_TOKEN_ENV", spec.default_token_env)
    token = _env(token_env)
    if not url:
        raise RuntimeError(f"{spec.env_prefix}_API_URL is not configured.")
    if not token:
        raise RuntimeError(f"{token_env} is not configured.")
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    text = response.text.strip()
    if "json" in content_type or text.startswith("{") or text.startswith("["):
        payload = response.json()
        if isinstance(payload, dict):
            payload = payload.get("data") or payload.get("results") or payload.get("items") or payload
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            raise ValueError(f"{spec.label} API did not return rows.")
        return pd.json_normalize(payload)
    return pd.read_csv(StringIO(response.text))


def load_connector_table(spec: ConnectorSpec) -> pd.DataFrame:
    mode = _mode(spec)
    if mode == "file":
        path = _env(f"{spec.env_prefix}_FILE_PATH")
        if not path:
            raise RuntimeError(f"{spec.env_prefix}_FILE_PATH is not configured.")
        return read_table(Path(path).expanduser())
    if mode == "http":
        return _load_http_table(spec)
    raise RuntimeError(f"{spec.label} connector is not configured.")


def validate_standard_columns(df: pd.DataFrame, source: str) -> None:
    missing = [c for c in STANDARD_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{source} is missing standardized column(s): {', '.join(missing)}.")


def load_live_inputs(week_start: pd.Timestamp, now: pd.Timestamp | None = None) -> LiveInputs:
    statuses = connector_statuses()
    not_ready = [s for s in statuses if not s.ready]
    if not_ready:
        raise RuntimeError("Connector(s) not ready: " + ", ".join(s.source for s in not_ready) + ".")

    payroll_raw = load_connector_table(PAYROLL_SPEC)
    schedule_raw = load_connector_table(SCHEDULE_SPEC)
    validate_standard_columns(payroll_raw, PAYROLL_SPEC.label)
    validate_standard_columns(schedule_raw, SCHEDULE_SPEC.label)

    now = now or pd.Timestamp.now()
    actual_detail = normalize_actual_rows(payroll_raw, STANDARD_MAPPING, week_start=week_start)
    actuals = prepare_actuals(payroll_raw, STANDARD_MAPPING, week_start=week_start)
    schedule_detail = normalize_schedule_rows(schedule_raw, STANDARD_MAPPING, now=now, week_start=week_start, actual_detail=actual_detail)
    schedule = prepare_schedule(schedule_raw, STANDARD_MAPPING, now=now, week_start=week_start, actual_detail=actual_detail)
    combined = combine_actuals_schedule(actuals, schedule)

    summary = crossing_summary(project_threshold_crossings(actuals, schedule_detail, thresholds=(30, 40, 50, 60)))
    if not summary.empty:
        combined = combined.merge(summary, on="employee_id", how="left")

    roster_path = _env("ROSTER_FILE_PATH")
    if roster_path and Path(roster_path).expanduser().exists():
        combined = enrich_with_roster(combined, normalize_roster(read_table(Path(roster_path).expanduser())))
    else:
        combined = enrich_with_roster(combined, pd.DataFrame())

    return LiveInputs(actuals, actual_detail, schedule, schedule_detail, combined, statuses)
