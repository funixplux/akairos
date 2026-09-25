#!/usr/bin/env python3
"""AKAIROS Cortex AKOS DVA5 performance monitor CLI.

Reads local report folders and optional Gmail/IMAP Cortex attachments.
Never automates Amazon credential capture or portal login bypass.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

# Allow `python monitor.py` from package directory and `python -m akos_performance_monitor.monitor`.
_PKG = Path(__file__).resolve().parent
_ROOT = _PKG.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from akos_performance_monitor.evaluate import evaluate_catalog, load_roster, render_summary
from akos_performance_monitor.ingest import pull_imap
from akos_performance_monitor.notify import maybe_send, resolve_recipients


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=_PKG / "config.json",
        help="Path to config.json",
    )
    parser.add_argument("--reports", type=Path, default=_PKG / "reports")
    parser.add_argument("--roster", type=Path, default=_PKG / "roster.csv")
    parser.add_argument("--output", type=Path, default=_PKG / "output")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument(
        "--send",
        action="store_true",
        help="Email results using AKOS_SMTP_* (named-driver details when config allows)",
    )
    parser.add_argument(
        "--no-imap",
        action="store_true",
        help="Skip IMAP pull even if AKOS_IMAP_* is set",
    )
    args = parser.parse_args(argv)

    config = json.loads(args.config.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    args.reports.mkdir(parents=True, exist_ok=True)

    incoming: list[str] = []
    if not args.no_imap:
        incoming = pull_imap(args.reports, config)

    as_of = dt.date.fromisoformat(args.date)
    try:
        roster = load_roster(args.roster, args.date) if args.roster.exists() else {}
    except FileNotFoundError:
        roster = {}

    result = evaluate_catalog(args.reports, roster, config, as_of=as_of)
    result["new_email_attachments"] = incoming
    if not args.roster.exists():
        result.setdefault("data_gaps", []).append(
            {
                "kind": "roster",
                "severity": "daily",
                "message": f"Roster file missing at {args.roster}; absence checks skipped. Copy roster.example.csv.",
            }
        )

    include_names = bool(config.get("email_named_driver_details", True))
    body = render_summary(result, include_named_details=include_names)

    (args.output / f"review_{args.date}.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (args.output / f"review_{args.date}.txt").write_text(body, encoding="utf-8")
    print(body)

    recipients = resolve_recipients(config)
    send_info = maybe_send(
        subject=f"AKAIROS Cortex performance review - {args.date}",
        body=body,
        recipients=recipients,
        state_path=args.output / "last_sent.json",
        send=args.send,
    )
    result["notify"] = send_info
    (args.output / f"review_{args.date}.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    if args.send:
        if send_info.get("sent"):
            print(f"Email sent to: {', '.join(recipients)}")
        elif send_info.get("skipped_duplicate"):
            print("Email skipped (duplicate content signature for same recipients).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
