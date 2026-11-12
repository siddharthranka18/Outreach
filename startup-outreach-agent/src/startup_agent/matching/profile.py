"""Candidate profile domain models and configuration loader."""

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml

from startup_agent.config.settings import Settings

logger = logging.getLogger("startup_agent.matching.profile")


@dataclass
class CandidateEducation:
    """Education background details."""

    degree: str
    institution: str
    location: str
    current_year: str
    expected_graduation: str
    cgpa: Optional[str] = None


@dataclass
class CandidateExperience:
    """Prior professional or internship experience."""

    role: str
    company: str
    duration: str
    highlights: List[str] = field(default_factory=list)


@dataclass
class CandidateProject:
    """Portfolio and technical projects."""

    title: str
    description: str
    technologies: List[str] = field(default_factory=list)
    outreach_roles: List[str] = field(default_factory=list)


@dataclass
class CandidateSkills:
    """Categorized technical and conceptual skills."""

    languages: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    databases: List[str] = field(default_factory=list)
    ai_ml: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    concepts: List[str] = field(default_factory=list)

    @property
    def all_skills(self) -> Set[str]:
        """Aggregate set of all skills lowercased."""
        combined = (
            self.languages
            + self.frameworks
            + self.databases
            + self.ai_ml
            + self.tools
            + self.concepts
        )
        return {s.strip().lower() for s in combined if s.strip()}


@dataclass
class CandidatePreferences:
    """Target roles, work arrangements, and geographic preferences."""

    target_roles: List[str] = field(default_factory=list)
    work_arrangements: List[str] = field(default_factory=list)
    preferred_locations: List[str] = field(default_factory=list)
    exclude_seniority: List[str] = field(default_factory=list)
    strict_fresher_only: bool = True
    max_required_experience_years: int = 2
    small_startup_max_employees: int = 200
    allow_unknown_company_size: bool = False


@dataclass
class CandidateProfile:
    """Complete candidate profile used by the matching engine."""

    name: str
    current_education: CandidateEducation
    skills: CandidateSkills
    experiences: List[CandidateExperience] = field(default_factory=list)
    projects: List[CandidateProject] = field(default_factory=list)
    preferences: CandidatePreferences = field(default_factory=CandidatePreferences)

    @property
    def all_skills(self) -> Set[str]:
        """Convenience property for aggregated skill tokens."""
        return self.skills.all_skills

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CandidateProfile":
        """Instantiate CandidateProfile from a parsed dictionary."""
        cand = data.get("candidate", data)
        edu_data = cand.get("current_education", {})
        education = CandidateEducation(
            degree=edu_data.get("degree", ""),
            institution=edu_data.get("institution", ""),
            location=edu_data.get("location", ""),
            current_year=edu_data.get("current_year", ""),
            expected_graduation=edu_data.get("expected_graduation", ""),
            cgpa=edu_data.get("cgpa"),
        )

        skills_data = cand.get("skills", {})
        skills = CandidateSkills(
            languages=skills_data.get("languages", []),
            frameworks=skills_data.get("frameworks", []),
            databases=skills_data.get("databases", []),
            ai_ml=skills_data.get("ai_ml", []),
            tools=skills_data.get("tools", []),
            concepts=skills_data.get("concepts", []),
        )

        experiences = [
            CandidateExperience(
                role=e.get("role", ""),
                company=e.get("company", ""),
                duration=e.get("duration", ""),
                highlights=e.get("highlights", []),
            )
            for e in cand.get("experiences", [])
        ]

        projects = [
            CandidateProject(
                title=p.get("title", ""),
                description=p.get("description", ""),
                technologies=p.get("technologies", []),
                outreach_roles=p.get("outreach_roles", []),
            )
            for p in cand.get("projects", [])
        ]

        prefs_data = cand.get("preferences", {})
        preferences = CandidatePreferences(
            target_roles=prefs_data.get("target_roles", []),
            work_arrangements=prefs_data.get("work_arrangements", []),
            preferred_locations=prefs_data.get("preferred_locations", []),
            exclude_seniority=prefs_data.get("exclude_seniority", []),
            strict_fresher_only=prefs_data.get("strict_fresher_only", True),
            max_required_experience_years=prefs_data.get(
                "max_required_experience_years", 2
            ),
            small_startup_max_employees=prefs_data.get(
                "small_startup_max_employees", CandidatePreferences.small_startup_max_employees
            ),
            allow_unknown_company_size=prefs_data.get(
                "allow_unknown_company_size", False
            ),
        )

        return cls(
            name=cand.get("name", "Candidate"),
            current_education=education,
            skills=skills,
            experiences=experiences,
            projects=projects,
            preferences=preferences,
        )

    @classmethod
    def load(cls, profile_path: Optional[Path] = None) -> "CandidateProfile":
        """Load candidate profile from YAML configuration file."""
        if profile_path is None:
            settings = Settings.load()
            profile_path = settings.base_dir / "config" / "candidate_profile.yaml"

        if not profile_path.exists():
            logger.warning("Profile YAML not found at %s. Using default profile.", profile_path)
            raise FileNotFoundError(f"Candidate profile configuration missing: {profile_path}")

        with open(profile_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        logger.info("Loaded candidate profile successfully from %s", profile_path.name)
        return cls.from_dict(data)

