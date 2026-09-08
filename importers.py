from __future__ import annotations

from typing import Optional

import pandas as pd


NAME_CANDIDATES = ["employee", "employee name", "associate", "associate name", "driver", "name"]
ID_CANDIDATES = ["employee id", "associate id", "driver id", "id"]
DATE_CANDIDATES = ["date", "work date", "shift date", "day"]
HOURS_CANDIDATES = ["hours", "worked hours", "total hours", "regular hours", "duration"]
START_CANDIDATES = ["start", "start time", "clock in", "clock-in", "punch in", "day in"]
END_CANDIDATES = ["end", "end time", "clock out", "clock-out", "punch out", "day out"]
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


def _boolean_series(df: pd.DataFrame, col: str | None) -> pd.Series:
    if not col:
        return pd.Series(False, index=df.index)
    vals = df[col].astype(str).str.strip().str.lower()
    return vals.isin(["1", "true", "yes", "y", "dot", "regulated"])


def _combine_date_and_time(date_series: pd.Series, time_series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(date_series, errors="coerce").dt.strftime("%Y-%m-%d")
    raw = time_series.astype(str).str.strip()
    direct = pd.to_datetime(time_series, errors="coerce")
    has_meaningful_date = direct.dt.year.fillna(1900) > 1971
    combined = pd.to_datetime(dates + " " + raw, errors="coerce")
    return direct.where(has_meaningful_date, combined)


def _timestamps(df: pd.DataFrame, date_col: str | None, start_col: str | None, end_col: str | None) -> tuple[pd.Series, pd.Series]:
    blank = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    if not start_col and not end_col:
        return blank, blank.copy()
    if date_col:
        start = _combine_date_and_time(df[date_col], df[start_col]) if start_col else blank
        end = _combine_date_and_time(df[date_col], df[end_col]) if end_col else blank.copy()
    else:
        start = pd.to_datetime(df[start_col], errors="coerce") if start_col else blank
        end = pd.to_datetime(df[end_col], errors="coerce") if end_col else blank.copy()
    if start_col and end_col:
        overnight = end.notna() & start.notna() & (end < start)
        end.loc[overnight] = end.loc[overnight] + pd.Timedelta(days=1)
    return start, end


def compute_hours(df: pd.DataFrame, hours_col: str | None, start_col: str | None, end_col: str | None, date_col: str | None = None) -> pd.Series:
    if hours_col:
        return pd.to_numeric(df[hours_col], errors="coerce").fillna(0).clip(lower=0)
    if start_col and end_col:
        start, end = _timestamps(df, date_col, start_col, end_col)
        hours = (end - start).dt.total_seconds() / 3600
        return hours.fillna(0).clip(lower=0)
    raise ValueError("Map either an Hours column or both Start and End columns.")


def normalize_actual_rows(df: pd.DataFrame, mapping: dict, week_start: pd.Timestamp | None = None) -> pd.DataFrame:
    df = normalize_columns(df)
    name_col = mapping.get("name")
    if not name_col:
        raise ValueError("Employee/associate name is required.")

    hours = compute_hours(df, mapping.get("hours"), mapping.get("start"), mapping.get("end"), mapping.get("date"))
    work = pd.DataFrame({"name": df[name_col].astype(str).str.strip(), "hours": hours})
    work["employee_id"] = df[mapping["id"]].astype(str).str.strip() if mapping.get("id") else work["name"].str.lower().str.replace(r"\W+", "_", regex=True)
    work["station"] = df[mapping["station"]].astype(str).str.strip() if mapping.get("station") else ""
    work["manager"] = df[mapping["manager"]].astype(str).str.strip() if mapping.get("manager") else ""
    work["phone"] = df[mapping["phone"]].astype(str).str.strip() if mapping.get("phone") else ""
    work["email"] = df[mapping["email"]].astype(str).str.strip() if mapping.get("email") else ""
    work["dot_regulated"] = _boolean_series(df, mapping.get("dot"))

    work["date"] = pd.to_datetime(df[mapping["date"]], errors="coerce").dt.normalize() if mapping.get("date") else pd.NaT
    start_ts, end_ts = _timestamps(df, mapping.get("date"), mapping.get("start"), mapping.get("end"))
    work["start_ts"] = start_ts
    work["end_ts"] = end_ts

    if mapping.get("hours"):
        raw_hours = pd.to_numeric(df[mapping["hours"]], errors="coerce")
        work["missing_punch"] = raw_hours.isna()
    elif mapping.get("start") and mapping.get("end"):
        work["missing_punch"] = start_ts.isna() | end_ts.isna()
    else:
        work["missing_punch"] = True

    work = work[(work["name"] != "") & (work["name"].str.lower() != "nan")]
    if week_start is not None and work["date"].notna().any():
        ws = pd.Timestamp(week_start).normalize()
        week_end = ws + pd.Timedelta(days=6)
        work = work[(work["date"] >= ws) & (work["date"] <= week_end)]
    return work.reset_index(drop=True)


def prepare_actuals(df: pd.DataFrame, mapping: dict, week_start: pd.Timestamp | None = None) -> pd.DataFrame:
    work = normalize_actual_rows(df, mapping, week_start=week_start)
    if work.empty:
        return pd.DataFrame(columns=["employee_id","name","actual_hours","max_daily_hours","days_worked","last_work_date","station","manager","phone","email","dot_regulated","missing_punch"])

    if work["date"].notna().any():
        daily = work.groupby(["employee_id", "name", "date"], as_index=False)["hours"].sum()
        max_daily = daily.groupby(["employee_id", "name"], as_index=False)["hours"].max().rename(columns={"hours": "max_daily_hours"})
        days = daily.groupby(["employee_id", "name"], as_index=False)["date"].nunique().rename(columns={"date": "days_worked"})
        last_date = daily.groupby(["employee_id", "name"], as_index=False)["date"].max().rename(columns={"date": "last_work_date"})
    else:
        max_daily = work.groupby(["employee_id", "name"], as_index=False)["hours"].max().rename(columns={"hours": "max_daily_hours"})
        days = work.groupby(["employee_id", "name"], as_index=False).size().rename(columns={"size": "days_worked"})
        last_date = work[["employee_id", "name"]].drop_duplicates().assign(last_work_date=pd.NaT)

    agg = work.groupby(["employee_id", "name"], as_index=False).agg(
        actual_hours=("hours", "sum"),
        station=("station", "last"),
        manager=("manager", "last"),
        phone=("phone", "last"),
        email=("email", "last"),
        dot_regulated=("dot_regulated", "max"),
        missing_punch=("missing_punch", "max"),
    )
    return agg.merge(max_daily, on=["employee_id", "name"], how="left").merge(days, on=["employee_id", "name"], how="left").merge(last_date, on=["employee_id", "name"], how="left")


def normalize_schedule_rows(df: pd.DataFrame, mapping: dict, now: pd.Timestamp | None = None, week_start: pd.Timestamp | None = None, actual_detail: pd.DataFrame | None = None) -> pd.DataFrame:
    df = normalize_columns(df)
    name_col = mapping.get("name")
    if not name_col:
        raise ValueError("Employee/associate name is required.")

    hours = compute_hours(df, mapping.get("hours"), mapping.get("start"), mapping.get("end"), mapping.get("date"))
    work = pd.DataFrame({"name": df[name_col].astype(str).str.strip(), "hours": hours})
    work["employee_id"] = df[mapping["id"]].astype(str).str.strip() if mapping.get("id") else work["name"].str.lower().str.replace(r"\W+", "_", regex=True)
    work["station"] = df[mapping["station"]].astype(str).str.strip() if mapping.get("station") else ""
    work["manager"] = df[mapping["manager"]].astype(str).str.strip() if mapping.get("manager") else ""
    work["phone"] = df[mapping["phone"]].astype(str).str.strip() if mapping.get("phone") else ""
    work["email"] = df[mapping["email"]].astype(str).str.strip() if mapping.get("email") else ""
    work["dot_regulated"] = _boolean_series(df, mapping.get("dot"))
    work["date"] = pd.to_datetime(df[mapping["date"]], errors="coerce").dt.normalize() if mapping.get("date") else pd.NaT
    start_ts, end_ts = _timestamps(df, mapping.get("date"), mapping.get("start"), mapping.get("end"))
    work["start_ts"] = start_ts
    work["end_ts"] = end_ts
    work = work[(work["name"] != "") & (work["name"].str.lower() != "nan")]

    if week_start is not None and work["date"].notna().any():
        ws = pd.Timestamp(week_start).normalize()
        week_end = ws + pd.Timedelta(days=6)
        work = work[(work["date"] >= ws) & (work["date"] <= week_end)]

    if now is not None and work["date"].notna().any():
        now = pd.Timestamp(now)
        today = now.normalize()
        future_date = work["date"] > today
        today_mask = work["date"] == today
        if work["start_ts"].notna().any():
            today_future = today_mask & work["start_ts"].notna() & (work["start_ts"] > now)
        else:
            today_future = today_mask
        if actual_detail is not None and not actual_detail.empty and "date" in actual_detail.columns:
            worked_today_ids = set(actual_detail.loc[actual_detail["date"] == today, "employee_id"].astype(str))
            if worked_today_ids:
                today_future = today_future & ~work["employee_id"].astype(str).isin(worked_today_ids)
        work = work[future_date | today_future]

    return work.reset_index(drop=True)


def prepare_schedule(df: pd.DataFrame, mapping: dict, now: pd.Timestamp | None = None, week_start: pd.Timestamp | None = None, actual_detail: pd.DataFrame | None = None) -> pd.DataFrame:
    work = normalize_schedule_rows(df, mapping, now=now, week_start=week_start, actual_detail=actual_detail)
    if work.empty:
        return pd.DataFrame(columns=["employee_id","name","scheduled_remaining_hours","scheduled_days","next_shift_hours","next_shift_date","max_scheduled_shift_hours","station","manager","phone","email","dot_regulated"])

    sort_cols = ["employee_id"] + (["date"] if work["date"].notna().any() else []) + (["start_ts"] if work["start_ts"].notna().any() else [])
    work = work.sort_values(sort_cols)
    first = work.groupby(["employee_id", "name"], as_index=False).first()
    next_shift = first[["employee_id", "name", "hours", "date"]].rename(columns={"hours": "next_shift_hours", "date": "next_shift_date"})

    if work["date"].notna().any():
        scheduled_days = work.groupby(["employee_id", "name"], as_index=False)["date"].nunique().rename(columns={"date": "scheduled_days"})
    else:
        scheduled_days = work.groupby(["employee_id", "name"], as_index=False).size().rename(columns={"size": "scheduled_days"})

    max_shift = work.groupby(["employee_id", "name"], as_index=False)["hours"].max().rename(columns={"hours": "max_scheduled_shift_hours"})
    agg = work.groupby(["employee_id", "name"], as_index=False).agg(
        scheduled_remaining_hours=("hours", "sum"),
        station=("station", "last"),
        manager=("manager", "last"),
        phone=("phone", "last"),
        email=("email", "last"),
        dot_regulated=("dot_regulated", "max"),
    )
    return agg.merge(next_shift, on=["employee_id", "name"], how="left").merge(scheduled_days, on=["employee_id", "name"], how="left").merge(max_shift, on=["employee_id", "name"], how="left")


def combine_actuals_schedule(actuals: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    if actuals is None or actuals.empty:
        actuals = pd.DataFrame(columns=["employee_id", "name", "actual_hours", "max_daily_hours", "days_worked", "last_work_date", "station", "manager", "phone", "email", "dot_regulated", "missing_punch"])
    if schedule is None or schedule.empty:
        schedule = pd.DataFrame(columns=["employee_id", "name", "scheduled_remaining_hours", "scheduled_days", "next_shift_hours", "next_shift_date", "max_scheduled_shift_hours", "station", "manager", "phone", "email", "dot_regulated"])

    merged = actuals.merge(schedule, on=["employee_id", "name"], how="outer", suffixes=("_a", "_s"))
    numeric = ["actual_hours", "max_daily_hours", "days_worked", "scheduled_remaining_hours", "scheduled_days", "next_shift_hours", "max_scheduled_shift_hours"]
    for c in numeric:
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
    merged["projected_days"] = (merged["days_worked"] + merged["scheduled_days"]).clip(upper=7)
    if "next_shift_date" not in merged:
        merged["next_shift_date"] = pd.NaT
    if "last_work_date" not in merged:
        merged["last_work_date"] = pd.NaT
    keep = [
        "employee_id","name","station","manager","phone","email",
        "actual_hours","scheduled_remaining_hours","projected_hours",
        "days_worked","scheduled_days","projected_days",
        "next_shift_hours","next_shift_date","max_daily_hours","max_scheduled_shift_hours",
        "last_work_date","dot_regulated","missing_punch"
    ]
    return merged[keep].sort_values(["projected_hours", "name"], ascending=[False, True]).reset_index(drop=True)
