# Codex instructions for AKAIROS Hours Guard

This repository is a Streamlit payroll and scheduling alert application for AKAIROS LLC.

## Goals
- Combine actual worked hours with remaining scheduled hours.
- Alert before associates approach or cross 30, 40, and 50 weekly hours.
- Keep 60-hour weekly, 12-hour daily, 10-hour rest, and DOT HOS checks distinct from management thresholds.
- Do not change payroll punches or cancel shifts automatically.
- Keep credentials out of source control.

## Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
streamlit run app.py
```

## Data flow
- `importers.py`: payroll/schedule parsing and standardization
- `engine.py`: threshold and compliance alert logic
- `app.py`: Streamlit dashboard
- `monitor.py`: unattended alert execution
- `notifier.py`: Slack, email, and Twilio SMS
- `storage.py`: SQLite snapshots and alert de-duplication

## Safe development rules
- Never commit Amazon, payroll, Twilio, SMTP, or Slack credentials.
- Use `.env` locally and keep `.env.example` placeholders only.
- Preserve actual worked time as the source of truth for payroll; schedule data is used only for projection.
- Missing punches must remain visible as a critical data-quality alert.
