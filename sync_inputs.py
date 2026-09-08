from __future__ import annotations

import argparse
from pathlib import Path
import shutil


def newest_matching(folder: Path, patterns: list[str]) -> Path | None:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(folder.glob(pattern))
    matches = [p for p in matches if p.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def sync(folder: str, out_dir: str = "runtime_inputs") -> tuple[Path, Path]:
    src = Path(folder).expanduser().resolve()
    dst = Path(out_dir).expanduser().resolve()
    dst.mkdir(parents=True, exist_ok=True)
    payroll = newest_matching(src, ["*TimeDetail*.csv", "*TimeDetail*.xlsx", "*Timedetail*.csv", "*Timedetail*.xlsx", "*payroll*.csv", "*payroll*.xlsx"])
    schedule = newest_matching(src, ["*schedule*.csv", "*schedule*.xlsx", "*roster*.csv", "*roster*.xlsx"])
    if payroll is None:
        raise FileNotFoundError("No payroll/time-detail export found in the watched folder.")
    if schedule is None:
        raise FileNotFoundError("No schedule/roster export found in the watched folder.")
    payroll_out = dst / f"payroll{payroll.suffix.lower()}"
    schedule_out = dst / f"schedule{schedule.suffix.lower()}"
    shutil.copy2(payroll, payroll_out)
    shutil.copy2(schedule, schedule_out)
    return payroll_out, schedule_out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Copy the newest AKAIROS payroll and schedule exports into a stable runtime folder.")
    ap.add_argument("--folder", required=True, help="Folder where browser/download/Drive sync exports land")
    ap.add_argument("--out-dir", default="runtime_inputs")
    args = ap.parse_args()
    p, s = sync(args.folder, args.out_dir)
    print(f"Payroll: {p}")
    print(f"Schedule: {s}")
