# Codex instructions — AKAIROS Hours Guard

This repository is the production AKAIROS LLC payroll + scheduling hours-alert project.

## Goal
Combine actual worked time with future scheduled time and notify management before associates cross 30, 40, or 50 hours, while separately enforcing working-hour and DOT review rules.

## Non-negotiable behavior
- Actual payroll/timekeeping hours are the source of truth for time already worked.
- Never modify, reduce, round down, or fabricate actual hours to suppress an alert.
- Keep future schedule hours separate from actual worked hours.
- AKAIROS workweek is Sunday through Saturday.
- Distinguish "already reached" from "scheduled to reach" in 30/40/50/60 alerts.
- Missing punches remain visible until corrected in the payroll provider.
- Do not commit credentials, Amazon passwords, session cookies, tokens, employee bank/tax data, or production exports.
- Browser profile/session data stays local and ignored by git.
- Run `pytest -q` after meaningful logic changes.

## Core files
- `app.py`: primary Streamlit dashboard.
- `importers.py`: actual/schedule normalization, same-day de-duplication, weekly aggregation.
- `planner.py`: exact future shift/date when thresholds are crossed.
- `engine.py`: alert rules.
- `roster.py`: associate + manager routing enrichment.
- `connectors.py`: file/API live payroll + schedule sources.
- `amazon_portal.py`: parser for Amazon Working Hour Visibility JSON.
- `amazon_browser_pull.py`: local persistent-browser capture; no passwords in source.
- `pages/2_Amazon_Site_Import.py`: manual Amazon JSON import.
- `pages/3_Live_Connectors.py`: live-source readiness/load UI.
- `monitor.py`: unattended alert worker, connector mode and repeating checks.
- `notifier.py`: Slack/email/Twilio.
- `storage.py`: SQLite snapshots and delivery de-duplication.

## Rules
- 30h: planning / full-time eligibility watch.
- 40h: overtime threshold.
- 50h: AKAIROS critical management threshold.
- 60h: working-hours policy review point; Amazon policy is rolling seven days.
- 12h/day and 10h rest between shifts: working-hours controls.
- 7/7 current-workweek days: rolling-day-off review.
- DOT: 10h off, 11h driving, 14h duty window, 70h/8 days when supporting data is available.

## Production priorities
1. Parse AKAIROS payroll time-detail exports reliably.
2. Ingest dated future Amazon schedule/roster data without double counting today's already-started shift.
3. Show exact crossing date for 30/40/50/60.
4. Route owner + manager alerts by DVA5/DMD2 assignment.
5. Maintain an audit trail and per-recipient de-duplication.
6. Use only approved Amazon access methods; never automate credential capture.
