# AKAIROS Cortex performance monitor (AKOS DVA5)

Daily / weekly review of Cortex-distributed DSP reports for station **DVA5**. Combines local `reports/` files with optional Gmail/IMAP attachment pull. Produces a manager summary and can email **named-driver** DVIC / performance findings to an authorized recipient.

Does **not** sign in to Amazon, capture credentials, or bypass portal login.

## What is live vs stubbed

| Report kind | Recognition | Driver alerts | Notes |
|---|---|---|---|
| DVIC PreTrip `.xlsx` | live | live | AKAIROS alert: **6 minutes (360s)** for all fleets (`dvic.alert_max_seconds` / `alert_max_minutes`); Amazon u90s/u300s filenames are classification only |
| Compliance Supplementary `.xlsx` | live | live when driver rows + metric columns exist | DSP-only aggregates never invent drivers |
| Break utilization `.csv` | live | live when break-status columns match | Day packs from Cortex week files |
| Uniform compliance `.xlsx` | live | live when compliance status columns match | |
| No Lap Belt / Engine Off tabular | live if driver table | live / presence | PDF dashboards stay metadata-only |
| Tenure workforce / DAS / Sentiment CSV | live inventory | stub thresholds | Rows counted; no coaching thresholds yet |
| DA Daily / Scorecard / other PDFs | filename metadata | metadata gaps only | No deep PDF parsing |

## Set up

1. Python 3.10+ with `openpyxl` (already in repo `requirements.txt`).
2. Copy `roster.example.csv` → `roster.csv` and list scheduled drivers (`date,driver,scheduled`). Blank `date` = every day.
3. Review `config.json` thresholds (examples for configuration — confirm against ops standards).
4. Drop Cortex exports into `reports/` **or** configure IMAP for scheduled Gmail delivery.
5. **UI (recommended for etim):** from repo root run Hours Guard and open the **Performance Monitor** page, or launch the page alone:

```bash
streamlit run app.py
# sidebar → Performance Monitor

./run_performance_monitor.sh
# or: streamlit run pages/4_Performance_Monitor.py
```

Upload Cortex files (or point at a reports folder), run the review (6-minute DVIC threshold), then optionally email `etimbassey@akairos.net`.

6. **CLI:** from repo root:

```bash
python -m akos_performance_monitor.monitor
# or
python akos_performance_monitor/monitor.py --reports /path/to/reports --send
```

## Email (authorized named-driver details)

User-authorized recipient for named-driver DVIC/performance detail: `etimbassey@akairos.net`.

Config:

- `notify_to_default`: default recipient when `AKOS_NOTIFY_TO` is unset
- `email_named_driver_details`: `true` includes driver names, inspection dates, fleet types, durations

Environment:

```text
AKOS_SMTP_HOST=smtp.gmail.com
AKOS_SMTP_PORT=587
AKOS_SMTP_STARTTLS=true
AKOS_SMTP_USER=...
AKOS_SMTP_PASSWORD=...
AKOS_SMTP_FROM=...
AKOS_NOTIFY_TO=etimbassey@akairos.net
```

Optional IMAP ingest (Cortex → Gmail):

```text
AKOS_IMAP_HOST=imap.gmail.com
AKOS_IMAP_USER=...
AKOS_IMAP_PASSWORD=...
```

`--send` emails only when the summary **content signature** changes for the same recipient list (de-duplication via `output/last_sent.json`).

## Scheduling

Example Eastern 8:00 AM daily:

```cron
TZ=America/New_York
0 8 * * * cd /path/to/akairos && /usr/bin/python3 -m akos_performance_monitor.monitor --send >> akos_performance_monitor/monitor.log 2>&1
```

## Data-gap alerts

When expected daily (`dvic_pretrip`) or weekly (compliance, uniform, tenure, break utilization) kinds are missing from `reports/`, the summary lists them under **Data gaps**. Prefer Cortex scheduled push to Gmail over manual portal download when possible.

## Relation to Hours Guard

This package sits beside Hours Guard payroll/schedule alerting. It does not modify actual hours or suppress Hours Guard alerts.
