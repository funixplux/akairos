from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable

import pandas as pd


@dataclass
class ThresholdCrossing:
    employee_id: str
    name: str
    threshold: float
    state: str  # already_reached | scheduled_crossing
    crossing_date: str = ""
    shift_hours: float = 0.0
    projected_after_shift: float = 0.0

    def to_dict(self):
        return asdict(self)


def project_threshold_crossings(actuals: pd.DataFrame, schedule_detail: pd.DataFrame, thresholds: Iterable[float] = (30.0, 40.0, 50.0, 60.0)) -> pd.DataFrame:
    thresholds = sorted({float(x) for x in thresholds})
    if actuals is None or actuals.empty:
        actuals = pd.DataFrame(columns=["employee_id", "name", "actual_hours"])
    if schedule_detail is None or schedule_detail.empty:
        schedule_detail = pd.DataFrame(columns=["employee_id", "name", "date", "hours"])

    records: list[dict] = []
    names = {}
    for _, r in actuals.iterrows():
        names[str(r.get("employee_id", ""))] = str(r.get("name", ""))
    for _, r in schedule_detail.iterrows():
        names.setdefault(str(r.get("employee_id", "")), str(r.get("name", "")))

    actual_map = {str(r.get("employee_id", "")): float(r.get("actual_hours", 0) or 0) for _, r in actuals.iterrows()}
    grouped = {str(k): v.copy() for k, v in schedule_detail.groupby("employee_id", dropna=False)} if not schedule_detail.empty else {}

    for employee_id, name in names.items():
        actual = actual_map.get(employee_id, 0.0)
        employee_shifts = grouped.get(employee_id, pd.DataFrame(columns=schedule_detail.columns))
        if not employee_shifts.empty:
            sort_cols = [c for c in ["date", "start_ts"] if c in employee_shifts.columns]
            if sort_cols:
                employee_shifts = employee_shifts.sort_values(sort_cols)

        for threshold in thresholds:
            if actual >= threshold:
                records.append(ThresholdCrossing(employee_id, name, threshold, "already_reached", projected_after_shift=actual).to_dict())
                continue

            running = actual
            for _, shift in employee_shifts.iterrows():
                h = float(shift.get("hours", 0) or 0)
                after = running + h
                if running < threshold <= after:
                    d = shift.get("date")
                    date_text = "" if pd.isna(d) else pd.Timestamp(d).date().isoformat()
                    records.append(ThresholdCrossing(employee_id, name, threshold, "scheduled_crossing", date_text, h, round(after, 2)).to_dict())
                    break
                running = after

    return pd.DataFrame(records)


def crossing_summary(crossings: pd.DataFrame) -> pd.DataFrame:
    if crossings is None or crossings.empty:
        return pd.DataFrame(columns=["employee_id"])
    rows = []
    for employee_id, group in crossings.groupby("employee_id"):
        out = {"employee_id": employee_id}
        for _, r in group.iterrows():
            t = int(float(r["threshold"]))
            out[f"cross_{t}_state"] = r.get("state", "")
            out[f"cross_{t}_date"] = r.get("crossing_date", "")
            out[f"cross_{t}_after"] = float(r.get("projected_after_shift", 0) or 0)
        rows.append(out)
    return pd.DataFrame(rows)
