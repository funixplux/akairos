from __future__ import annotations

import pandas as pd


ROSTER_COLUMNS = [
    "employee_id",
    "name",
    "station",
    "manager",
    "manager_email",
    "manager_phone",
    "dot_regulated",
    "phone",
    "email",
    "active",
]


def normalize_roster(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=ROSTER_COLUMNS)
    out = df.copy()
    out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
    rename = {
        "employee": "name",
        "associate": "name",
        "associate_name": "name",
        "driver": "name",
        "id": "employee_id",
        "associate_id": "employee_id",
        "driver_id": "employee_id",
        "supervisor": "manager",
        "mobile": "phone",
        "cell": "phone",
        "manager_mobile": "manager_phone",
    }
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    if "name" not in out.columns:
        raise ValueError("Roster requires a name column.")
    if "employee_id" not in out.columns:
        out["employee_id"] = out["name"].astype(str).str.lower().str.replace(r"\W+", "_", regex=True)
    for c in ROSTER_COLUMNS:
        if c not in out.columns:
            out[c] = ""
    vals = out["dot_regulated"].astype(str).str.strip().str.lower()
    out["dot_regulated"] = vals.isin(["1", "true", "yes", "y", "dot", "regulated"])
    active = out["active"].astype(str).str.strip().str.lower()
    out["active"] = ~active.isin(["0", "false", "no", "n", "inactive", "terminated"])
    for c in ["employee_id", "name", "station", "manager", "manager_email", "manager_phone", "phone", "email"]:
        out[c] = out[c].fillna("").astype(str).str.strip()
    return out[ROSTER_COLUMNS].drop_duplicates("employee_id", keep="last").reset_index(drop=True)


def enrich_with_roster(combined: pd.DataFrame, roster: pd.DataFrame) -> pd.DataFrame:
    if combined is None or combined.empty:
        return combined
    if roster is None or roster.empty:
        out = combined.copy()
        for c in ["manager_email", "manager_phone", "active"]:
            if c not in out.columns:
                out[c] = True if c == "active" else ""
        return out

    r = normalize_roster(roster)
    out = combined.merge(r, on="employee_id", how="left", suffixes=("", "_roster"))
    for c in ["name", "station", "manager", "phone", "email"]:
        rc = f"{c}_roster"
        if rc in out.columns:
            out[c] = out[c].where(out[c].fillna("").astype(str).str.len() > 0, out[rc].fillna(""))
            out = out.drop(columns=[rc])
    if "dot_regulated_roster" in out.columns:
        out["dot_regulated"] = out["dot_regulated"].fillna(False).astype(bool) | out["dot_regulated_roster"].fillna(False).astype(bool)
        out = out.drop(columns=["dot_regulated_roster"])
    out["manager_email"] = out.get("manager_email", "").fillna("")
    out["manager_phone"] = out.get("manager_phone", "").fillna("")
    out["active"] = out.get("active", True).fillna(True).astype(bool)
    return out[out["active"]].reset_index(drop=True)
