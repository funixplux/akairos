"""Helpers to present monitor results in Streamlit (and tests)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def bridge_hours_guard_smtp_env() -> None:
    """Copy Hours Guard SMTP_* into AKOS_SMTP_* when the latter are unset."""
    pairs = (
        ("SMTP_HOST", "AKOS_SMTP_HOST"),
        ("SMTP_PORT", "AKOS_SMTP_PORT"),
        ("SMTP_USER", "AKOS_SMTP_USER"),
        ("SMTP_PASSWORD", "AKOS_SMTP_PASSWORD"),
        ("SMTP_FROM", "AKOS_SMTP_FROM"),
    )
    for src, dst in pairs:
        if not os.getenv(dst) and os.getenv(src):
            os.environ[dst] = os.environ[src]
    if not os.getenv("AKOS_SMTP_STARTTLS") and os.getenv("AKOS_SMTP_PORT", os.getenv("SMTP_PORT", "")) == "587":
        os.environ["AKOS_SMTP_STARTTLS"] = "true"
    if not os.getenv("AKOS_NOTIFY_TO") and os.getenv("ALERT_EMAIL"):
        os.environ["AKOS_NOTIFY_TO"] = os.environ["ALERT_EMAIL"]


def smtp_ready() -> bool:
    bridge_hours_guard_smtp_env()
    host = os.getenv("AKOS_SMTP_HOST")
    sender = os.getenv("AKOS_SMTP_FROM") or os.getenv("AKOS_SMTP_USER")
    return bool(host and sender)


def flatten_flagged_drivers(result: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per flagged driver finding across report kinds."""
    rows: list[dict[str, Any]] = []
    for rep in result.get("reports") or []:
        kind = rep.get("kind", "")
        source = rep.get("file", "")
        for item in rep.get("below_standard") or []:
            if not isinstance(item, dict):
                continue
            if "misses" in item:
                for miss in item["misses"]:
                    rows.append(
                        {
                            "driver": item.get("driver", ""),
                            "report": kind,
                            "metric": miss.get("metric", ""),
                            "value": miss.get("value", ""),
                            "threshold": miss.get("threshold", ""),
                            "direction": miss.get("direction", ""),
                            "fleet_type": "",
                            "fleet_class": "",
                            "inspection_date": "",
                            "source_file": source,
                        }
                    )
            else:
                rows.append(
                    {
                        "driver": item.get("driver", ""),
                        "report": kind,
                        "metric": item.get("metric", ""),
                        "value": item.get("value", ""),
                        "threshold": item.get("threshold", ""),
                        "direction": item.get("direction", ""),
                        "fleet_type": item.get("fleet_type", ""),
                        "fleet_class": item.get("fleet_class", ""),
                        "inspection_date": item.get("inspection_date", ""),
                        "source_file": source,
                    }
                )
    return rows


def flatten_data_gaps(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "kind": g.get("kind", ""),
            "severity": g.get("severity", ""),
            "message": g.get("message", ""),
        }
        for g in (result.get("data_gaps") or [])
    ]


def flatten_report_status(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for rep in result.get("reports") or []:
        rows.append(
            {
                "kind": rep.get("kind", ""),
                "status": rep.get("status", ""),
                "file": rep.get("file", ""),
                "rows": rep.get("rows", 0),
                "flagged": len(rep.get("below_standard") or []),
                "warnings": "; ".join(rep.get("warnings") or []),
            }
        )
    return rows


def save_uploads(files, destination: Path) -> list[str]:
    """Write Streamlit UploadedFile objects into destination; return saved names."""
    destination.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files or []:
        name = Path(f.name).name
        target = destination / name
        target.write_bytes(f.getvalue())
        saved.append(name)
    return saved
