"""Internship and candidate eligibility evaluation engine."""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import List, Optional, Tuple

from startup_agent.matching.classifier import JobCategory, OpportunityType
from startup_agent.matching.profile import CandidateProfile


class EligibilityStatus(str, Enum):
    """Eligibility classification statuses."""

    ELIGIBLE = "Eligible"
    POTENTIALLY_ELIGIBLE = "Potentially Eligible"
    INSUFFICIENT_INFO = "Insufficient Information"
    INELIGIBLE = "Ineligible"


@dataclass
class EligibilityResult:
    """Outcome of eligibility evaluation."""

    status: EligibilityStatus
    reasons: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)
    work_auth_warning: Optional[str] = None


class EligibilityFilter:
    """Evaluates applicant eligibility against opportunity constraints."""

    def __init__(self, profile: CandidateProfile) -> None:
        self.profile = profile

    def _evaluate_degree_requirements(
        self,
        title: str,
        description: Optional[str],
    ) -> Tuple[Optional[EligibilityStatus], List[str], List[str]]:
        """Evaluate degree constraints (PhD, Master's, Bachelor's) against candidate profile.

        Returns:
            Tuple of (overriding_status, reasons, flags).
            overriding_status is None if degree criteria don't force Ineligible or Insufficient Info.
        """
        reasons: List[str] = []
        flags: List[str] = []

        title_lower = title.strip().lower()
        desc_lower = (description or "").strip().lower()
        desc_available = len(desc_lower) >= 80

        # Check title for degree specifications
        is_phd_in_title = bool(re.search(r"\bph\.?d\b", title_lower))
        is_masters_in_title = bool(re.search(r"\b(?:master'?s|ms)\s+intern\b", title_lower))

        # 1. PhD in Title handling. The product deliberately excludes
        # doctoral-targeted roles even when ATS details are incomplete.
        if is_phd_in_title:
            if not desc_available:
                flags.append("Role title specifies PhD Intern, but job description is unavailable in ATS.")
                return (
                    EligibilityStatus.INELIGIBLE,
                    [
                        "Role title explicitly targets PhD candidates; doctoral roles are outside the configured undergraduate/fresher scope."
                    ],
                    flags,
                )

            # Description is available: check if PhD is strictly required vs preferred
            phd_required_patterns = [
                r"\b(?:must be|currently)\s*(?:enrolled in|pursuing)\s+(?:a\s+)?ph\.?d\b",
                r"\bph\.?d\s+(?:required|is required|degree required|candidates? only|students? only)\b",
                r"\brequires?\s+(?:a\s+)?ph\.?d\b",
                r"\bph\.?d\s+program\b",
            ]
            phd_preferred_patterns = [
                r"\bph\.?d\s+(?:preferred|is a plus|desired|bonus)\b",
                r"\b(?:preferred|plus|bonus)\s*:\s*(?:a\s+)?ph\.?d\b",
                r"\b(?:ms|master'?s|ph\.?d)\s+(?:degree\s+)?preferred\b",
            ]
            if any(re.search(p, desc_lower) for p in phd_required_patterns):
                return (
                    EligibilityStatus.INELIGIBLE,
                    ["Position strictly requires PhD enrollment or degree; candidate is currently an undergraduate student (B.Tech)."],
                    flags,
                )
            elif any(re.search(p, desc_lower) for p in phd_preferred_patterns):
                flags.append("PhD degree is preferred in requirements; undergraduate applicant faces competitive disadvantage.")
            else:
                # Title says PhD, description doesn't explicitly soften it -> PhD mandatory
                return (
                    EligibilityStatus.INELIGIBLE,
                    ["Position title designates a PhD-level role; candidate is currently an undergraduate student (B.Tech)."],
                    flags,
                )

        # 2. Master's in Title handling
        if is_masters_in_title:
            if not desc_available:
                flags.append("Role title specifies Master's Intern, but job description is unavailable in ATS.")
                return (
                    EligibilityStatus.INSUFFICIENT_INFO,
                    ["Role title specifies Master's Intern, but detailed requirements are unavailable in ATS."],
                    flags,
                )
            return (
                EligibilityStatus.INELIGIBLE,
                ["Position strictly requires Master's/MS enrollment; candidate is currently an undergraduate student (B.Tech)."],
                flags,
            )

        # 3. Description-based degree requirements (when title does not specify degree)
        if desc_available:
            # Check mandatory PhD in description
            phd_req = [
                r"\b(?:must be|currently)\s*(?:enrolled in|pursuing)\s+(?:a\s+)?ph\.?d\b",
                r"\bph\.?d\s+(?:required|is required|degree required)\b",
                r"\bph\.?d\s+students?\s+only\b",
                r"\brequires?\s+(?:a\s+)?ph\.?d\b",
            ]
            if any(re.search(p, desc_lower) for p in phd_req):
                return (
                    EligibilityStatus.INELIGIBLE,
                    ["Job description specifies mandatory PhD requirement; candidate is currently an undergraduate student (B.Tech)."],
                    flags,
                )

            # Check preferred PhD in description
            phd_pref = [
                r"\bph\.?d\s+(?:preferred|is a plus|desired|bonus)\b",
                r"\b(?:preferred|plus|bonus)\s*:\s*(?:a\s+)?ph\.?d\b",
            ]
            if any(re.search(p, desc_lower) for p in phd_pref):
                flags.append("PhD degree preferred in job requirements; doctoral candidates prioritized.")

            # Check mandatory Master's in description
            masters_req = [
                r"\b(?:must be|currently)\s*(?:enrolled in|pursuing)\s+(?:a\s+)?(?:master'?s|ms|m\.tech)\b",
                r"\b(?:master'?s|ms|m\.tech)\s+(?:required|degree required)\b",
                r"\b(?:master'?s|ms)\s+students?\s+only\b",
                r"\brequires?\s+(?:a\s+)?(?:master'?s|ms|m\.tech)\b",
            ]
            if any(re.search(p, desc_lower) for p in masters_req):
                return (
                    EligibilityStatus.INELIGIBLE,
                    ["Job description specifies mandatory Master's/MS requirement; candidate is currently pursuing Bachelor's (B.Tech)."],
                    flags,
                )

            # Check preferred Master's in description
            masters_pref = [
                r"\b(?:master'?s|ms|m\.tech)\s+(?:preferred|is a plus|desired)\b",
            ]
            if any(re.search(p, desc_lower) for p in masters_pref):
                flags.append("Master's degree preferred in job requirements.")

            # Check undergraduate / Bachelor's explicitly accepted
            undergrad_acc = [
                r"\b(?:pursuing|enrolled in|currently pursuing)\s+(?:a\s+)?(?:bachelor'?s|bs|b\.tech|undergraduate)\b",
                r"\b(?:bachelor'?s|bs|b\.tech|undergraduate)\s+students?\b",
                r"\bopen to\s+(?:bachelor'?s|undergraduates?)\b",
            ]
            if any(re.search(p, desc_lower) for p in undergrad_acc):
                reasons.append("Undergraduate/Bachelor's students explicitly accepted.")

        return (None, reasons, flags)

    def evaluate(
        self,
        title: str,
        category: str,
        opportunity_type: OpportunityType,
        description: Optional[str] = None,
        location: Optional[str] = None,
        employment_type: Optional[str] = None,
        experience_level: Optional[str] = None,
    ) -> EligibilityResult:
        """Evaluate applicant eligibility for an opportunity.

        Args:
            title: Job title string.
            category: Job category from JobClassifier.
            opportunity_type: Evaluated OpportunityType.
            description: Full text description.
            location: Job location string.
            employment_type: Employment type metadata.
            experience_level: Stated experience level metadata.

        Returns:
            EligibilityResult: Categorized status with detailed reasons.
        """
        reasons: List[str] = []
        flags: List[str] = []
        work_auth_warning: Optional[str] = None

        full_text = f"{title} {description or ''} {experience_level or ''}".lower()

        # 1. Unrelated Role Check
        if category == JobCategory.UNRELATED:
            return EligibilityResult(
                status=EligibilityStatus.INELIGIBLE,
                reasons=["Role is classified as non-technical or outside target engineering domain."],
            )

        # 2. Strict Seniority Check
        if opportunity_type == OpportunityType.SENIOR_STAFF:
            return EligibilityResult(
                status=EligibilityStatus.INELIGIBLE,
                reasons=["Position is Senior, Lead, Staff, or requires substantial (>4 yrs) experience."],
            )

        if (
            self.profile.preferences.strict_fresher_only
            and opportunity_type == OpportunityType.OTHER_UNKNOWN
        ):
            return EligibilityResult(
                status=EligibilityStatus.INELIGIBLE,
                reasons=[
                    "Role is not explicitly identified as an internship, fresher, graduate, entry-level, or junior opportunity."
                ],
            )

        # Check explicit experience requirements in metadata and description.
        max_years = self.profile.preferences.max_required_experience_years
        range_match = re.search(r"(\d+)\s*(?:-|to)\s*(\d+)\s*years?", full_text, re.IGNORECASE)
        if range_match:
            min_yrs = int(range_match.group(1))
            if min_yrs > max_years:
                return EligibilityResult(
                    status=EligibilityStatus.INELIGIBLE,
                    reasons=[f"Explicit minimum experience requirement of {min_yrs} years exceeds the configured fresher ceiling of {max_years}."],
                )
            elif min_yrs == max_years:
                flags.append(f"Position specifies {experience_level} experience; student applicant will need strong justification.")
        else:
            exp_match = re.search(r"(\d+)\+?\s*years?", full_text, re.IGNORECASE)
            if exp_match:
                years = int(exp_match.group(1))
                if years > max_years:
                    return EligibilityResult(
                        status=EligibilityStatus.INELIGIBLE,
                        reasons=[f"Explicit experience requirement of {years}+ years exceeds the configured fresher ceiling of {max_years}."],
                    )
                elif years == max_years:
                    flags.append(f"Position asks for {years}+ years experience; student applicant will need strong justification.")

        # 3. Location and Work Authorization Evaluation
        loc_str = (location or "").lower()
        is_remote = any(kw in loc_str for kw in ["remote", "anywhere", "virtual", "wfh"])
        is_india = any(kw in loc_str for kw in ["india", "gurgaon", "delhi", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "noida"])

        # Check if remote has geographic restrictions
        us_only_remote = any(kw in loc_str for kw in ["us remote", "united states - remote", "us/canada", "us only"])
        if is_remote and us_only_remote:
            work_auth_warning = "Remote is geographically restricted (US/Canada). May require local authorization or US entity."
            flags.append(work_auth_warning)
        elif is_remote:
            reasons.append("Work arrangement is flexible remote.")
        elif is_india:
            reasons.append(f"Domestic preferred location ({location}).")
        elif not location or location.strip() == "":
            flags.append("Location metadata is unlisted or missing.")
        else:
            work_auth_warning = f"On-site/hybrid role located in '{location}'. Does not assume visa sponsorship."
            flags.append(work_auth_warning)

        # 4. Degree-Specific Eligibility Evaluation
        degree_status, degree_reasons, degree_flags = self._evaluate_degree_requirements(title, description)
        reasons.extend(degree_reasons)
        flags.extend(degree_flags)
        if degree_status is not None:
            return EligibilityResult(
                status=degree_status,
                reasons=reasons,
                flags=flags,
                work_auth_warning=work_auth_warning,
            )

        # 5. Description Completeness Check
        desc_len = len((description or "").strip())
        if desc_len < 80:
            flags.append("Job description is minimal or absent; technical matching is low-confidence.")
            if opportunity_type in (OpportunityType.INTERNSHIP, OpportunityType.COOP_STUDENT):
                return EligibilityResult(
                    status=EligibilityStatus.POTENTIALLY_ELIGIBLE,
                    reasons=reasons + ["Designated as student internship, but lacks detailed requirements text."],
                    flags=flags,
                    work_auth_warning=work_auth_warning,
                )
            return EligibilityResult(
                status=EligibilityStatus.INSUFFICIENT_INFO,
                reasons=reasons + ["Insufficient job specification to determine student eligibility."],
                flags=flags,
                work_auth_warning=work_auth_warning,
            )

        # 5. Opportunity Type Eligibility Synthesis
        if opportunity_type in (OpportunityType.INTERNSHIP, OpportunityType.COOP_STUDENT):
            reasons.append(f"Opportunity explicitly designated as {opportunity_type.value}.")
            if is_india or (is_remote and not us_only_remote):
                return EligibilityResult(
                    status=EligibilityStatus.ELIGIBLE,
                    reasons=reasons,
                    flags=flags,
                    work_auth_warning=work_auth_warning,
                )
            # International or US-restricted intern
            return EligibilityResult(
                status=EligibilityStatus.POTENTIALLY_ELIGIBLE,
                reasons=reasons + ["Student internship confirmed, but location requires checking work eligibility."],
                flags=flags,
                work_auth_warning=work_auth_warning,
            )

        if opportunity_type == OpportunityType.GRADUATE_ENTRY_LEVEL:
            reasons.append("Graduate / entry-level full-time opportunity.")
            return EligibilityResult(
                status=EligibilityStatus.POTENTIALLY_ELIGIBLE,
                reasons=reasons + ["Suitable for 2028 graduating placement or internship negotiation."],
                flags=flags,
                work_auth_warning=work_auth_warning,
            )

        if opportunity_type == OpportunityType.REGULAR_FULL_TIME:
            if self.profile.preferences.strict_fresher_only:
                return EligibilityResult(
                    status=EligibilityStatus.INELIGIBLE,
                    reasons=[
                        "Regular full-time role is not explicitly marked as internship, fresher, graduate, entry-level, or junior."
                    ],
                    flags=flags,
                    work_auth_warning=work_auth_warning,
                )
            reasons.append("Regular full-time position (not an internship).")
            return EligibilityResult(
                status=EligibilityStatus.POTENTIALLY_ELIGIBLE,
                reasons=reasons + ["Regular full-time role; suitable only for speculative internship enquiry or future placement."],
                flags=flags,
                work_auth_warning=work_auth_warning,
            )

        return EligibilityResult(
            status=EligibilityStatus.INSUFFICIENT_INFO,
            reasons=reasons + ["Unclassified opportunity type."],
            flags=flags,
            work_auth_warning=work_auth_warning,
        )
