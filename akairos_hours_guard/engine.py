from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
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
    next_shift_hours: float = 0.0
    max_daily_hours: float = 0.0
    rest_before_next_shift: Optional[float] = None
    dot_regulated: bool = False
    duty_hours_8d: Optional[float] = None
    drive_hours_next_shift: Optional[float] = None
    missing_punch: bool = False
    manager: str = ""
    phone: str = ""
    email: str = ""

    @property
    def projected_hours(self) -> float:
        return round(float(self.actual_hours) + float(self.scheduled_remaining_hours), 2)


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

    def to_dict(self):
        return asdict(self)


def evaluate(assoc: AssociateWeek, rules: Rules | None = None) -> list[Alert]:
    rules = rules or Rules()
    alerts: list[Alert] = []
    projected = assoc.projected_hours

    def add(severity: str, code: str, message: str, threshold: float | None = None):
        alerts.append(Alert(
            employee_id=assoc.employee_id,
            name=assoc.name,
            station=assoc.station,
            severity=severity,
            code=code,
            message=message,
            actual_hours=round(assoc.actual_hours, 2),
            projected_hours=projected,
            threshold=threshold,
        ))

    if assoc.missing_punch:
        add(
            "critical",
            "MISSING_PUNCH",
            "Missing/incomplete punch data detected. Review timekeeping before relying on projected hours.",
        )

    if projected >= rules.amazon_weekly_max:
        add(
            "critical",
            "WEEKLY_60_LIMIT",
            f"Projected weekly hours are {projected:.1f}, at/above the {rules.amazon_weekly_max:.0f}-hour rolling weekly policy limit.",
            rules.amazon_weekly_max,
        )
    elif projected >= rules.critical_50 - rules.lead_hours:
        if projected >= rules.critical_50:
            add("critical", "CRITICAL_50", f"Projected weekly hours are {projected:.1f}, at/above the AKAIROS {rules.critical_50:.0f}-hour critical threshold.", rules.critical_50)
        else:
            add("critical", "APPROACHING_50", f"Projected weekly hours are {projected:.1f}; associate is within {rules.lead_hours:.1f} hours of the {rules.critical_50:.0f}-hour critical threshold.", rules.critical_50)
    elif projected >= rules.overtime_40 - rules.lead_hours:
        if projected >= rules.overtime_40:
            add("warning", "OVERTIME_40", f"Projected weekly hours are {projected:.1f}, at/above the {rules.overtime_40:.0f}-hour overtime threshold. Review remaining schedule and overtime authorization.", rules.overtime_40)
        else:
            add("warning", "APPROACHING_40", f"Projected weekly hours are {projected:.1f}; associate is within {rules.lead_hours:.1f} hours of the {rules.overtime_40:.0f}-hour overtime threshold.", rules.overtime_40)
    elif projected >= rules.watch_30 - rules.lead_hours:
        if projected >= rules.watch_30:
            add("watch", "WATCH_30", f"Projected weekly hours are {projected:.1f}, at/above the {rules.watch_30:.0f}-hour planning/benefit-status watch threshold.", rules.watch_30)
        else:
            add("watch", "APPROACHING_30", f"Projected weekly hours are {projected:.1f}; associate is within {rules.lead_hours:.1f} hours of the {rules.watch_30:.0f}-hour watch threshold.", rules.watch_30)

    if assoc.max_daily_hours > rules.daily_max:
        add("critical", "DAILY_MAX", f"A workday reached {assoc.max_daily_hours:.1f} hours, above the {rules.daily_max:.0f}-hour daily policy limit.", rules.daily_max)
    if assoc.rest_before_next_shift is not None and assoc.rest_before_next_shift < rules.min_rest_hours:
        add("critical", "REST_10", f"Only {assoc.rest_before_next_shift:.1f} hours of rest are scheduled before the next shift; minimum configured rest is {rules.min_rest_hours:.0f} hours.", rules.min_rest_hours)

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
    return f"{week_key}|{alert.employee_id}|{alert.code}"
