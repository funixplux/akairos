# Codex instructions for AKAIROS Hours Guard

This repository is a Streamlit payroll and scheduling alert application for AKAIROS LLC.

## Goals

- Combine actual worked hours with remaining scheduled hours.
- Alert before associates approach or cross 30, 40, and 50 weekly hours.
- Keep 60-hour weekly, 12-hour daily, 10-hour rest, and DOT HOS checks distinct from management thresholds.
- Do not change payroll punches or cancel shifts automatically.
- Keep credentials out of source control.
- Prepare the app to connect actual payroll/timekeeping data with Amazon DSP scheduling data.

## Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
streamlit run app.py
```

## Data flow

- `importers.py`: payroll/schedule parsing and standardization.
- `connectors.py`: file/API connector readiness and live standardized payroll + schedule ingestion.
- `engine.py`: threshold and compliance alert logic.
- `app.py`: Streamlit dashboard.
- `pages/3_Live_Connectors.py`: live connector readiness and manual connector load page.
- `monitor.py`: unattended alert execution, including `--use-connectors` and `--repeat-hours 2`.
- `notifier.py`: Slack, email, and Twilio SMS.
- `storage.py`: SQLite snapshots and alert de-duplication.

## Connector work

- Production connectors should emit the standardized columns used by `connectors.STANDARD_MAPPING`: `employee_id`, `name`, `date`, `hours`, `station`, `manager`, `dot_regulated`, `phone`, and `email`.
- Store connector secrets in environment variables only. Keep `.env` local and use `.env.example` for names and empty placeholders.
- Prefer adding source-specific adapters behind `connectors.py` instead of changing the alert engine.
- The two-hour refresh requirement is handled by `monitor.py --use-connectors --repeat-hours 2` or by an external scheduler running the one-shot connector command every two hours.

## Safe development rules

- Never commit Amazon, payroll, Twilio, SMTP, Slack, API, or webhook credentials.
- Use `.env` locally and keep `.env.example` placeholders only.
- Preserve actual worked time as the source of truth for payroll; schedule data is used only for projection.
- Missing punches must remain visible as a critical data-quality alert.
- Do not commit downloaded production payroll exports, schedule exports, browser session files, or local SQLite databases.
