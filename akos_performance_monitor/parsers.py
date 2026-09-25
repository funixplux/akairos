"""Report-type parsers for Cortex AKOS DVA5 performance files."""
from __future__ import annotations

from pathlib import Path

from .catalog import ClassifiedReport, ReportKind
from .parsers_common import (
    DRIVER_ALIASES,
    find_driver_table,
    find_header_table,
    get_cell,
    norm,
    value_float,
)


# --- DVIC PreTrip -----------------------------------------------------------

DVIC_DURATION_ALIASES = (
    "DVIC Duration",
    "PreTrip Duration",
    "Pre-Trip Duration",
    "Pre Trip Duration",
    "Inspection Duration",
    "Duration (Seconds)",
    "Duration Seconds",
    "Duration",
    "Seconds",
    "DVIC Time",
    "PreTrip Time",
)

DVIC_FLEET_ALIASES = (
    "Fleet Type",
    "Vehicle Type",
    "Asset Type",
    "Van Type",
    "DOT Status",
    "Regulation",
    "Vehicle Class",
)

DVIC_DATE_ALIASES = (
    "Inspection Date",
    "Date",
    "Shift Date",
    "Service Date",
    "PreTrip Date",
    "DVIC Date",
)

DOT_FLEET_TOKENS = ("dot", "cdv", "box truck", "boxtruck", "straight truck", "stepvan-dot")


def _is_dot_fleet(raw) -> bool:
    s = str(raw or "").casefold()
    if not s.strip():
        return False
    if "nondot" in s.replace(" ", "") or "non-dot" in s or "non dot" in s:
        return False
    return any(tok in s for tok in DOT_FLEET_TOKENS)


def _dvic_alert_max_seconds(dvic_cfg: dict) -> float:
    """AKAIROS review cutover: 6 minutes for all fleets (not Amazon 90s/300s filename standards)."""
    if "alert_max_seconds" in dvic_cfg and dvic_cfg["alert_max_seconds"] is not None:
        return float(dvic_cfg["alert_max_seconds"])
    if "alert_max_minutes" in dvic_cfg and dvic_cfg["alert_max_minutes"] is not None:
        return float(dvic_cfg["alert_max_minutes"]) * 60.0
    return 360.0


def parse_dvic(path: Path, config: dict) -> dict:
    """Flag drivers whose DVIC PreTrip duration exceeds the AKAIROS 6-minute (360s) alert cutover."""
    dvic_cfg = config.get("dvic", {})
    threshold = _dvic_alert_max_seconds(dvic_cfg)
    aliases = config.get("aliases", {})
    driver_aliases = list(aliases.get("driver", DRIVER_ALIASES))

    sheet, records = find_driver_table(path, {"driver": driver_aliases})
    result = {
        "kind": ReportKind.DVIC_PRETRIP.value,
        "file": path.name,
        "sheet": sheet,
        "rows": len(records),
        "below_standard": [],
        "warnings": [],
        "status": "live",
        "thresholds": {
            "alert_max_seconds": threshold,
            "alert_max_minutes": threshold / 60.0,
        },
    }
    if not records:
        result["warnings"].append(
            "DVIC PreTrip: no driver-level rows found; named-driver duration alerts unavailable."
        )
        return result

    duration_aliases = list(dvic_cfg.get("duration_columns", DVIC_DURATION_ALIASES))
    fleet_aliases = list(dvic_cfg.get("fleet_columns", DVIC_FLEET_ALIASES))
    date_aliases = list(dvic_cfg.get("date_columns", DVIC_DATE_ALIASES))

    found_duration = False
    seen = set()
    for record in records:
        name = str(get_cell(record, driver_aliases) or "").strip()
        key = norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        raw_dur = get_cell(record, duration_aliases)
        if raw_dur is None or str(raw_dur).strip() == "":
            continue
        try:
            seconds = value_float(raw_dur)
        except ValueError:
            result["warnings"].append(f"Cannot parse DVIC duration for {name}: {raw_dur}")
            continue
        if seconds is None:
            continue
        found_duration = True
        fleet = get_cell(record, fleet_aliases)
        fleet_label = str(fleet).strip() if fleet is not None and str(fleet).strip() else "unknown"
        is_dot = _is_dot_fleet(fleet)
        fleet_class = "DOT" if is_dot else "NonDOT"
        insp_date = get_cell(record, date_aliases)
        insp_date_s = str(insp_date).strip() if insp_date is not None else ""
        # Same AKAIROS 6-minute alert for NonDOT and DOT (Amazon u90s/u300s stay classification-only).
        if seconds > threshold:
            result["below_standard"].append(
                {
                    "driver": name,
                    "metric": "DVIC PreTrip duration",
                    "value": seconds,
                    "threshold": threshold,
                    "direction": "max",
                    "fleet_type": fleet_label,
                    "fleet_class": fleet_class,
                    "inspection_date": insp_date_s,
                    "unit": "seconds",
                }
            )

    if not found_duration:
        result["warnings"].append(
            "DVIC PreTrip: no duration columns matched configured aliases; thresholds not assessed."
        )
    return result


# --- Compliance Supplementary -----------------------------------------------

def parse_compliance(path: Path, config: dict) -> dict:
    """Evaluate configured min/max metrics on driver rows when present."""
    aliases = config.get("aliases", {})
    driver_aliases = list(aliases.get("driver", DRIVER_ALIASES))
    sheet, records = find_driver_table(path, {"driver": driver_aliases})
    metrics = config.get("metrics", {})
    result = {
        "kind": ReportKind.COMPLIANCE_SUPPLEMENTARY.value,
        "file": path.name,
        "sheet": sheet,
        "rows": len(records),
        "below_standard": [],
        "warnings": [],
        "status": "live",
        "found_metrics": [],
    }
    if not records:
        result["warnings"].append(
            "Compliance Supplementary: no driver-level rows; DSP aggregates are not treated as driver evidence."
        )
        return result

    seen = set()
    found_metrics: set[str] = set()
    for record in records:
        name = str(get_cell(record, driver_aliases) or "").strip()
        key = norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        misses = []
        for metric, rule in metrics.items():
            raw = get_cell(record, rule["columns"])
            if raw is None or str(raw).strip() == "":
                continue
            found_metrics.add(metric)
            try:
                number = value_float(raw)
            except ValueError:
                result["warnings"].append(f"Cannot parse {metric} for {name}: {raw}")
                continue
            if number is None:
                continue
            threshold = rule["threshold"]
            failed = number < threshold if rule["direction"] == "min" else number > threshold
            if failed:
                misses.append(
                    {
                        "metric": metric,
                        "value": number,
                        "threshold": threshold,
                        "direction": rule["direction"],
                    }
                )
        if misses:
            result["below_standard"].append({"driver": name, "misses": misses})

    result["found_metrics"] = sorted(found_metrics)
    if not found_metrics:
        result["warnings"].append(
            "Compliance Supplementary: no configured metric columns found; thresholds not assessed."
        )
    return result


# --- Break utilization ------------------------------------------------------

BREAK_MISS_ALIASES = (
    "Break Taken",
    "Break Completed",
    "Utilized Break",
    "Break Utilized",
    "Took Break",
    "Break Status",
    "Missed Break",
)
BREAK_REQUIRED_ALIASES = (
    "Required Break",
    "Break Required",
    "Expected Break",
)


def parse_break_utilization(path: Path, config: dict) -> dict:
    aliases = config.get("aliases", {})
    driver_aliases = list(aliases.get("driver", DRIVER_ALIASES))
    sheet, records = find_driver_table(path, {"driver": driver_aliases})
    result = {
        "kind": ReportKind.BREAK_UTILIZATION.value,
        "file": path.name,
        "sheet": sheet,
        "rows": len(records),
        "below_standard": [],
        "warnings": [],
        "status": "live",
    }
    if not records:
        result["warnings"].append("Break utilization: no driver-level rows found.")
        return result

    seen = set()
    signal = False
    for record in records:
        name = str(get_cell(record, driver_aliases) or "").strip()
        key = norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        raw = get_cell(record, BREAK_MISS_ALIASES)
        if raw is None:
            continue
        signal = True
        text = str(raw).strip().casefold()
        missed = text in {"no", "false", "0", "missed", "n", "not taken", "incomplete"}
        if text in {"yes", "true", "1", "taken", "y", "complete", "completed"}:
            missed = False
        # Numeric: 0 = missed
        try:
            num = value_float(raw)
            if num is not None:
                missed = num <= 0
                signal = True
        except ValueError:
            pass
        if missed:
            result["below_standard"].append(
                {
                    "driver": name,
                    "metric": "Break utilization",
                    "value": str(raw).strip(),
                    "threshold": "break taken",
                    "direction": "required",
                }
            )
    if not signal:
        result["warnings"].append(
            "Break utilization: no break-status columns matched; file recognized but not assessed."
        )
        result["status"] = "stubbed_columns"
    return result


# --- Uniform compliance -----------------------------------------------------

UNIFORM_FAIL_ALIASES = (
    "Uniform Compliant",
    "Compliant",
    "Compliance Status",
    "Uniform Status",
    "Pass Fail",
    "Result",
)


def parse_uniform(path: Path, config: dict) -> dict:
    aliases = config.get("aliases", {})
    driver_aliases = list(aliases.get("driver", DRIVER_ALIASES))
    sheet, records = find_driver_table(path, {"driver": driver_aliases})
    result = {
        "kind": ReportKind.UNIFORM_COMPLIANCE.value,
        "file": path.name,
        "sheet": sheet,
        "rows": len(records),
        "below_standard": [],
        "warnings": [],
        "status": "live",
    }
    if not records:
        result["warnings"].append("Uniform compliance: no driver-level rows found.")
        return result
    seen = set()
    signal = False
    for record in records:
        name = str(get_cell(record, driver_aliases) or "").strip()
        key = norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        raw = get_cell(record, UNIFORM_FAIL_ALIASES)
        if raw is None:
            continue
        signal = True
        text = str(raw).strip().casefold()
        failed = text in {"no", "false", "0", "fail", "failed", "noncompliant", "non-compliant", "n"}
        if failed:
            result["below_standard"].append(
                {
                    "driver": name,
                    "metric": "Uniform compliance",
                    "value": str(raw).strip(),
                    "threshold": "compliant",
                    "direction": "required",
                }
            )
    if not signal:
        result["warnings"].append(
            "Uniform compliance: status column not matched; recognized but not assessed."
        )
        result["status"] = "stubbed_columns"
    return result


# --- Tenure / sentiment (inventory + light parse) ---------------------------

def parse_tabular_inventory(path: Path, kind: ReportKind, config: dict) -> dict:
    """Recognize driver table when present; no aggressive thresholds yet."""
    aliases = config.get("aliases", {})
    driver_aliases = list(aliases.get("driver", DRIVER_ALIASES))
    sheet, records = find_driver_table(path, {"driver": driver_aliases})
    result = {
        "kind": kind.value,
        "file": path.name,
        "sheet": sheet,
        "rows": len(records),
        "below_standard": [],
        "warnings": [],
        "status": "stubbed",
        "drivers_seen": [],
    }
    if records:
        names = []
        seen = set()
        for record in records:
            name = str(get_cell(record, driver_aliases) or "").strip()
            key = norm(name)
            if name and key not in seen:
                seen.add(key)
                names.append(name)
        result["drivers_seen"] = names[:200]
        result["warnings"].append(
            f"{kind.value}: driver rows ingested for inventory; thresholds not configured (stub)."
        )
    else:
        # Try any header-ish first row for row count
        sheet2, _h, rows = find_header_table(path, ("employee", "associate", "da", "name", "driver", "tenure"))
        result["sheet"] = sheet2
        result["rows"] = len(rows)
        result["warnings"].append(
            f"{kind.value}: file recognized; no driver-threshold rules configured (stub)."
        )
    return result


def parse_safety_event_stub(path: Path, kind: ReportKind, config: dict) -> dict:
    """No Lap Belt / Engine Off — live if driver+event columns exist; else stub."""
    aliases = config.get("aliases", {})
    driver_aliases = list(aliases.get("driver", DRIVER_ALIASES))
    sheet, records = find_driver_table(path, {"driver": driver_aliases})
    result = {
        "kind": kind.value,
        "file": path.name,
        "sheet": sheet,
        "rows": len(records),
        "below_standard": [],
        "warnings": [],
        "status": "live" if records else "stubbed",
    }
    event_aliases = (
        "Events",
        "Event Count",
        "Violations",
        "Count",
        "No Lap Belt Events",
        "Engine Off Events",
        "Occurrences",
    )
    if not records:
        result["warnings"].append(
            f"{kind.value}: recognized; no driver-level table yet (PDF dashboards stay metadata-only)."
        )
        result["status"] = "stubbed"
        return result
    seen = set()
    for record in records:
        name = str(get_cell(record, driver_aliases) or "").strip()
        key = norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        raw = get_cell(record, event_aliases)
        if raw is None:
            # Presence on a violation report implies a finding
            result["below_standard"].append(
                {
                    "driver": name,
                    "metric": kind.value,
                    "value": "listed",
                    "threshold": 0,
                    "direction": "max",
                }
            )
            continue
        try:
            number = value_float(raw)
        except ValueError:
            number = None
        if number is None or number > 0:
            result["below_standard"].append(
                {
                    "driver": name,
                    "metric": kind.value,
                    "value": number if number is not None else str(raw).strip(),
                    "threshold": 0,
                    "direction": "max",
                }
            )
    return result


def parse_pdf_metadata(classified: ClassifiedReport) -> dict:
    age_note = ""
    try:
        import datetime as dt

        mtime = dt.date.fromtimestamp(classified.path.stat().st_mtime)
        age_note = mtime.isoformat()
    except OSError:
        age_note = "unknown"
    return {
        "kind": classified.kind.value,
        "file": classified.path.name,
        "sheet": None,
        "rows": 0,
        "below_standard": [],
        "warnings": [
            f"PDF/dashboard metadata only ({classified.kind.value}); deep PDF parsing not enabled. "
            f"File mtime date: {age_note}."
        ],
        "status": "metadata",
        "station": classified.station,
        "week": classified.week,
        "report_date": classified.report_date,
    }


def parse_report(classified: ClassifiedReport, config: dict) -> dict:
    path = classified.path
    kind = classified.kind
    if kind == ReportKind.DVIC_PRETRIP:
        return parse_dvic(path, config)
    if kind == ReportKind.COMPLIANCE_SUPPLEMENTARY:
        return parse_compliance(path, config)
    if kind == ReportKind.BREAK_UTILIZATION:
        return parse_break_utilization(path, config)
    if kind == ReportKind.UNIFORM_COMPLIANCE:
        return parse_uniform(path, config)
    if kind in {ReportKind.TENURE_WORKFORCE, ReportKind.TENURE_DAS, ReportKind.SENTIMENT}:
        return parse_tabular_inventory(path, kind, config)
    if kind in {ReportKind.NO_LAP_BELT, ReportKind.ENGINE_OFF}:
        return parse_safety_event_stub(path, kind, config)
    if classified.is_pdf or kind in {
        ReportKind.DA_DAILY_REPORT,
        ReportKind.DSP_SCORECARD,
        ReportKind.POD_DETAILS,
        ReportKind.PDF_DASHBOARD,
    }:
        return parse_pdf_metadata(classified)
    if kind == ReportKind.UNKNOWN_TABULAR:
        # Fall back to generic compliance-style metric pass when metrics configured
        base = parse_compliance(path, config)
        base["kind"] = kind.value
        base["status"] = "live" if base.get("found_metrics") else "stubbed"
        if not base.get("found_metrics"):
            base["warnings"].append("Unknown tabular file: recognized but no metric columns matched.")
        return base
    return {
        "kind": kind.value,
        "file": path.name,
        "sheet": None,
        "rows": 0,
        "below_standard": [],
        "warnings": [f"Unhandled report kind: {kind.value}"],
        "status": "stubbed",
    }
