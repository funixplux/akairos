"""Cortex AKOS DVA5 report catalog recognition from filenames."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ReportKind(str, Enum):
    DVIC_PRETRIP = "dvic_pretrip"
    COMPLIANCE_SUPPLEMENTARY = "compliance_supplementary"
    BREAK_UTILIZATION = "break_utilization"
    UNIFORM_COMPLIANCE = "uniform_compliance"
    TENURE_WORKFORCE = "tenure_workforce"
    TENURE_DAS = "tenure_das"
    SENTIMENT = "sentiment"
    NO_LAP_BELT = "no_lap_belt"
    ENGINE_OFF = "engine_off"
    DA_DAILY_REPORT = "da_daily_report"
    DSP_SCORECARD = "dsp_scorecard"
    POD_DETAILS = "pod_details"
    PDF_DASHBOARD = "pdf_dashboard"
    UNKNOWN_TABULAR = "unknown_tabular"
    UNKNOWN = "unknown"


# Priority for actionable driver-level processing (lower = higher priority).
PROCESS_PRIORITY = {
    ReportKind.DVIC_PRETRIP: 10,
    ReportKind.COMPLIANCE_SUPPLEMENTARY: 20,
    ReportKind.BREAK_UTILIZATION: 30,
    ReportKind.UNIFORM_COMPLIANCE: 40,
    ReportKind.NO_LAP_BELT: 50,
    ReportKind.ENGINE_OFF: 60,
    ReportKind.TENURE_WORKFORCE: 70,
    ReportKind.TENURE_DAS: 80,
    ReportKind.SENTIMENT: 90,
    ReportKind.UNKNOWN_TABULAR: 100,
    ReportKind.DA_DAILY_REPORT: 200,
    ReportKind.DSP_SCORECARD: 210,
    ReportKind.POD_DETAILS: 220,
    ReportKind.PDF_DASHBOARD: 230,
    ReportKind.UNKNOWN: 999,
}

# Dashboard / report titles from Cortex index (PDF or non-driver deep parse).
DASHBOARD_KEYWORDS = (
    "da training summary",
    "downtime allowance",
    "driver support dashboard",
    "dsp controllable status",
    "engine off compliance",
    "enterprise delivery accuracy",
    "fleet condition assessment",
    "wear & tear",
    "wear and tear",
    "fleet execution",
    "hub supply route",
    "labor planning",
    "last mile rental",
    "netradyne",
    "new deployment isr",
    "no lap belt",
    "pps daily",
    "san fransisco supplementary",
    "san francisco supplementary",
    "twf dashboard",
)

TABULAR_SUFFIXES = {".csv", ".xlsx", ".xls"}
PDF_SUFFIXES = {".pdf"}


@dataclass(frozen=True)
class ClassifiedReport:
    path: Path
    kind: ReportKind
    station: str | None
    week: str | None
    report_date: str | None  # YYYY-MM-DD when parseable from filename
    is_pdf: bool
    actionable: bool  # driver-level tabular parsers live / stubbed high-signal


def _norm_name(name: str) -> str:
    return re.sub(r"[\s_\-]+", " ", name).casefold().strip()


def classify_filename(path: Path | str) -> ClassifiedReport:
    p = Path(path)
    raw = p.name
    n = _norm_name(raw)
    suffix = p.suffix.lower()
    is_pdf = suffix in PDF_SUFFIXES

    station = None
    m_station = re.search(r"\b(dva5|dmd2)\b", n, re.I)
    if m_station:
        station = m_station.group(1).upper()

    week = None
    m_week = re.search(r"week[\s\-]?(\d{1,2})", n, re.I)
    if m_week:
        week = m_week.group(1)

    report_date = None
    m_date = re.search(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", raw)
    if m_date:
        report_date = f"{m_date.group(1)}-{m_date.group(2)}-{m_date.group(3)}"

    kind = ReportKind.UNKNOWN
    if "dvic" in n and "pretrip" in n.replace(" ", ""):
        kind = ReportKind.DVIC_PRETRIP
    elif "compliance" in n and "supplementary" in n:
        kind = ReportKind.COMPLIANCE_SUPPLEMENTARY
    elif "breakutilization" in n.replace(" ", "") or "break utilization" in n:
        kind = ReportKind.BREAK_UTILIZATION
    elif "uniform" in n and "compliance" in n:
        kind = ReportKind.UNIFORM_COMPLIANCE
    elif "tenure" in n and "workforce" in n:
        kind = ReportKind.TENURE_WORKFORCE
    elif "tenure" in n and ("das" in n.split() or "_das_" in raw.casefold() or "das report" in n):
        kind = ReportKind.TENURE_DAS
    elif "sentiment" in n:
        kind = ReportKind.SENTIMENT
    elif "no lap belt" in n or "nolapbelt" in n.replace(" ", ""):
        kind = ReportKind.NO_LAP_BELT
    elif "engine off" in n:
        kind = ReportKind.ENGINE_OFF
    elif "da daily report" in n or re.search(r"da[\s\-]?daily[\s\-]?report", n):
        kind = ReportKind.DA_DAILY_REPORT
    elif "dspscorecard" in n.replace(" ", "") or "dsp scorecard" in n:
        kind = ReportKind.DSP_SCORECARD
    elif "pod" in n and "detail" in n:
        kind = ReportKind.POD_DETAILS
    elif is_pdf or any(k in n for k in DASHBOARD_KEYWORDS):
        kind = ReportKind.PDF_DASHBOARD if is_pdf else ReportKind.UNKNOWN
        if any(k in n for k in ("no lap belt", "engine off")) and not is_pdf:
            # already handled above; keep for clarity
            pass
    elif suffix in TABULAR_SUFFIXES:
        kind = ReportKind.UNKNOWN_TABULAR

    actionable = kind in {
        ReportKind.DVIC_PRETRIP,
        ReportKind.COMPLIANCE_SUPPLEMENTARY,
        ReportKind.BREAK_UTILIZATION,
        ReportKind.UNIFORM_COMPLIANCE,
        ReportKind.TENURE_WORKFORCE,
        ReportKind.TENURE_DAS,
        ReportKind.NO_LAP_BELT,
        ReportKind.ENGINE_OFF,
        ReportKind.SENTIMENT,
        ReportKind.UNKNOWN_TABULAR,
    }

    return ClassifiedReport(
        path=p,
        kind=kind,
        station=station,
        week=week,
        report_date=report_date,
        is_pdf=is_pdf,
        actionable=actionable and not is_pdf,
    )


def classify_directory(reports_dir: Path) -> list[ClassifiedReport]:
    if not reports_dir.exists():
        return []
    items = []
    for path in reports_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in TABULAR_SUFFIXES | PDF_SUFFIXES:
            continue
        if path.name.startswith("."):
            continue
        items.append(classify_filename(path))
    return sorted(items, key=lambda c: (PROCESS_PRIORITY.get(c.kind, 999), -c.path.stat().st_mtime))


# Expected feed inventory for data-gap alerts (Cortex scheduled push).
EXPECTED_DAILY_KINDS = (
    ReportKind.DVIC_PRETRIP,
)

EXPECTED_WEEKLY_KINDS = (
    ReportKind.COMPLIANCE_SUPPLEMENTARY,
    ReportKind.UNIFORM_COMPLIANCE,
    ReportKind.TENURE_WORKFORCE,
    ReportKind.TENURE_DAS,
    ReportKind.BREAK_UTILIZATION,
)

EXPECTED_PDF_METADATA = (
    ReportKind.DA_DAILY_REPORT,
    ReportKind.DSP_SCORECARD,
    ReportKind.PDF_DASHBOARD,
)


def missing_kinds(
    classified: list[ClassifiedReport],
    expected: tuple[ReportKind, ...] | list[ReportKind],
) -> list[ReportKind]:
    present = {c.kind for c in classified}
    return [k for k in expected if k not in present]
