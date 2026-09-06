from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd


NAME_CANDIDATES = ["employee", "employee name", "associate", "associate name", "driver", "name"]
ID_CANDIDATES = ["employee id", "associate id", "driver id", "id"]
DATE_CANDIDATES = ["date", "work date", "shift date", "day"]
HOURS_CANDIDATES = ["hours", "worked hours", "total hours", "regular hours", "duration"]
START_CANDIDATES = ["start", "start time", "clock in", "clock-in", "punch in"]
END_CANDIDATES = ["end", "end time", "clock out", "clock-out", "punch out"]
STATION_CANDIDATES = ["station", "site", "location", "business unit", "department"]
MANAGER_CANDIDATES = ["manager", "supervisor"]
DOT_CANDIDATES = ["dot", "dot regulated", "regulated"]
PHONE_CANDIDATES = ["phone", "mobile", "cell"]
EMAIL_CANDIDATES = ["email", "email address"]


def read_table(file_or_path) -> pd.DataFrame:
    name = getattr(file_or_path, "name", str(file_or_path)).lower()
    if name.endswith(".csv"):
        return pd.read_csv(file_or_path)
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(file_or_path)
    raise ValueError("Use CSV, XLSX, or XLS files.")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def guess_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    lookup = {str(c).strip().lower(): c for c in df.columns}
    for c in candidates:
        if c in lookup:
            return lookup[c]
    for col in df.columns:
        low = str(col).strip().lower()
        for c in candidates:
            if c in low:
                return col
    return None


def compute_hours(df: pd.DataFrame, hours_col: str | None, start_col: str | None, end_col: str | None) -> pd.Series:
    if hours_col:
        return pd.to_numeric(df[hours_col], errors="coerce").fillna(0).clip(lower=0)
    if start_col and end_col:
        start = pd.to_datetime(df[start_col], errors="coerce")
        end = pd.to_datetime(df[end_col], errors="coerce")
        hours = (end - start).dt.total_seconds() / 3600
        hours = hours.where(hours >= 0, hours + 24)
        return hours.fillna(0).clip(lower=0)
    raise ValueError("Map either an Hours column or both Start and End columns.")


def prepare_actuals(df: pd.DataFrame, mapping: dict, week_start: pd.Timestamp | None = None) -> pd.DataFrame:
    df = normalize_columns(df)
    name_col = mapping.get("name")
    if not name_col:
        raise ValueError("Employee/associate name is required.")
    hours = compute_hours(df, mapping.get("hours"), mapping.get("start"), mapping.get("end"))
    work = pd.DataFrame({"name": df[name_col].astype(str).str.strip(), "hours": hours})
    if mapping.get("id"):
        work["employee_id"] = df[mapping["id"]].astype(str).str.strip()
    else:
        work["employee_id"] = work["name"].str.lower().str.replace(r"\W+", "_", regex=True)
    work["station"] = df[mapping["station"]].astype(str).str.strip() if mapping.get("station") else ""
    work["manager"] = df[mapping["manager"]].astype(str).str.strip() if mapping.get("manager") else ""
    work["phone"] = df[mapping["phone"]].astype(str).str.strip() if mapping.get("phone") else ""
    work["email"] = df[mapping["email"]].astype(str).str.strip() if mapping.get("email") else ""
    work["dot_regulated"] = False
    if mapping.get("dot"):
        vals = df[mapping["dot"]].astype(str).str.strip().str.lower()
        work["dot_regulated"] = vals.isin(["1", "true", "yes", "y", "dot", "regulated"])
    work["missing_punch"] = False
    if mapping.get("start") or mapping.get("end"):
        start_missing = df[mapping["start"]].isna() if mapping.get("start") else False
        end_missing = df[mapping["end"]].isna() if mapping.get("end") else False
        work["missing_punch"] = start_missing | end_missing
    if mapping.get("date"):
        work["date"] = pd.to_datetime(df[mapping["date"]], errors="coerce").dt.normalize()
        if week_start is not None:
            week_end = week_start + pd.Timedelta(days=6)
            work = work[(work["date"] >= week_start) & (work["date"] <= week_end)]
    else:
        work["date"] = pd.NaT
    if work["date"].notna().any():
        daily = work.groupby(["employee_id", "name", "date"], as_index=False)["hours"].sum()
        max_daily = daily.groupby(["employee_id", "name"], as_index=False)["hours"].max().rename(columns={"hours": "max_daily_hours"})
        days = daily.groupby(["employee_id", "name"], as_index=False)["date"].nunique().rename(columns={"date": "days_worked"})
    else:
        max_daily = work.groupby(["employee_id", "name"], as_index=False)["hours"].max().rename(columns={"hours": "max_daily_hours"})
        days = work.groupby(["employee_id", "name"], as_index=False).size().rename(columns={"size": "days_worked"})
    agg = work.groupby(["employee_id", "name"], as_index=False).agg(actual_hours=("hours", "sum"),station=("station", "last"),manager=("manager", "last"),phone=("phone", "last"),email=("email", "last"),dot_regulated=("dot_regulated", "max"),missing_punch=("missing_punch", "max"))
    return agg.merge(max_daily, on=["employee_id", "name"], how="left").merge(days, on=["employee_id", "name"], how="left")


def prepare_schedule(df: pd.DataFrame, mapping: dict, now: pd.Timestamp | None = None, week_start: pd.Timestamp | None = None) -> pd.DataFrame:
    df = normalize_columns(df)
    name_col = mapping.get("name")
    if not name_col:
        raise ValueError("Employee/associate name is required.")
    hours = compute_hours(df, mapping.get("hours"), mapping.get("start"), mapping.get("end"))
    work = pd.DataFrame({"name": df[name_col].astype(str).str.strip(), "hours": hours})
    work["employee_id"] = df[mapping["id"]].astype(str).str.strip() if mapping.get("id") else work["name"].str.lower().str.replace(r"\W+", "_", regex=True)
    work["station"] = df[mapping["station"]].astype(str).str.strip() if mapping.get("station") else ""
    work["manager"] = df[mapping["manager"]].astype(str).str.strip() if mapping.get("manager") else ""
    work["phone"] = df[mapping["phone"]].astype(str).str.strip() if mapping.get("phone") else ""
    work["email"] = df[mapping["email"]].astype(str).str.strip() if mapping.get("email") else ""
    work["dot_regulated"] = False
    if mapping.get("dot"):
        vals = df[mapping["dot"]].astype(str).str.strip().str.lower()
        work["dot_regulated"] = vals.isin(["1", "true", "yes", "y", "dot", "regulated"])
    work["date"] = pd.to_datetime(df[mapping["date"]], errors="coerce").dt.normalize() if mapping.get("date") else pd.NaT
    if week_start is not None and work["date"].notna().any():
        week_end = week_start + pd.Timedelta(days=6)
        work = work[(work["date"] >= week_start) & (work["date"] <= week_end)]
    if now is not None and work["date"].notna().any():
        work = work[work["date"] >= now.normalize()]
    if work.empty:
        return pd.DataFrame(columns=["employee_id","name","scheduled_remaining_hours","next_shift_hours","station","manager","phone","email","dot_regulated"])
    if work["date"].notna().any():
        work = work.sort_values(["employee_id", "date"])
        next_shift = work.groupby(["employee_id", "name"], as_index=False).first()[["employee_id", "name", "hours"]].rename(columns={"hours": "next_shift_hours"})
    else:
        next_shift = work.groupby(["employee_id", "name"], as_index=False)["hours"].first().rename(columns={"hours": "next_shift_hours"})
    agg = work.groupby(["employee_id", "name"], as_index=False).agg(scheduled_remaining_hours=("hours", "sum"),station=("station", "last"),manager=("manager", "last"),phone=("phone", "last"),email=("email", "last"),dot_regulated=("dot_regulated", "max"))
    return agg.merge(next_shift, on=["employee_id", "name"], how="left")


def combine_actuals_schedule(actuals: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    if actuals is None or actuals.empty:
        actuals = pd.DataFrame(columns=["employee_id", "name", "actual_hours", "max_daily_hours", "days_worked", "station", "manager", "phone", "email", "dot_regulated", "missing_punch"])
    if schedule is None or schedule.empty:
        schedule = pd.DataFrame(columns=["employee_id", "name", "scheduled_remaining_hours", "next_shift_hours", "station", "manager", "phone", "email", "dot_regulated"])
    merged = actuals.merge(schedule, on=["employee_id", "name"], how="outer", suffixes=("_a", "_s"))
    for c in ["actual_hours", "max_daily_hours", "days_worked", "scheduled_remaining_hours", "next_shift_hours"]:
        if c not in merged:
            merged[c] = 0
        merged[c] = pd.to_numeric(merged[c], errors="coerce").fillna(0)
    for c in ["station", "manager", "phone", "email"]:
        a, s = f"{c}_a", f"{c}_s"
        merged[c] = merged.get(a, pd.Series(index=merged.index, dtype=str)).fillna("")
        if s in merged:
            merged[c] = merged[c].where(merged[c].astype(str).str.len() > 0, merged[s].fillna(""))
    da = merged.get("dot_regulated_a", pd.Series(False, index=merged.index)).fillna(False).astype(bool)
    ds = merged.get("dot_regulated_s", pd.Series(False, index=merged.index)).fillna(False).astype(bool)
    merged["dot_regulated"] = da | ds
    merged["missing_punch"] = merged.get("missing_punch", pd.Series(False, index=merged.index)).fillna(False).astype(bool)
    merged["projected_hours"] = merged["actual_hours"] + merged["scheduled_remaining_hours"]
    keep = ["employee_id","name","station","manager","phone","email","actual_hours","scheduled_remaining_hours","projected_hours","days_worked","next_shift_hours","max_daily_hours","dot_regulated","missing_punch"]
    return merged[keep].sort_values(["projected_hours", "name"], ascending=[False, True]).reset_index(drop=True)
