from engine import AssociateWeek, Rules, evaluate


def codes(a):
    return [x.code for x in evaluate(a, Rules())]


def test_approaching_40():
    a=AssociateWeek("1","Driver",actual_hours=31,scheduled_remaining_hours=8)
    assert "APPROACHING_40" in codes(a)


def test_overtime_40():
    a=AssociateWeek("1","Driver",actual_hours=32,scheduled_remaining_hours=10)
    assert "OVERTIME_40" in codes(a)


def test_critical_50():
    a=AssociateWeek("1","Driver",actual_hours=45,scheduled_remaining_hours=7)
    assert "CRITICAL_50" in codes(a)


def test_weekly_60_supersedes_50_band():
    a=AssociateWeek("1","Driver",actual_hours=55,scheduled_remaining_hours=6)
    c=codes(a)
    assert "WEEKLY_60_LIMIT" in c
    assert "CRITICAL_50" not in c


def test_daily_limit_and_rest():
    a=AssociateWeek("1","Driver",actual_hours=20,scheduled_remaining_hours=0,max_daily_hours=12.5,rest_before_next_shift=9)
    c=codes(a)
    assert "DAILY_MAX" in c
    assert "REST_10" in c


def test_dot_70_8d():
    a=AssociateWeek("1","Driver",actual_hours=20,scheduled_remaining_hours=0,dot_regulated=True,duty_hours_8d=65,next_shift_hours=10)
    assert "DOT_70_8D" in codes(a)
