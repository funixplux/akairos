from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright


load_dotenv()

DEFAULT_RUNTIME_DIR = Path("runtime")
DEFAULT_PROFILE_DIR = Path("browser_profile")


def _has_work_summary(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if isinstance(payload.get("daWorkSummaryAndEligibility"), dict):
        return True
    data = payload.get("data")
    return isinstance(data, dict) and isinstance(data.get("daWorkSummaryAndEligibility"), dict)


def interactive_login(page_url: str, profile_dir: Path) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(page_url, wait_until="domcontentloaded", timeout=120_000)
        print("\nA browser window is open. Log into the Amazon DSP portal and open the Scheduling page.")
        input("When the Scheduling page is fully loaded, press Enter here to save the session and close the browser... ")
        context.close()


def pull_once(
    page_url: str,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    runtime_dir: Path = DEFAULT_RUNTIME_DIR,
    headless: bool = True,
    timeout_seconds: int = 120,
) -> dict:
    profile_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    captured: list[tuple[str, dict]] = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
        )
        page = context.pages[0] if context.pages else context.new_page()

        def handle_response(response) -> None:
            if captured:
                return
            content_type = response.headers.get("content-type", "").lower()
            if "json" not in content_type:
                return
            try:
                payload = response.json()
            except Exception:
                return
            if _has_work_summary(payload):
                captured.append((response.url, payload))

        page.on("response", handle_response)
        page.goto(page_url, wait_until="domcontentloaded", timeout=120_000)

        deadline = time.monotonic() + timeout_seconds
        while not captured and time.monotonic() < deadline:
            page.wait_for_timeout(1000)

        if not captured:
            # A reload often causes the Scheduling UI to re-request working-hour visibility.
            page.reload(wait_until="domcontentloaded", timeout=120_000)
            deadline = time.monotonic() + min(timeout_seconds, 90)
            while not captured and time.monotonic() < deadline:
                page.wait_for_timeout(1000)

        context.close()

    if not captured:
        raise RuntimeError(
            "No Amazon working-hours response was captured. Run --login first, verify AMAZON_SCHEDULING_URL points to the Scheduling page, and confirm the page loads working-hour visibility."
        )

    source_url, payload = captured[-1]
    stamp = datetime.now(timezone.utc).isoformat()
    wrapped = {
        "captured_at_utc": stamp,
        "source_url": source_url,
        "payload": payload,
    }

    latest = runtime_dir / "amazon_work_summary_latest.json"
    latest.write_text(json.dumps(wrapped, indent=2), encoding="utf-8")

    history_dir = runtime_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    safe_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (history_dir / f"amazon_work_summary_{safe_stamp}.json").write_text(
        json.dumps(wrapped, indent=2), encoding="utf-8"
    )
    return wrapped


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Amazon DSP Scheduling work-summary JSON using a persistent local browser session.")
    parser.add_argument("--url", default=os.getenv("AMAZON_SCHEDULING_URL", ""), help="Amazon DSP Scheduling page URL")
    parser.add_argument("--login", action="store_true", help="Open a browser once so you can log in and persist the session locally")
    parser.add_argument("--headed", action="store_true", help="Show the browser for a normal pull")
    parser.add_argument("--timeout", type=int, default=120, help="Seconds to wait for the work-summary response")
    args = parser.parse_args()

    if not args.url:
        raise SystemExit("Set AMAZON_SCHEDULING_URL in .env or pass --url.")

    if args.login:
        interactive_login(args.url, DEFAULT_PROFILE_DIR)
        return 0

    result = pull_once(
        args.url,
        profile_dir=DEFAULT_PROFILE_DIR,
        runtime_dir=DEFAULT_RUNTIME_DIR,
        headless=not args.headed,
        timeout_seconds=max(30, args.timeout),
    )
    print(f"Captured Amazon work-summary data at {result['captured_at_utc']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
