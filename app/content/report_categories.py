"""Tenant hazard report categories, modeled on how Boston 311 routes housing requests.

`severity` is used by the ranking service (Task 8). `fire_category` links each report to the
same categories used for Boston's official records.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportCategory:
    id: str
    label: str
    hint: str
    severity: int  # 5 = most serious
    fire_category: str
    department: str  # who would handle it, 311-style


REPORT_CATEGORIES: dict[str, ReportCategory] = {
    c.id: c
    for c in [
        ReportCategory(
            id="no_second_exit",
            label="No second way out",
            hint="A bedroom or unit has only one way out, or a window is too small, painted, or nailed shut.",
            severity=5,
            fire_category="egress",
            department="Housing inspections",
        ),
        ReportCategory(
            id="smoke_alarm",
            label="Missing or broken smoke or carbon monoxide alarm",
            hint="An alarm is missing, removed, beeping, or doesn't work.",
            severity=5,
            fire_category="smoke_alarms",
            department="Housing inspections",
        ),
        ReportCategory(
            id="blocked_exit",
            label="Blocked exit or stairway",
            hint="A hallway, stairway, fire escape, or exit door is blocked or locked.",
            severity=4,
            fire_category="egress",
            department="Housing inspections",
        ),
        ReportCategory(
            id="electrical_hazard",
            label="Electrical hazard",
            hint="Exposed wiring, sparking outlets, breakers that keep tripping, or too few outlets.",
            severity=4,
            fire_category="electrical",
            department="Building inspections",
        ),
        ReportCategory(
            id="heating_hazard",
            label="Heating problem",
            hint="No heat, heat that doesn't reach every room, or the landlord supplies space heaters instead.",
            severity=3,
            fire_category="heating",
            department="Housing inspections",
        ),
        ReportCategory(
            id="other",
            label="Other fire-safety problem",
            hint="Anything else that makes a fire more likely or harder to escape.",
            severity=1,
            fire_category="other",
            department="Housing inspections",
        ),
    ]
}

BOSTON_311_URL = "https://311.boston.gov"
BOSTON_ISD_URL = "https://www.boston.gov/departments/inspectional-services"
