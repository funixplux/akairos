"""Roster loading, multi-report evaluation, and summary rendering."""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from .catalog import (
    EXPECTED_DAILY_KINDS,
    EXPECTED_PDF_METADATA,
    EXPECTED_WEEKLY_KINDS,
    ClassifiedReport,
    ReportKind,
    classify_directory,
    missing_kinds,
)
from .parsers import parse_report
from .parsers_common import norm


def load_roster(path: Path, date: str) -> dict[str, str]:
    """Roster columns: date, driver, scheduled. Empty date means every day."""
    if not path.exists():
        raise FileNotFoundError(f"Roster missing: {path}")
    names: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            d = (row.get("date") or "").strip()
            scheduled = (row.get("scheduled") or "yes").strip().casefold()
            name = (row.get("driver") or "").strip()
            if name and (not d or d == date) and scheduled not in {"no", "false", "0"}:
                names[norm(name)] = name
    return names


def evaluate_catalog(
    reports_dir: Path,
    roster: dict[str, str],
    config: dict,
    as_of: dt.date | None = None,
) -> dict:
    """Classify all reports, parse actionable types, emit data-gap alerts."""
    as_of = as_of or dt.date.today()
    classified = classify_directory(reports_dir)
    expected_daily = [ReportKind(x) for x in config.get("expected_daily", [k.value for k in EXPECTED_DAILY_KINDS])]
    expected_weekly = [ReportKind(x) for x in config.get("expected_weekly", [k.value for k in EXPECTED_WEEKLY_KINDS])]
    expected_pdf = [ReportKind(x) for x in config.get("expected_pdf_metadata", [k.value for k in EXPECTED_PDF_METADATA])]

    gaps = []
    for kind in missing_kinds(classified, expected_daily):
        gaps.append(
            {
                "kind": kind.value,
                "severity": "daily",
                "message": f"Expected daily report missing: {kind.value}. Check Cortex/Gmail feed.",
            }
        )
    for kind in missing_kinds(classified, expected_weekly):
        gaps.append(
            {
                "kind": kind.value,
                "severity": "weekly",
                "message": f"Expected weekly report missing: {kind.value}. Check Cortex week pack.",
            }
        )

    # Prefer newest file per kind
    by_kind: dict[ReportKind, ClassifiedReport] = {}
    for item in classified:
        if item.kind not in by_kind:
            by_kind[item.kind] = item

    reports_out = []
    all_flagged_drivers: set[str] = set()
    seen_driver_keys: set[str] = set()

    # Process actionable kinds first (already sorted by classify_directory priority)
    for item in classified:
        if by_kind.get(item.kind) is not item:
            continue  # only newest per kind
        parsed = parse_report(item, config)
        stale_days = int(config.get("stale_after_days", 8))
        kind_stale = config.get("stale_after_days_by_kind", {}).get(item.kind.value)
        if kind_stale is not None:
            stale_days = int(kind_stale)
        try:
            age = as_of - dt.date.fromtimestamp(item.path.stat().st_mtime)
            if age.days > stale_days:
                parsed.setdefault("warnings", []).append(
                    f"File is {age.days} days old (stale after {stale_days}); verify Cortex delivery."
                )
        except OSError:
            pass

        # Collect drivers from live driver tables for absence checks
        if item.kind in {
            ReportKind.DVIC_PRETRIP,
            ReportKind.COMPLIANCE_SUPPLEMENTARY,
            ReportKind.BREAK_UTILIZATION,
            ReportKind.UNIFORM_COMPLIANCE,
        } and parsed.get("rows"):
            from .parsers_common import DRIVER_ALIASES, find_driver_table, get_cell

            _sheet, records = find_driver_table(item.path, config.get("aliases"))
            aliases = list((config.get("aliases") or {}).get("driver", DRIVER_ALIASES))
            for record in records:
                name = str(get_cell(record, aliases) or "").strip()
                if name:
                    seen_driver_keys.add(norm(name))

        for entry in parsed.get("below_standard", []):
            if isinstance(entry, dict) and entry.get("driver"):
                all_flagged_drivers.add(norm(entry["driver"]))

        reports_out.append(parsed)

    # PDF metadata presence gaps (soft)
    pdf_present = {c.kind for c in classified if c.is_pdf or c.kind in EXPECTED_PDF_METADATA}
    for kind in expected_pdf:
        if kind not in pdf_present and kind not in {c.kind for c in classified}:
            gaps.append(
                {
                    "kind": kind.value,
                    "severity": "pdf_metadata",
                    "message": f"PDF/dashboard not seen locally: {kind.value} (metadata alert only).",
                }
            )

    absent = []
    if roster:
        # Only report absences when at least one driver-level report had rows
        if seen_driver_keys:
            absent = sorted(
                (name for key, name in roster.items() if key not in seen_driver_keys),
                key=str.casefold,
            )
        else:
            gaps.append(
                {
                    "kind": "roster_compare",
                    "severity": "daily",
                    "message": "Roster loaded but no driver-level report rows available for absence check.",
                }
            )

    return {
        "date": as_of.isoformat(),
        "station": config.get("station", "DVA5"),
        "files_seen": [c.path.name for c in classified],
        "kinds_seen": sorted({c.kind.value for c in classified}),
        "reports": reports_out,
        "data_gaps": gaps,
        "absent_from_report": absent,
        "flagged_driver_count": len(all_flagged_drivers),
        "status": "reviewed" if classified else "no_report",
    }


def render_summary(result: dict, include_named_details: bool = True) -> str:
    date = result.get("date", "")
    lines = [
        f"AKAIROS Cortex performance review | {date} | station {result.get('station', 'DVA5')}",
        f"Status: {result.get('status')}",
        f"Files seen ({len(result.get('files_seen', []))}): {', '.join(result.get('files_seen', [])) or 'none'}",
        f"Kinds: {', '.join(result.get('kinds_seen', [])) or 'none'}",
        "",
        "Data gaps:",
    ]
    gaps = result.get("data_gaps") or []
    if gaps:
        for g in gaps:
            lines.append(f"- [{g.get('severity')}] {g.get('message')}")
    else:
        lines.append("- None")

    lines.extend(["", "Report findings:"])
    reports = result.get("reports") or []
    if not reports:
        lines.append("- No reports processed.")
    for rep in reports:
        kind = rep.get("kind", "unknown")
        status = rep.get("status", "")
        lines.append(f"- {kind} [{status}] file={rep.get('file')} rows={rep.get('rows', 0)}")
        for w in rep.get("warnings") or []:
            lines.append(f"    warning: {w}")
        below = rep.get("below_standard") or []
        if not below:
            lines.append("    below standard: none identified from available columns")
            continue
        for item in below:
            if not include_named_details:
                lines.append("    below standard: (named details suppressed by config)")
                break
            if "misses" in item:
                details = "; ".join(
                    f"{m['metric']} {m['value']} ({'min' if m['direction']=='min' else 'max'} {m['threshold']})"
                    for m in item["misses"]
                )
                lines.append(f"    - {item['driver']}: {details}")
            else:
                extra = []
                if item.get("fleet_type"):
                    extra.append(f"fleet={item['fleet_type']} ({item.get('fleet_class', '')})")
                if item.get("inspection_date"):
                    extra.append(f"date={item['inspection_date']}")
                if item.get("unit"):
                    extra.append(item["unit"])
                suffix = f" [{' | '.join(extra)}]" if extra else ""
                direction = item.get("direction") or "max"
                if direction == "required":
                    bound = f"(expected {item.get('threshold')})"
                elif direction == "min":
                    bound = f"(min {item.get('threshold')})"
                else:
                    bound = f"(max {item.get('threshold')})"
                lines.append(
                    f"    - {item.get('driver')}: {item.get('metric')} {item.get('value')} "
                    f"{bound}{suffix}"
                )

    lines.extend(["", "Scheduled drivers absent from driver-level reports:"])
    absent = result.get("absent_from_report") or []
    if absent and include_named_details:
        lines.extend(f"- {x}" for x in absent)
    elif absent and not include_named_details:
        lines.append(f"- {len(absent)} driver(s) (names suppressed by config)")
    else:
        lines.append("- None identified (or check unavailable; see gaps/warnings)")

    lines.extend(
        [
            "",
            "Named-driver DVIC/performance details are authorized for etimbassey@akairos.net when enabled in config.",
            "A flagged record requires manager review before driver coaching.",
            "This tool does not automate Amazon credential capture or portal login bypass.",
        ]
    )
    return "\n".join(lines) + "\n"
