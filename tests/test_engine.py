import pandas as pd

from engine import AssociateWeek, Rules, evaluate
from importers import normalize_actual_rows, normalize_schedule_rows, prepare_actuals, prepare_schedule, combine_actuals_schedule
from planner import project_threshold_crossings, crossing_summary
from workweek import week_start_for, week_key_for


def codes(a):
    return [x.code for x in evaluate(a, Rules())]


def test_approaching_40():
    a = AssociateWeek("1", "Driver", actual_hours=31, scheduled_remaining_hours=8)
    assert "APPROACHING_40" in codes(a)


def test_planned_overtime_40_is_not_same_as_actual_overtime():
    a = AssociateWeek("1", "Driver", actual_hours=32, scheduled_remaining_hours=10, cross_40_date="2026-09-04")
    c = codes(a)
    assert "PLANNED_OVERTIME_40" in c
    assert "OVERTIME_40_REACHED" not in c


def test_actual_overtime_reached():
    a = AssociateWeek("1", "Driver", actual_hours=41, scheduled_remaining_hours=0)
    assert "OVERTIME_40_REACHED" in codes(a)


def test_planned_critical_50():
    a = AssociateWeek("1", "Driver", actual_hours=45, scheduled_remaining_hours=7)
    assert "PLANNED_50" in codes(a)


def test_weekly_60_supersedes_50_band():
    a = AssociateWeek("1", "Driver", actual_hours=55, scheduled_remaining_hours=6)
    c = codes(a)
    assert "PLANNED_60_LIMIT" in c
    assert "PLANNED_50" not in c


def test_daily_limit_and_rest():
    a = AssociateWeek("1", "Driver", actual_hours=20, scheduled_remaining_hours=0, max_daily_hours=12.5, rest_before_next_shift=9)
    c = codes(a)
    assert "DAILY_MAX_REACHED" in c
    assert "REST_10" in c


def test_future_shift_over_daily_limit():
    a = AssociateWeek("1", "Driver", actual_hours=20, scheduled_remaining_hours=13, max_scheduled_shift_hours=13)
    assert "SCHEDULED_DAILY_MAX" in codes(a)


def test_dot_70_8d():
    a = AssociateWeek("1", "Driver", actual_hours=20, scheduled_remaining_hours=0, dot_regulated=True, duty_hours_8d=65, next_shift_hours=10)
    assert "DOT_70_8D" in codes(a)


def test_seven_day_schedule_review():
    a = AssociateWeek("1", "Driver", days_worked=4, scheduled_days=3)
    assert "DAY_OFF_REVIEW" in codes(a)


def test_akairos_week_is_sunday_to_saturday():
    assert week_start_for(pd.Timestamp("2026-09-05")) == pd.Timestamp("2026-08-30").date()
    assert week_start_for(pd.Timestamp("2026-09-06")) == pd.Timestamp("2026-09-06").date()
    assert week_key_for(pd.Timestamp("2026-09-08")) == "2026-09-06_2026-09-12"


def test_threshold_crossing_date_from_future_schedule():
    actuals = pd.DataFrame([{"employee_id":"A1","name":"Driver","actual_hours":31.0}])
    detail = pd.DataFrame([
        {"employee_id":"A1","name":"Driver","date":pd.Timestamp("2026-09-10"),"hours":8.0},
        {"employee_id":"A1","name":"Driver","date":pd.Timestamp("2026-09-11"),"hours":10.0},
    ])
    crossings = project_threshold_crossings(actuals, detail, thresholds=(40, 50))
    summary = crossing_summary(crossings).iloc[0]
    assert summary["cross_40_date"] == "2026-09-11"
    assert "cross_50_date" not in summary.index or not summary.get("cross_50_date", "")


def test_hours_column_does_not_false_flag_missing_start_end():
    df = pd.DataFrame([{"name":"Driver","date":"2026-09-06","hours":10.0,"start":"","end":""}])
    mapping = {"name":"name","date":"date","hours":"hours","start":"start","end":"end"}
    detail = normalize_actual_rows(df, mapping, week_start=pd.Timestamp("2026-09-06"))
    assert bool(detail.iloc[0]["missing_punch"]) is False


def test_today_schedule_not_double_counted_if_actual_time_exists():
    payroll = pd.DataFrame([{"employee_id":"A1","name":"Driver","date":"2026-09-08","hours":4.0}])
    sched = pd.DataFrame([
        {"employee_id":"A1","name":"Driver","date":"2026-09-08","hours":10.0},
        {"employee_id":"A1","name":"Driver","date":"2026-09-09","hours":10.0},
    ])
    mapping = {"name":"name","id":"employee_id","date":"date","hours":"hours"}
    actual_detail = normalize_actual_rows(payroll, mapping, week_start=pd.Timestamp("2026-09-06"))
    schedule_detail = normalize_schedule_rows(sched, mapping, now=pd.Timestamp("2026-09-08 18:00"), week_start=pd.Timestamp("2026-09-06"), actual_detail=actual_detail)
    assert schedule_detail["date"].dt.date.tolist() == [pd.Timestamp("2026-09-09").date()]


def test_combine_actuals_and_schedule():
    payroll = pd.DataFrame([{"employee_id":"A1","name":"Driver","date":"2026-09-06","hours":10.0}])
    sched = pd.DataFrame([{"employee_id":"A1","name":"Driver","date":"2026-09-10","hours":10.0}])
    mapping = {"name":"name","id":"employee_id","date":"date","hours":"hours"}
    actual = prepare_actuals(payroll, mapping, week_start=pd.Timestamp("2026-09-06"))
    schedule = prepare_schedule(sched, mapping, now=pd.Timestamp("2026-09-08"), week_start=pd.Timestamp("2026-09-06"))
    combined = combine_actuals_schedule(actual, schedule)
    assert combined.iloc[0]["projected_hours"] == 20.0
    assert combined.iloc[0]["scheduled_days"] == 1
