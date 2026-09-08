from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Optional


@dataclass
class Rules:
    watch_30: float = 30.0
    overtime_40: float = 40.0
    critical_50: float = 50.0
    amazon_weekly_max: float = 60.0
    daily_max: float = 12.0
    min_rest_hours: float = 10.0
    lead_hours: float = 2.0
    dot_max_duty_8d: float = 70.0
    dot_max_drive_after_rest: float = 11.0
    dot_max_duty_window: float = 14.0


@dataclass
class AssociateWeek:
    employee_id: str
    name: str
    station: str = ""
    actual_hours: float = 0.0
    scheduled_remaining_hours: float = 0.0
    days_worked: int = 0
    scheduled_days: int = 0
    next_shift_hours: float = 0.0
    next_shift_date: str = ""
    max_daily_hours: float = 0.0
    max_scheduled_shift_hours: float = 0.0
    rest_before_next_shift: Optional[float] = None
    dot_regulated: bool = False
    duty_hours_8d: Optional[float] = None
    drive_hours_next_shift: Optional[float] = None
    missing_punch: bool = False
    manager: str = ""
    manager_email: str = ""
    manager_phone: str = ""
    phone: str = ""
    email: str = ""
    cross_30_date: str = ""
    cross_40_date: str = ""
    cross_50_date: str = ""
    cross_60_date: str = ""

    @property
    def projected_hours(self) -> float:
        return round(float(self.actual_hours) + float(self.scheduled_remaining_hours), 2)

    @property
    def projected_days(self) -> int:
        return min(7, int(self.days_worked or 0) + int(self.scheduled_days or 0))


@dataclass
class Alert:
    employee_id: str
    name: str
    severity: str
    code: str
    message: str
    actual_hours: float
    projected_hours: float
    station: str = ""
    threshold: Optional[float] = None
    crossing_date: str = ""

    def to_dict(self):
        return asdict(self)


def evaluate(assoc: AssociateWeek, rules: Rules | None = None) -> list[Alert]:
    rules = rules or Rules()
    alerts: list[Alert] = []
    actual = float(assoc.actual_hours or 0)
    projected = assoc.projected_hours

    def add(severity: str, code: str, message: str, threshold: float | None = None, crossing_date: str = ""):
        alerts.append(Alert(
            employee_id=assoc.employee_id,
            name=assoc.name,
            station=assoc.station,
            severity=severity,
            code=code,
            message=message,
            actual_hours=round(actual, 2),
            projected_hours=projected,
            threshold=threshold,
            crossing_date=crossing_date,
        ))

    if assoc.missing_punch:
        add("critical", "MISSING_PUNCH", "Missing/incomplete time data detected. Review the payroll timecard before relying on the projection.")

    if actual >= rules.amazon_weekly_max:
        add("critical", "WEEKLY_60_REACHED", f"Actual hours are {actual:.1f}, at/above the configured {rules.amazon_weekly_max:.0f}-hour working-hours limit review point.", rules.amazon_weekly_max)
    elif projected >= rules.amazon_weekly_max:
        when = f" on {assoc.cross_60_date}" if assoc.cross_60_date else ""
        add("critical", "PLANNED_60_LIMIT", f"Current schedule projects {projected:.1f} hours and would reach/exceed {rules.amazon_weekly_max:.0f} hours{when}. Review immediately before the shift is worked.", rules.amazon_weekly_max, assoc.cross_60_date)
    elif actual >= rules.critical_50:
        add("critical", "CRITICAL_50_REACHED", f"Actual hours are {actual:.1f}, at/above the AKAIROS {rules.critical_50:.0f}-hour critical management threshold.", rules.critical_50)
    elif projected >= rules.critical_50:
        when = f" on {assoc.cross_50_date}" if assoc.cross_50_date else ""
        add("critical", "PLANNED_50", f"Current schedule projects {projected:.1f} hours and would reach/exceed the AKAIROS {rules.critical_50:.0f}-hour critical threshold{when}.", rules.critical_50, assoc.cross_50_date)
    elif projected >= rules.critical_50 - rules.lead_hours:
        add("critical", "APPROACHING_50", f"Projected weekly hours are {projected:.1f}; associate is within {rules.lead_hours:.1f} hours of the {rules.critical_50:.0f}-hour critical threshold.", rules.critical_50, assoc.cross_50_date)
    elif actual >= rules.overtime_40:
        add("warning", "OVERTIME_40_REACHED", f"Actual hours are {actual:.1f}, at/above the {rules.overtime_40:.0f}-hour overtime threshold.", rules.overtime_40)
    elif projected >= rules.overtime_40:
        when = f" on {assoc.cross_40_date}" if assoc.cross_40_date else ""
        add("warning", "PLANNED_OVERTIME_40", f"Current schedule projects {projected:.1f} hours and would reach/exceed {rules.overtime_40:.0f} hours{when}. Review the remaining schedule before the shift is worked.", rules.overtime_40, assoc.cross_40_date)
    elif projected >= rules.overtime_40 - rules.lead_hours:
        add("warning", "APPROACHING_40", f"Projected weekly hours are {projected:.1f}; associate is within {rules.lead_hours:.1f} hours of the {rules.overtime_40:.0f}-hour overtime threshold.", rules.overtime_40, assoc.cross_40_date)
    elif actual >= rules.watch_30:
        add("watch", "WATCH_30_REACHED", f"Actual hours are {actual:.1f}, at/above the {rules.watch_30:.0f}-hour planning / full-time eligibility watch threshold.", rules.watch_30)
    elif projected >= rules.watch_30:
        when = f" on {assoc.cross_30_date}" if assoc.cross_30_date else ""
        add("watch", "PLANNED_30", f"Current schedule projects {projected:.1f} hours and would reach/exceed the {rules.watch_30:.0f}-hour planning watch threshold{when}.", rules.watch_30, assoc.cross_30_date)
    elif projected >= rules.watch_30 - rules.lead_hours:
        add("watch", "APPROACHING_30", f"Projected weekly hours are {projected:.1f}; associate is within {rules.lead_hours:.1f} hours of the {rules.watch_30:.0f}-hour watch threshold.", rules.watch_30, assoc.cross_30_date)

    if assoc.max_daily_hours > rules.daily_max:
        add("critical", "DAILY_MAX_REACHED", f"A worked day reached {assoc.max_daily_hours:.1f} hours, above the configured {rules.daily_max:.0f}-hour daily limit.", rules.daily_max)
    if assoc.max_scheduled_shift_hours > rules.daily_max:
        add("critical", "SCHEDULED_DAILY_MAX", f"A future scheduled shift is {assoc.max_scheduled_shift_hours:.1f} hours, above the configured {rules.daily_max:.0f}-hour daily limit. Review before the shift is worked.", rules.daily_max)
    if assoc.rest_before_next_shift is not None and assoc.rest_before_next_shift < rules.min_rest_hours:
        add("critical", "REST_10", f"Only {assoc.rest_before_next_shift:.1f} hours of rest are scheduled before the next shift; minimum configured rest is {rules.min_rest_hours:.0f} hours.", rules.min_rest_hours)

    if assoc.projected_days >= 7:
        add("warning", "DAY_OFF_REVIEW", "Worked + scheduled dates cover all 7 days in the current workweek. Review the rolling seven-day day-off requirement.")

    if assoc.dot_regulated:
        if assoc.duty_hours_8d is not None:
            projected_8d = assoc.duty_hours_8d + assoc.next_shift_hours
            if projected_8d > rules.dot_max_duty_8d:
                add("critical", "DOT_70_8D", f"DOT 8-day duty projection is {projected_8d:.1f} hours, above {rules.dot_max_duty_8d:.0f} hours.", rules.dot_max_duty_8d)
        if assoc.drive_hours_next_shift is not None and assoc.drive_hours_next_shift > rules.dot_max_drive_after_rest:
            add("critical", "DOT_11_DRIVE", f"Planned driving time is {assoc.drive_hours_next_shift:.1f} hours, above the configured {rules.dot_max_drive_after_rest:.0f}-hour driving limit after required rest.", rules.dot_max_drive_after_rest)
        if assoc.next_shift_hours > rules.dot_max_duty_window:
            add("critical", "DOT_14_WINDOW", f"Next DOT shift is {assoc.next_shift_hours:.1f} hours, above the configured {rules.dot_max_duty_window:.0f}-hour duty window.", rules.dot_max_duty_window)

    return alerts


def highest_severity(alerts: Iterable[Alert]) -> str:
    order = {"ok": 0, "watch": 1, "warning": 2, "critical": 3}
    best = "ok"
    for alert in alerts:
        if order.get(alert.severity, 0) > order[best]:
            best = alert.severity
    return best


def alert_fingerprint(alert: Alert, week_key: str) -> str:
    date_part = alert.crossing_date or "none"
    return f"{week_key}|{alert.employee_id}|{alert.code}|{date_part}"
