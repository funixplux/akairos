# AKAIROS Hours Guard

AKAIROS Hours Guard is a Streamlit payroll + scheduling early-warning system. It combines **actual hours already worked** with **future scheduled hours** and warns management before an associate crosses 30, 40, 50, or 60 hours.

## What is implemented

- AKAIROS Sunday–Saturday workweek
- 30h planning/full-time watch
- 40h overtime warning
- 50h AKAIROS critical management threshold
- 60h working-hours policy review point
- 12h/day and 10h-rest review logic
- DOT HOS checks when supporting data is available
- Exact future shift/date where 30/40/50/60 is crossed
- Separate **already worked** vs **scheduled to reach** alerts
- Missing-punch/data-quality alerts
- Payroll CSV/XLSX import with column mapping
- Future schedule CSV/XLSX import with column mapping
- Prevention of same-day schedule double counting when actual time already exists
- DVA5/DMD2 and manager filtering
- Downloadable manager action queue
- Associate/manager roster enrichment
- Owner + manager email/SMS routing
- Slack webhook, SMTP email, and Twilio SMS notifications
- Per-recipient alert de-duplication in SQLite
- File/API live connectors
- Watched browser/download folder helper (`sync_inputs.py`)
- Amazon Working Hour Visibility JSON parser and local browser-capture helper

Actual timekeeping remains the source of truth. The app does not reduce punches, withhold pay, or automatically cancel shifts.

## Run in Codex or locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
streamlit run app.py
```

## Standardized source format

Automated payroll/schedule connectors use these columns:

```text
employee_id,name,date,hours,station,manager,dot_regulated,phone,email
```

Only the first four are required by the live connector. The remaining fields improve routing and filtering.

## Associate / manager roster

Use `sample_data/roster.csv` as the template:

```text
employee_id,name,station,manager,manager_email,manager_phone,dot_regulated,phone,email,active
```

The roster lets the automated worker send alerts to the owner and the associate's assigned manager.

## File/API connectors

Copy `.env.example` to `.env` and configure either file paths or approved HTTP endpoints:

```text
PAYROLL_CONNECTOR_TYPE=file
PAYROLL_FILE_PATH=/path/to/payroll.csv
DSP_SCHEDULE_CONNECTOR_TYPE=file
DSP_SCHEDULE_FILE_PATH=/path/to/schedule.csv
ROSTER_FILE_PATH=/path/to/roster.csv
```

Or use `http` connector type with tokens stored only in environment variables.

Run connector mode once:

```bash
python monitor.py --use-connectors --channel stdout
```

Run it every two hours:

```bash
python monitor.py --use-connectors --repeat-hours 2 --channel email
```

## Watched export folder

If browser or cloud-sync exports arrive in one folder:

```bash
python sync_inputs.py --folder ~/Downloads --out-dir runtime_inputs
```

Then point file connectors at the stable files in `runtime_inputs/`.

## Notifications

Supported channels:

- Slack: `SLACK_WEBHOOK_URL`
- Email: `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `ALERT_EMAIL`
- SMS: Twilio credentials + `ALERT_PHONE`

By default manager alerts are enabled and associate alerts are disabled:

```text
SEND_MANAGER_ALERTS=true
SEND_ASSOCIATE_ALERTS=false
```

Never commit `.env` or real employee/payroll exports.

## Amazon DSP Scheduling support

The repository includes:

- `amazon_portal.py` — parses Amazon Working Hour Visibility JSON while keeping actual and rolling-scheduled concepts separate.
- `amazon_browser_pull.py` — uses a persistent **local** Playwright browser profile so a user can authenticate interactively; no Amazon password is stored in source code.
- `pages/2_Amazon_Site_Import.py` — manually reviews/imports the captured Working Hour Visibility JSON.
- `pages/3_Live_Connectors.py` — shows live payroll/schedule connector readiness.

For local browser capture:

```bash
playwright install chromium
python amazon_browser_pull.py --login --url "$AMAZON_SCHEDULING_URL"
python amazon_browser_pull.py --url "$AMAZON_SCHEDULING_URL"
```

A dated future schedule source is still used for exact threshold-crossing dates. The app does not assume Amazon's rolling scheduled-hour field equals remaining future hours.

## Tests

```bash
pytest -q
```

The test suite covers Sunday–Saturday workweeks, actual-vs-planned overtime, 30/40/50/60 thresholds, daily/rest logic, DOT review logic, exact crossing dates, same-day double-count prevention, live file connectors, and repeating monitor behavior.
