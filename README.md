# AKAIROS Hours Guard

A Codex-ready Streamlit app that combines **actual payroll/timekeeping hours** with **remaining scheduled hours** to warn before an associate reaches 30, 40, 50, or 60 hours.

## What it does

- Imports payroll/timekeeping CSV/XLSX.
- Imports Amazon schedule/roster CSV/XLSX.
- Lets you map columns when exports use different headers.
- Calculates actual worked hours, remaining scheduled hours, and projected weekly hours.
- Warnings at 30h, 40h, 50h; separate critical policy checks at 60h/week, 12h/day, and <10h rest.
- Flags missing/incomplete punches.
- Optional DOT HOS checks when the required data is available.
- Sends Slack, email, or Twilio SMS notifications when configured.
- Includes `monitor.py` for scheduled/cron alerting with de-duplication.

## Run in Codex / terminal

```bash
cd akairos_hours_guard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL shown by Streamlit (usually `http://localhost:8501`).

## Test

```bash
pytest -q
```

## Automated alert run

The monitor expects standardized columns: `employee_id,name,date,hours,station,manager,dot_regulated,phone,email`.

```bash
python monitor.py \
  --payroll sample_data/payroll.csv \
  --schedule sample_data/schedule.csv \
  --channel stdout
```

For a real deployment, configure `.env` from `.env.example` and schedule `monitor.py` every 15-30 minutes using your hosting platform's cron/scheduler.

## Notification channels

- Slack incoming webhook: `SLACK_WEBHOOK_URL`
- SMS: Twilio credentials + sender number
- Email: SMTP credentials

Do not store Amazon credentials in this repo. Connect the DSP Scheduling Portal through an approved export/API or controlled integration. The app is designed so the schedule source can be replaced later without changing the alert engine.

## Rule notes

The code distinguishes policy/compliance limits from AKAIROS management thresholds:
- 30h: planning / benefit-status watch.
- 40h: overtime warning.
- 50h: AKAIROS management critical threshold.
- 60h rolling seven-day: Amazon working-hours policy limit (except special/emergency situations).
- 12h/day and 10h rest between shifts: Amazon Supplier working-hours limits.
- DOT HOS checks are applied only when relevant fields are available.

This software does not edit punches, withhold pay, or automatically cancel shifts. It alerts managers for review.
