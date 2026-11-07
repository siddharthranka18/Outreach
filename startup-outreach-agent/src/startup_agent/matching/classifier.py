"""Job and opportunity classification into standardized technical domains and employment types."""

from enum import Enum
import re
from typing import Optional


class OpportunityType(str, Enum):
    """Classification of employment commitment and candidate seniority level."""

    INTERNSHIP = "Internship"
    COOP_STUDENT = "Co-op / Student Placement"
    GRADUATE_ENTRY_LEVEL = "Graduate / Entry-Level Full-Time"
    REGULAR_FULL_TIME = "Regular Full-Time"
    SENIOR_STAFF = "Senior / Lead / Staff"
    OTHER_UNKNOWN = "Other / Unknown"


class JobCategory:
    """Standardized technical role families."""

    SOFTWARE_DEV = "Software Development"
    BACKEND = "Backend Engineering"
    FRONTEND = "Frontend Engineering"
    FULL_STACK = "Full Stack Engineering"
    AI_ML = "AI/ML Engineering"
    DATA_SCIENCE = "Data Science"
    DATA_ENGINEERING = "Data Engineering"
    GENERAL_SWE = "General Software Engineering"
    UNRELATED = "Unrelated or Unsuitable"

    # Backward-compatibility aliases for earlier test suites
    SOFTWARE_DEV_INTERN = "Software Development Intern"
    BACKEND_INTERN = "Backend Intern"
    FRONTEND_INTERN = "Frontend Intern"
    FULL_STACK_INTERN = "Full Stack Intern"
    AI_ML_INTERN = "AI/ML Intern"
    DATA_SCIENCE_INTERN = "Data Science Intern"
    DATA_ENG_INTERN = "Data Engineering Intern"


# Keywords strictly denoting student or internship roles
INTERN_PATTERNS = [
    r"\bintern\b",
    r"\binternship\b",
    r"\bco-?op\b",
    r"\bstudent\b",
    r"\btrainee\b",
    r"\bapprentice\b",
]

# Keywords denoting graduate or entry-level positions
GRADUATE_ENTRY_PATTERNS = [
    r"\bgraduate\b",
    r"\bnew grad\b",
    r"\bcollege grad\b",
    r"\bcampus hire\b",
    r"\bentry[- ]level\b",
    r"\bfresher\b",
    r"\bassociate\b",
    r"\bjunior\b",
    r"\bjr\.?\b",
]

# Keywords denoting senior or leadership seniority
SENIOR_PATTERNS = [
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
    r"\bfellow\b",
    r"\bdistinguished\b",
    r"\b[5-9]\+?\s*years?\b",
    r"\b10\+?\s*years?\b",
]

# Regex patterns for explicitly non-engineering or excluded professions
EXCLUDED_ROLES = [
    r"\bsales\b",
    r"\baccount executive\b",
    r"\bmarketing\b",
    r"\bmarketer\b",
    r"\bdemand gen\b",
    r"\bgrowth\b",
    r"\brecruiter\b",
    r"\btalent\b",
    r"\bhr\b",
    r"\bhuman resources\b",
    r"\bpeople partner\b",
    r"\bteacher\b",
    r"\bpreschool\b",
    r"\bdaycare\b",
    r"\blegal\b",
    r"\bcounsel\b",
    r"\battorney\b",
    r"\boperations manager\b",
    r"\bfinance\b",
    r"\baccounting\b",
    r"\bcompliance\b",
    r"\bcustomer success\b",
    r"\bcustomer support\b",
    r"\bevents manager\b",
    r"\boffice manager\b",
    r"\bdesigner\b",
    r"\bproduct designer\b",
    r"\bmotion designer\b",
    r"\bvideo editor\b",
    r"\bconsultant\b",
    r"\binsights consultant\b",
    r"\bsolutions associate\b",
    r"\bimplementation consultant\b",
    r"\btechnical account manager\b",
    r"\bcustomer engineer\b",
    r"\bcontent creator\b",
    r"\bcreator internship\b",
    r"\bsocial media creator\b",
    r"\binfluencer\b",
    r"\bcopywriter\b",
    r"\bmechanical engineer(?:ing)?\b",
    r"\belectrical engineer(?:ing)?\b",
    r"\bcivil engineer(?:ing)?\b",
    r"\bchemical engineer(?:ing)?\b",
    r"\bhardware engineer(?:ing)?\b",
]


# Patterns identifying ambiguous engineering titles that may or may not be software development
AMBIGUOUS_TECH_PATTERNS = [
    r"\bgtm\b",
    r"\bgo-?to-?market\b",
    r"\bsales engineer",
    r"\bsolutions engineer",
    r"\brevops\b",
    r"\brevenue operations\b",
    r"\bpre-?sales\b",
    r"\bcrm engineer\b",
]


class JobClassifier:
    """Classifies opportunities into distinct OpportunityType and technical JobCategory."""

    def is_unrelated(self, title: str) -> bool:
        """Check if the title indicates a non-technical or excluded profession."""
        title_lower = title.strip().lower()
        # If it is an ambiguous engineering title (e.g., Sales Engineer, GTM Engineer),
        # do not summarily exclude it here; allow description evaluation to determine.
        if self.is_ambiguous_engineering(title):
            return False
        return any(re.search(pat, title_lower) for pat in EXCLUDED_ROLES)

    def is_ambiguous_engineering(self, title: str) -> bool:
        """Check if the title is an ambiguous technical/engineering title (e.g. GTM, Sales Engineer)."""
        title_lower = title.strip().lower()
        return any(re.search(pat, title_lower) for pat in AMBIGUOUS_TECH_PATTERNS)

    def has_software_engineering_responsibilities(self, description: Optional[str]) -> bool:
        """Evaluate whether an ambiguous title actually involves core software engineering responsibilities."""
        if not description or len(description.strip()) < 80:
            return False
        desc_lower = description.lower()

        swe_indicators = [
            r"\bsoftware engineering\b",
            r"\bshipping code\b",
            r"\bwrite code\b",
            r"\bwrote code\b",
            r"\bwriting code\b",
            r"\bcodebase\b",
            r"\bproduction systems?\b",
            r"\bbackend services?\b",
            r"\bdata pipelines?\b",
            r"\b(?:build|develop|architect)\s+(?:apis?|microservices?|web applications?|systems?|applications?|infrastructure|tools)\b",
            r"\b(?:python|javascript|typescript|golang|rust|c\+\+|java)\b",
            r"\b(?:llms?|rag|vector database|microservices|distributed systems)\b",
        ]
        matches = sum(1 for pat in swe_indicators if re.search(pat, desc_lower))
        return matches >= 2

    def determine_opportunity_type(
        self,
        title: str,
        employment_type: Optional[str] = None,
        experience_level: Optional[str] = None,
        description: Optional[str] = None,
    ) -> OpportunityType:
        """Determine whether the role is an internship, graduate role, full-time, or senior.

        Rules:
            1. Senior/Lead patterns take precedence -> SENIOR_STAFF.
            2. Explicit intern / internship patterns -> INTERNSHIP.
            3. Co-op / student placement patterns -> COOP_STUDENT.
            4. Ambiguous engineering titles without SWE evidence -> OTHER_UNKNOWN.
            5. Graduate / Entry-level / Fresher / Junior patterns -> GRADUATE_ENTRY_LEVEL.
            6. Standard full-time or stated 2+ years without senior title -> REGULAR_FULL_TIME.
            7. Fallback -> OTHER_UNKNOWN.
        """
        combined = f"{title} {employment_type or ''} {experience_level or ''}".lower()

        # 1. Seniority Check
        for pat in SENIOR_PATTERNS:
            if re.search(pat, title.lower()):
                return OpportunityType.SENIOR_STAFF
            if experience_level and re.search(pat, experience_level.lower()):
                return OpportunityType.SENIOR_STAFF

        # 2. Explicit Co-op
        if re.search(r"\bco-?op\b", combined) or "student placement" in combined:
            return OpportunityType.COOP_STUDENT

        # 3. Explicit Internship
        if any(re.search(pat, combined) for pat in INTERN_PATTERNS):
            return OpportunityType.INTERNSHIP

        # 4. Ambiguous Engineering Check (GTM, Sales Engineer, RevOps)
        if self.is_ambiguous_engineering(title):
            if not self.has_software_engineering_responsibilities(description):
                return OpportunityType.OTHER_UNKNOWN

        # 5. Graduate / Entry Level
        if any(re.search(pat, combined) for pat in GRADUATE_ENTRY_PATTERNS):
            return OpportunityType.GRADUATE_ENTRY_LEVEL

        # 6. Regular Full Time
        if employment_type and "full" in employment_type.lower():
            return OpportunityType.REGULAR_FULL_TIME

        if any(kw in title.lower() for kw in ["engineer", "developer", "programmer", "architect", "scientist"]):
            return OpportunityType.REGULAR_FULL_TIME

        return OpportunityType.OTHER_UNKNOWN

    def classify_category(
        self,
        title: str,
        description: Optional[str] = None,
    ) -> str:
        """Classify the technical role family (e.g., Backend, AI/ML, Full Stack)."""
        title_lower = title.strip().lower()

        if self.is_unrelated(title):
            return JobCategory.UNRELATED

        # Domain words such as "AI" do not make a commercial/operations title
        # a software role. Require an explicit build/research/student signal.
        core_technical_title = bool(
            re.search(
                r"\b(engineer(?:ing)?|developer|programmer|software|backend|back-end|frontend|front-end|full[ -]?stack|"
                r"data scientist|data engineer|machine learning|ml engineer|research scientist|computer vision|"
                r"devops|site reliability|sre|intern|internship|co-?op|apprentice)\b",
                title_lower,
            )
        )
        if not core_technical_title:
            return JobCategory.UNRELATED

        # Handle ambiguous engineering titles (e.g. GTM Engineer, Sales Engineer)
        if self.is_ambiguous_engineering(title):
            if not self.has_software_engineering_responsibilities(description):
                return JobCategory.UNRELATED
            # Genuinely technical GTM role with verified SWE responsibilities
            desc_lower = (description or "").lower()
            if any(kw in desc_lower for kw in ["ai", "ml", "machine learning", "llm", "rag", "agents"]):
                return JobCategory.AI_ML
            if any(kw in desc_lower for kw in ["backend", "server", "distributed system"]):
                return JobCategory.BACKEND
            if any(kw in desc_lower for kw in ["full stack", "fullstack"]):
                return JobCategory.FULL_STACK
            return JobCategory.SOFTWARE_DEV

        if any(kw in title_lower for kw in ["ai", "ml", "machine learning", "deep learning", "nlp", "computer vision", "llm"]):
            return JobCategory.AI_ML

        if any(kw in title_lower for kw in ["backend", "back-end", "back end", "server", "distributed system"]):
            return JobCategory.BACKEND

        if any(kw in title_lower for kw in ["frontend", "front-end", "front end", "ui engineer", "react"]):
            return JobCategory.FRONTEND

        if any(kw in title_lower for kw in ["full stack", "fullstack", "full-stack"]):
            return JobCategory.FULL_STACK

        if any(kw in title_lower for kw in ["data scientist", "data science", "data analyst", "analytics"]):
            return JobCategory.DATA_SCIENCE

        if any(kw in title_lower for kw in ["data engineer", "etl", "data pipeline"]):
            return JobCategory.DATA_ENGINEERING

        if any(kw in title_lower for kw in ["robotics", "robot", "autonomy", "embedded software"]):
            return JobCategory.SOFTWARE_DEV

        if any(kw in title_lower for kw in ["software", "sde", "developer", "engineer", "programmer", "systems"]):
            return JobCategory.SOFTWARE_DEV

        return JobCategory.UNRELATED

    def classify(
        self,
        title: str,
        description: Optional[str] = None,
        employment_type: Optional[str] = None,
    ) -> str:
        """Backward-compatible classification method returning specific or composite categories."""
        if self.is_unrelated(title):
            return JobCategory.UNRELATED

        opp_type = self.determine_opportunity_type(
            title=title,
            employment_type=employment_type,
            description=description,
        )
        cat = self.classify_category(title, description)

        if cat == JobCategory.UNRELATED:
            return JobCategory.UNRELATED

        is_intern = opp_type in (OpportunityType.INTERNSHIP, OpportunityType.COOP_STUDENT)

        if is_intern:
            if cat == JobCategory.AI_ML:
                return JobCategory.AI_ML_INTERN
            if cat == JobCategory.BACKEND:
                return JobCategory.BACKEND_INTERN
            if cat == JobCategory.FRONTEND:
                return JobCategory.FRONTEND_INTERN
            if cat == JobCategory.FULL_STACK:
                return JobCategory.FULL_STACK_INTERN
            if cat == JobCategory.DATA_SCIENCE:
                return JobCategory.DATA_SCIENCE_INTERN
            if cat == JobCategory.DATA_ENGINEERING:
                return JobCategory.DATA_ENG_INTERN
            return JobCategory.SOFTWARE_DEV_INTERN

        return JobCategory.GENERAL_SWE
