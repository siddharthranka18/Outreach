"""Internship and early-career candidate eligibility filtering."""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import List, Optional

from startup_agent.matching.classifier import JobCategory
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


# Seniority patterns that disqualify an early-career / student applicant
DISQUALIFYING_SENIORITY_PATTERNS = [
    r"\bsenior\b",
    r"\bsr\.?\b",
    r"\blead\b",
    r"\bstaff\b",
    r"\bprincipal\b",
    r"\bdirector\b",
    r"\bhead of\b",
    r"\bvp\b",
    r"\bvice president\b",
    r"\bmanager\b",
    r"\barchitect\b",
    r"\b10\+?\s*years?\b",
    r"\b[5-9]\+?\s*years?\b",
    r"\b[7-9]\s*years?\b",
]

# Experience indicators suitable for students / early-career
EARLY_CAREER_INDICATORS = [
    r"\bintern\b",
    r"\binternship\b",
    r"\bco-?op\b",
    r"\bstudent\b",
    r"\bfresher\b",
    r"\bgraduate\b",
    r"\bentry[- ]level\b",
    r"\b0-2\s*years?\b",
    r"\b1-2\s*years?\b",
    r"\bjunior\b",
    r"\bjr\.?\b",
]


class EligibilityFilter:
    """Evaluates candidate eligibility against job constraints and requirements."""

    def __init__(self, profile: CandidateProfile) -> None:
        self.profile = profile

    def evaluate(
        self,
        title: str,
        category: str,
        description: Optional[str] = None,
        location: Optional[str] = None,
        employment_type: Optional[str] = None,
        experience_level: Optional[str] = None,
    ) -> EligibilityResult:
        """Evaluate applicant eligibility for an opportunity.

        Args:
            title: Job title string.
            category: Job category from JobClassifier.
            description: Full text description.
            location: Job location string.
            employment_type: Employment type metadata.
            experience_level: Stated experience level metadata.

        Returns:
            EligibilityResult: Categorized status with detailed reasons.
        """
        reasons: List[str] = []
        flags: List[str] = []
        full_text = f"{title} {description or ''} {experience_level or ''}".lower()

        # 1. Unrelated Role Check
        if category == JobCategory.UNRELATED:
            return EligibilityResult(
                status=EligibilityStatus.INELIGIBLE,
                reasons=["Role is classified as non-technical or outside the target domain."],
            )

        # 2. Strict Seniority Check
        for pat in DISQUALIFYING_SENIORITY_PATTERNS:
            if re.search(pat, title.lower()):
                return EligibilityResult(
                    status=EligibilityStatus.INELIGIBLE,
                    reasons=[f"Title specifies senior requirement matching '{pat}'."],
                )
            if experience_level and re.search(pat, experience_level.lower()):
                return EligibilityResult(
                    status=EligibilityStatus.INELIGIBLE,
                    reasons=[f"Experience level specifies senior requirement matching '{pat}'."],
                )

        # 3. Check for Explicit Internship / Student Opportunity
        is_explicit_intern = False
        if "intern" in category.lower() or (employment_type and "intern" in employment_type.lower()):
            is_explicit_intern = True
            reasons.append("Posting explicitly designated as an internship/co-op.")
        elif any(re.search(pat, title.lower()) for pat in EARLY_CAREER_INDICATORS):
            is_explicit_intern = True
            reasons.append("Role title indicates student/internship opportunity.")

        # 4. Location and Work Arrangement Check
        loc_str = (location or "").lower()
        is_remote = any(kw in loc_str for kw in ["remote", "anywhere", "virtual", "wfh"])
        is_india = any(kw in loc_str for kw in ["india", "gurgaon", "delhi", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "noida"])

        if is_remote:
            reasons.append("Work arrangement is remote.")
        elif is_india:
            reasons.append("Location matches preferred domestic region (India).")
        elif not location or location.strip() == "":
            flags.append("Location metadata is missing or unlisted.")
        else:
            flags.append(f"On-site/hybrid location: '{location}'. May require work authorization or relocation.")

        # 5. Metadata Completeness Check
        if not description or len(description.strip()) < 50:
            flags.append("Job description is minimal or absent.")
            if is_explicit_intern:
                return EligibilityResult(
                    status=EligibilityStatus.POTENTIALLY_ELIGIBLE,
                    reasons=reasons + ["Designated as internship, but lacking detailed requirement text."],
                    flags=flags,
                )
            return EligibilityResult(
                status=EligibilityStatus.INSUFFICIENT_INFO,
                reasons=reasons + ["Insufficient job specification to determine student eligibility."],
                flags=flags,
            )

        # 6. Final Status Synthesis
        if is_explicit_intern:
            if is_remote or is_india:
                return EligibilityResult(
                    status=EligibilityStatus.ELIGIBLE,
                    reasons=reasons,
                    flags=flags,
                )
            return EligibilityResult(
                status=EligibilityStatus.POTENTIALLY_ELIGIBLE,
                reasons=reasons + ["Internship verified, but location may have geographic restrictions."],
                flags=flags,
            )

        # For General Software Engineering without explicit intern tag
        reasons.append("General software engineering opportunity (worth speculative enquiry or junior placement).")
        return EligibilityResult(
            status=EligibilityStatus.POTENTIALLY_ELIGIBLE,
            reasons=reasons,
            flags=flags,
        )

