import pandas as pd

from connectors import PAYROLL_SPEC, connector_status, load_live_inputs


def test_file_connectors_build_combined_hours(tmp_path, monkeypatch):
    payroll = tmp_path / "payroll.csv"
    schedule = tmp_path / "schedule.csv"
    payroll.write_text(
        "\n".join(
            [
                "employee_id,name,date,hours,station,manager,dot_regulated,phone,email",
                "A1,Driver One,2026-09-01,8,DVA5,Manager A,no,,driver@example.com",
                "A1,Driver One,2026-09-02,8,DVA5,Manager A,no,,driver@example.com",
            ]
        )
    )
    schedule.write_text(
        "\n".join(
            [
                "employee_id,name,date,hours,station,manager,dot_regulated,phone,email",
                "A1,Driver One,2026-09-03,10,DVA5,Manager A,no,,driver@example.com",
            ]
        )
    )

    monkeypatch.setenv("PAYROLL_CONNECTOR_TYPE", "file")
    monkeypatch.setenv("PAYROLL_FILE_PATH", str(payroll))
    monkeypatch.setenv("DSP_SCHEDULE_CONNECTOR_TYPE", "file")
    monkeypatch.setenv("DSP_SCHEDULE_FILE_PATH", str(schedule))

    live = load_live_inputs(
        week_start=pd.Timestamp("2026-08-31"),
        now=pd.Timestamp("2026-09-02"),
    )

    row = live.combined.iloc[0]
    assert row["actual_hours"] == 16
    assert row["scheduled_remaining_hours"] == 10
    assert row["projected_hours"] == 26


def test_http_status_masks_secret(monkeypatch):
    monkeypatch.setenv("PAYROLL_CONNECTOR_TYPE", "http")
    monkeypatch.setenv("PAYROLL_API_URL", "https://example.invalid/payroll")
    monkeypatch.setenv("PAYROLL_API_TOKEN_ENV", "PAYROLL_TEST_TOKEN")
    monkeypatch.setenv("PAYROLL_TEST_TOKEN", "example-token-value")

    status = connector_status(PAYROLL_SPEC)

    assert status.ready is True
    assert status.secret_configured is True
    assert "example-token-value" not in status.detail
