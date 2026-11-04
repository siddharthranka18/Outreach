"""Job classification into technical and internship categories."""

import re
from typing import Optional


class JobCategory:
    """Standardized classification categories."""

    SOFTWARE_DEV_INTERN = "Software Development Intern"
    BACKEND_INTERN = "Backend Intern"
    FRONTEND_INTERN = "Frontend Intern"
    FULL_STACK_INTERN = "Full Stack Intern"
    AI_ML_INTERN = "AI/ML Intern"
    DATA_SCIENCE_INTERN = "Data Science Intern"
    DATA_ENG_INTERN = "Data Engineering Intern"
    GENERAL_SWE = "General Software Engineering"
    UNRELATED = "Unrelated or Unsuitable"


# Regex patterns identifying internship and trainee designations
INTERN_INDICATORS = [
    r"\bintern\b",
    r"\binternship\b",
    r"\bco-?op\b",
    r"\bstudent\b",
    r"\btrainee\b",
    r"\bapprentice\b",
    r"\bfresher\b",
]

# Regex patterns for non-engineering / completely unrelated professions
EXCLUDED_ROLES = [
    r"\bsales\b",
    r"\baccount executive\b",
    r"\bmarketing\b",
    r"\brecruiter\b",
    r"\btalent\b",
    r"\bhr\b",
    r"\bhuman resources\b",
    r"\bteacher\b",
    r"\bpreschool\b",
    r"\bdaycare\b",
    r"\blegal\b",
    r"\boperations manager\b",
    r"\bfinance\b",
    r"\bcompliance\b",
    r"\bcustomer success\b",
    r"\bevents manager\b",
    r"\boffice manager\b",
]


class JobClassifier:
    """Rule-based, deterministic classifier for job titles and descriptions."""

    def is_internship(self, title: str, employment_type: Optional[str] = None) -> bool:
        """Determine whether the posting is an internship role."""
        if employment_type and "intern" in employment_type.lower():
            return True
        title_lower = title.lower()
        return any(re.search(pat, title_lower) for pat in INTERN_INDICATORS)

    def is_unrelated(self, title: str) -> bool:
        """Check if the title indicates a non-technical or excluded profession."""
        title_lower = title.lower()
        return any(re.search(pat, title_lower) for pat in EXCLUDED_ROLES)

    def classify(self, title: str, description: Optional[str] = None, employment_type: Optional[str] = None) -> str:
        """Classify a job into a specific target category.

        Args:
            title: Raw job title.
            description: Optional job description text.
            employment_type: Optional employment type string (e.g. 'Internship', 'Full-time').

        Returns:
            str: One of the standard JobCategory values.
        """
        title_lower = title.strip().lower()
        desc_lower = (description or "").lower()

        # Check for explicitly unrelated positions first
        if self.is_unrelated(title):
            return JobCategory.UNRELATED

        is_intern = self.is_internship(title, employment_type)

        # AI / ML Signals
        if any(kw in title_lower for kw in ["ai", "ml", "machine learning", "deep learning", "nlp", "computer vision", "llm"]):
            return JobCategory.AI_ML_INTERN if is_intern else JobCategory.GENERAL_SWE

        # Backend Signals
        if any(kw in title_lower for kw in ["backend", "back-end", "back end", "server", "distributed system"]):
            return JobCategory.BACKEND_INTERN if is_intern else JobCategory.GENERAL_SWE

        # Frontend Signals
        if any(kw in title_lower for kw in ["frontend", "front-end", "front end", "ui engineer", "react"]):
            return JobCategory.FRONTEND_INTERN if is_intern else JobCategory.GENERAL_SWE

        # Full Stack Signals
        if any(kw in title_lower for kw in ["full stack", "fullstack", "full-stack"]):
            return JobCategory.FULL_STACK_INTERN if is_intern else JobCategory.GENERAL_SWE

        # Data Science & Analytics
        if any(kw in title_lower for kw in ["data scientist", "data science", "data analyst", "analytics"]):
            return JobCategory.DATA_SCIENCE_INTERN if is_intern else JobCategory.GENERAL_SWE

        # Data Engineering
        if any(kw in title_lower for kw in ["data engineer", "etl", "data pipeline"]):
            return JobCategory.DATA_ENG_INTERN if is_intern else JobCategory.GENERAL_SWE

        # General Software Engineering & Development
        if any(kw in title_lower for kw in ["software", "sde", "developer", "engineer", "programmer", "systems"]):
            return JobCategory.SOFTWARE_DEV_INTERN if is_intern else JobCategory.GENERAL_SWE

        # If it's an internship with generic title
        if is_intern:
            return JobCategory.SOFTWARE_DEV_INTERN

        # Fallback check on description
        if any(kw in desc_lower for kw in ["python", "javascript", "software", "api", "backend", "machine learning"]):
            return JobCategory.GENERAL_SWE

        return JobCategory.UNRELATED

