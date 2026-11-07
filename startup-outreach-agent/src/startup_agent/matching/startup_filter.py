"""Deterministic company-size targeting for small-startup opportunities."""

from dataclasses import dataclass
from enum import Enum
import re
from typing import Optional


class StartupEligibilityStatus(str, Enum):
    """Whether a company fits the configured small-startup boundary."""

    ELIGIBLE = "Eligible small startup"
    UNKNOWN = "Unknown company size"
    INELIGIBLE = "Outside small-startup target"


@dataclass(frozen=True)
class StartupEligibilityResult:
    """Explainable company-size targeting result."""

    status: StartupEligibilityStatus
    reason: str
    estimated_min_employees: Optional[int] = None
    estimated_max_employees: Optional[int] = None


class StartupEligibilityFilter:
    """Classify public employee-count labels without guessing missing data."""

    def __init__(self, max_employees: int = 200, allow_unknown: bool = False) -> None:
        self.max_employees = max_employees
        self.allow_unknown = allow_unknown

    @staticmethod
    def _parse_employee_count(value: Optional[str]) -> tuple[Optional[int], Optional[int]]:
        if not value or not value.strip():
            return None, None

        normalized = value.lower().replace(",", "").strip()
        numbers = [int(item) for item in re.findall(r"\d+", normalized)]
        if not numbers:
            return None, None

        if len(numbers) >= 2:
            return numbers[0], numbers[1]

        number = numbers[0]
        if "+" in normalized or any(token in normalized for token in ["over", "more than", "above"]):
            return number, None
        if any(token in normalized for token in ["under", "less than", "up to", "<"]):
            return 1, number
        return number, number

    def evaluate(self, employee_count: Optional[str]) -> StartupEligibilityResult:
        minimum, maximum = self._parse_employee_count(employee_count)

        if minimum is None:
            status = (
                StartupEligibilityStatus.ELIGIBLE
                if self.allow_unknown
                else StartupEligibilityStatus.UNKNOWN
            )
            return StartupEligibilityResult(
                status=status,
                reason="Company size is not publicly known; no small-startup assumption was made.",
            )

        if minimum > self.max_employees:
            return StartupEligibilityResult(
                status=StartupEligibilityStatus.INELIGIBLE,
                reason=(
                    f"Company has at least {minimum} employees, above the configured "
                    f"small-startup ceiling of {self.max_employees}."
                ),
                estimated_min_employees=minimum,
                estimated_max_employees=maximum,
            )

        if maximum is None:
            return StartupEligibilityResult(
                status=StartupEligibilityStatus.UNKNOWN,
                reason=(
                    f"Company size is listed as {minimum}+ employees, so it cannot be "
                    "confirmed below the small-startup ceiling."
                ),
                estimated_min_employees=minimum,
            )

        if maximum <= self.max_employees:
            return StartupEligibilityResult(
                status=StartupEligibilityStatus.ELIGIBLE,
                reason=(
                    f"Published company size ({minimum}-{maximum}) is within the configured "
                    f"ceiling of {self.max_employees}."
                ),
                estimated_min_employees=minimum,
                estimated_max_employees=maximum,
            )

        return StartupEligibilityResult(
            status=StartupEligibilityStatus.UNKNOWN,
            reason=(
                f"Published size band ({minimum}-{maximum}) crosses the configured "
                f"small-startup ceiling of {self.max_employees}."
            ),
            estimated_min_employees=minimum,
            estimated_max_employees=maximum,
        )
