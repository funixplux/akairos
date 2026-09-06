import pytest

import monitor


def test_run_repeating_honors_max_runs(monkeypatch):
    calls = []
    sleeps = []

    def fake_run_once(*args):
        calls.append(args)

    monkeypatch.setattr(monitor, "run_once", fake_run_once)
    monkeypatch.setattr(monitor.time, "sleep", lambda seconds: sleeps.append(seconds))

    monitor.run_repeating(
        payroll_path="payroll.csv",
        schedule_path="schedule.csv",
        channel="stdout",
        recipient=None,
        use_connectors=False,
        repeat_hours=2,
        max_runs=2,
    )

    assert len(calls) == 2
    assert sleeps == [7200]


def test_run_repeating_rejects_zero_interval():
    with pytest.raises(ValueError):
        monitor.run_repeating(
            payroll_path=None,
            schedule_path=None,
            channel="stdout",
            recipient=None,
            use_connectors=True,
            repeat_hours=0,
            max_runs=1,
        )
