from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


class AmazonPortalPayloadError(ValueError):
    """Raised when a captured DSP Scheduling payload is not in the expected shape."""


def load_json_payload(file_or_path_or_text: Any) -> dict:
    """Load a JSON object from a path, Streamlit upload, bytes, or JSON string.

    This intentionally does not perform authentication or network requests. Live access
    should use an approved/local authenticated integration and must keep credentials,
    cookies, and tokens out of source control.
    """
    if isinstance(file_or_path_or_text, dict):
        return file_or_path_or_text

    if isinstance(file_or_path_or_text, (bytes, bytearray)):
        return json.loads(bytes(file_or_path_or_text).decode("utf-8"))

    if hasattr(file_or_path_or_text, "read"):
        raw = file_or_path_or_text.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    value = str(file_or_path_or_text)
    path = Path(value)
    if path.exists() and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))

    return json.loads(value)


def _work_summary_root(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the DA-id -> summary mapping from known response wrappers."""
    if "daWorkSummaryAndEligibility" in payload:
        root = payload.get("daWorkSummaryAndEligibility")
    else:
        root = payload.get("data", {}).get("daWorkSummaryAndEligibility")

    if not isinstance(root, Mapping):
        raise AmazonPortalPayloadError(
            "Expected data.daWorkSummaryAndEligibility in the Amazon Scheduling response."
        )
    return root


def _mins_to_hours(value: Any) -> float:
    try:
        mins = float(value or 0)
    except (TypeError, ValueError):
        mins = 0.0
    return round(max(mins, 0.0) / 60.0, 2)


def parse_work_summary_payload(
    payload: Mapping[str, Any],
    name_map: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Flatten Amazon DSP Scheduling working-hour summary JSON.

    The captured response is keyed by Amazon Delivery Associate ID. This parser keeps
    Amazon's hour concepts separate instead of guessing that one field is a future
    schedule. In particular, `daScheduledLast7DaysMins` is retained as its own rolling
    scheduling field and is NOT treated as remaining future hours.
    """
    root = _work_summary_root(payload)
    names = name_map or {}
    rows: list[dict[str, Any]] = []

    for employee_id, item in root.items():
        item = item or {}
        work = item.get("workSummary") or {}
        eligibility = item.get("daEligibility") or {}

        rows.append(
            {
                "employee_id": str(employee_id),
                "name": str(names.get(str(employee_id), str(employee_id))),
                "actual_work_week_hours": _mins_to_hours(work.get("daActualWorkWeekMins")),
                "actual_work_day_hours": _mins_to_hours(work.get("daActualWorkDayMins")),
                "scheduled_day_hours": _mins_to_hours(work.get("daScheduledDayMins")),
                "scheduled_week_hours": _mins_to_hours(work.get("daScheduledWeekMins")),
                "scheduled_last_7_days_hours": _mins_to_hours(
                    work.get("daScheduledLast7DaysMins")
                ),
                "daily_leap_threshold_breached": bool(
                    work.get("isDailyLeapThresholdBreached", False)
                ),
                "nursery_training_level": eligibility.get("nurseryTrainingLevel"),
                "qualifications": item.get("daQualifications"),
            }
        )

    columns = [
        "employee_id",
        "name",
        "actual_work_week_hours",
        "actual_work_day_hours",
        "scheduled_day_hours",
        "scheduled_week_hours",
        "scheduled_last_7_days_hours",
        "daily_leap_threshold_breached",
        "nursery_training_level",
        "qualifications",
    ]
    return pd.DataFrame(rows, columns=columns)


def portal_snapshot_to_actuals(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Convert the portal work-summary snapshot into Hours Guard actuals.

    Only fields that are clearly actual worked time are promoted to the alert engine.
    Future scheduled hours must come from the weekly schedule/roster source so the app
    does not double-count or misclassify rolling historical schedule minutes.
    """
    if snapshot is None or snapshot.empty:
        return pd.DataFrame(
            columns=[
                "employee_id",
                "name",
                "actual_hours",
                "max_daily_hours",
                "days_worked",
                "station",
                "manager",
                "phone",
                "email",
                "dot_regulated",
                "missing_punch",
            ]
        )

    out = pd.DataFrame()
    out["employee_id"] = snapshot["employee_id"].astype(str)
    out["name"] = snapshot["name"].astype(str)
    out["actual_hours"] = pd.to_numeric(
        snapshot["actual_work_week_hours"], errors="coerce"
    ).fillna(0)
    out["max_daily_hours"] = pd.to_numeric(
        snapshot["actual_work_day_hours"], errors="coerce"
    ).fillna(0)
    out["days_worked"] = 0
    out["station"] = ""
    out["manager"] = ""
    out["phone"] = ""
    out["email"] = ""
    out["dot_regulated"] = False
    out["missing_punch"] = False
    return out


def parse_work_summary_file(
    file_or_path_or_text: Any,
    name_map: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    return parse_work_summary_payload(load_json_payload(file_or_path_or_text), name_map=name_map)
