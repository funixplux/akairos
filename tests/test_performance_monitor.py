"""Tests for Cortex AKOS DVA5 performance monitor expansion."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from akos_performance_monitor.catalog import ReportKind, classify_filename, missing_kinds
from akos_performance_monitor.evaluate import evaluate_catalog, load_roster, render_summary
from akos_performance_monitor.notify import maybe_send, resolve_recipients
from akos_performance_monitor.parsers import parse_compliance, parse_dvic


@pytest.fixture()
def config():
    return json.loads(
        (Path(__file__).resolve().parents[1] / "akos_performance_monitor" / "config.json").read_text()
    )


def _write_dvic(path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "PreTrip"
    ws.append(["Driver Name", "Fleet Type", "Inspection Date", "DVIC Duration"])
    ws.append(["Alex Rivera", "NonDOT Van", "2026-09-23", 45])
    ws.append(["Blake Chen", "NonDOT Van", "2026-09-23", 120])  # over 90
    ws.append(["Casey DOT", "DOT CDV", "2026-09-23", 250])  # under 300
    ws.append(["Drew DOT", "DOT CDV", "2026-09-23", 340])  # over 300
    ws.append(["Total", "", "", 755])
    wb.save(path)


def _write_compliance(path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Compliance"
    ws.append(["DA Name", "DCR %", "POD %", "Speeding Events"])
    ws.append(["Alex Rivera", 99.8, 99.5, 0])
    ws.append(["Blake Chen", 98.0, 97.0, 2])
    wb.save(path)


def _write_break_csv(path: Path):
    path.write_text(
        "Driver,Break Taken\nAlex Rivera,yes\nBlake Chen,no\n",
        encoding="utf-8",
    )


@pytest.fixture()
def reports_dir(tmp_path: Path):
    d = tmp_path / "reports"
    d.mkdir()
    _write_dvic(d / "US_AKOS_DVA5_2026_week-38_20260923_DVIC_PreTrip_u90s-NonDOT_u300s-DOT_last7days.xlsx")
    _write_compliance(d / "US-AKOS-DVA5-Week38-2026-Compliance-Supplementary-Report.xlsx")
    _write_break_csv(d / "US-AKOS-DVA5-Week38-2026-Day1-DABreakUtilization.csv")
    (d / "US_AKOS_DVA5_Week38_2026_en_DSPScorecard.pdf").write_bytes(b"%PDF-1.4 stub")
    return d


def test_classify_dvic_and_compliance():
    c = classify_filename(
        "US_AKOS_DVA5_2026_week-38_20260918_DVIC_PreTrip_u90s-NonDOT_u300s-DOT_last7days.xlsx"
    )
    assert c.kind == ReportKind.DVIC_PRETRIP
    assert c.station == "DVA5"
    assert c.week == "38"
    assert c.report_date == "2026-09-18"
    assert c.actionable

    c2 = classify_filename("US-AKOS-DVA5-Week38-2026-Compliance-Supplementary-Report.xlsx")
    assert c2.kind == ReportKind.COMPLIANCE_SUPPLEMENTARY

    c3 = classify_filename("US-AKOS-DVA5-Week38-2026-Day3-DABreakUtilization.csv")
    assert c3.kind == ReportKind.BREAK_UTILIZATION

    c4 = classify_filename("US_AKOS_DVA5_Week38_2026_en_DSPScorecard.pdf")
    assert c4.kind == ReportKind.DSP_SCORECARD
    assert c4.is_pdf


def test_dvic_thresholds(tmp_path, config):
    path = tmp_path / "dvic.xlsx"
    _write_dvic(path)
    result = parse_dvic(path, config)
    assert result["status"] == "live"
    drivers = {x["driver"]: x for x in result["below_standard"]}
    assert "Blake Chen" in drivers
    assert drivers["Blake Chen"]["threshold"] == 90
    assert drivers["Blake Chen"]["fleet_class"] == "NonDOT"
    assert "Drew DOT" in drivers
    assert drivers["Drew DOT"]["threshold"] == 300
    assert "Alex Rivera" not in drivers
    assert "Casey DOT" not in drivers


def test_compliance_metrics(tmp_path, config):
    path = tmp_path / "comp.xlsx"
    _write_compliance(path)
    result = parse_compliance(path, config)
    assert result["status"] == "live"
    assert "DCR %" in result["found_metrics"]
    flagged = {x["driver"] for x in result["below_standard"]}
    assert flagged == {"Blake Chen"}


def test_evaluate_catalog_gaps_and_render(reports_dir, tmp_path, config):
    roster_path = tmp_path / "roster.csv"
    roster_path.write_text(
        "date,driver,scheduled\n,Alex Rivera,yes\n,Blake Chen,yes\n,Missing Person,yes\n",
        encoding="utf-8",
    )
    roster = load_roster(roster_path, "2026-09-24")
    # Remove weekly kinds except what we wrote — tenure missing should gap
    result = evaluate_catalog(reports_dir, roster, config, as_of=__import__("datetime").date(2026, 9, 24))
    kinds = {r["kind"] for r in result["reports"]}
    assert "dvic_pretrip" in kinds
    assert "compliance_supplementary" in kinds
    assert "break_utilization" in kinds
    assert "dsp_scorecard" in kinds
    gap_kinds = {g["kind"] for g in result["data_gaps"]}
    assert "tenure_workforce" in gap_kinds
    assert "uniform_compliance" in gap_kinds
    assert "Missing Person" in result["absent_from_report"]

    body = render_summary(result, include_named_details=True)
    assert "Blake Chen" in body
    assert "DVIC PreTrip duration" in body or "dvic_pretrip" in body
    assert "Data gaps:" in body


def test_missing_kinds_helper():
    from akos_performance_monitor.catalog import ClassifiedReport

    classified = [
        ClassifiedReport(
            path=Path("a.xlsx"),
            kind=ReportKind.DVIC_PRETRIP,
            station="DVA5",
            week="38",
            report_date=None,
            is_pdf=False,
            actionable=True,
        )
    ]
    missing = missing_kinds(classified, [ReportKind.DVIC_PRETRIP, ReportKind.COMPLIANCE_SUPPLEMENTARY])
    assert missing == [ReportKind.COMPLIANCE_SUPPLEMENTARY]


def test_notify_dedupe(tmp_path, monkeypatch):
    state = tmp_path / "last_sent.json"
    sent = []

    def fake_notify(subject, body, recipients):
        sent.append((subject, body, list(recipients)))

    monkeypatch.setattr("akos_performance_monitor.notify.notify", fake_notify)
    cfg = {"notify_to_default": "etimbassey@akairos.net", "email_named_driver_details": True}
    recipients = resolve_recipients(cfg)
    assert recipients == ["etimbassey@akairos.net"]

    info1 = maybe_send("subj", "body-a", recipients, state, send=True)
    info2 = maybe_send("subj", "body-a", recipients, state, send=True)
    info3 = maybe_send("subj", "body-b", recipients, state, send=True)
    assert info1["sent"] is True
    assert info2["skipped_duplicate"] is True
    assert info3["sent"] is True
    assert len(sent) == 2


def test_cli_runs(reports_dir, tmp_path, config):
    from akos_performance_monitor.monitor import main

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    roster = tmp_path / "roster.csv"
    roster.write_text("date,driver,scheduled\n,Alex Rivera,yes\n", encoding="utf-8")
    out = tmp_path / "output"
    rc = main(
        [
            "--config",
            str(cfg),
            "--reports",
            str(reports_dir),
            "--roster",
            str(roster),
            "--output",
            str(out),
            "--date",
            "2026-09-24",
            "--no-imap",
        ]
    )
    assert rc == 0
    assert (out / "review_2026-09-24.txt").exists()
    assert (out / "review_2026-09-24.json").exists()
