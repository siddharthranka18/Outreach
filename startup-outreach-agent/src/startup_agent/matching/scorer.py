"""Explainable, deterministic match scoring for startup opportunities."""

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional, Set, Tuple

from startup_agent.matching.classifier import JobCategory, JobClassifier
from startup_agent.matching.eligibility import EligibilityFilter, EligibilityResult, EligibilityStatus
from startup_agent.matching.profile import CandidateProfile

# Technical dictionary for identifying required technologies in job postings
SKILL_TAXONOMY = {
    "python": ["python", "py"],
    "javascript": ["javascript", "js"],
    "typescript": ["typescript", "ts"],
    "java": ["java"],
    "c++": ["c++", "cpp"],
    "react": ["react", "react.js", "reactjs"],
    "react native": ["react native", "react-native"],
    "node.js": ["node.js", "nodejs", "node"],
    "express.js": ["express", "express.js", "expressjs"],
    "fastapi": ["fastapi", "fast-api"],
    "mysql": ["mysql"],
    "postgresql": ["postgresql", "postgres"],
    "mongodb": ["mongodb", "mongo"],
    "redis": ["redis"],
    "qdrant": ["qdrant"],
    "docker": ["docker", "containerization"],
    "kubernetes": ["kubernetes", "k8s"],
    "langchain": ["langchain"],
    "langgraph": ["langgraph"],
    "rag": ["rag", "retrieval-augmented generation"],
    "llm": ["llm", "llms", "large language models"],
    "rest apis": ["rest api", "rest apis", "restful", "restful api"],
    "git": ["git", "github"],
    "aws": ["aws", "amazon web services"],
    "gcp": ["gcp", "google cloud"],
    "go": ["golang", "go"],
    "rust": ["rust"],
    "graphql": ["graphql"],
}


@dataclass
class MatchResult:
    """Detailed, explainable matching outcome for a job posting."""

    job_id: Optional[int]
    job_title: str
    company_name: str
    location: Optional[str]
    category: str
    eligibility_status: EligibilityStatus
    match_score: float  # 0.0 to 100.0
    matching_skills: List[str] = field(default_factory=list)
    missing_skills: List[str] = field(default_factory=list)
    relevant_projects: List[str] = field(default_factory=list)
    score_reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    job_url: str = ""
    company_website: Optional[str] = None
    careers_url: Optional[str] = None


class OpportunityScorer:
    """Calculates weighted, explainable match scores without LLM dependencies."""

    def __init__(self, profile: CandidateProfile) -> None:
        self.profile = profile
        self.classifier = JobClassifier()
        self.eligibility_filter = EligibilityFilter(profile)
        self.candidate_skills = profile.all_skills

    def _extract_job_skills(self, text: str) -> Set[str]:
        """Detect technical skills present in job text using taxonomy."""
        detected = set()
        text_lower = text.lower()
        for canonical, aliases in SKILL_TAXONOMY.items():
            for alias in aliases:
                pattern = r"(?<!\w)" + re.escape(alias) + r"(?!\w)"
                if re.search(pattern, text_lower):
                    detected.add(canonical)
                    break
        return detected

    def score(
        self,
        job_id: Optional[int],
        job_title: str,
        company_name: str,
        job_url: str,
        description: Optional[str] = None,
        location: Optional[str] = None,
        employment_type: Optional[str] = None,
        experience_level: Optional[str] = None,
        employee_count: Optional[str] = None,
        hiring_status: Optional[str] = None,
        company_website: Optional[str] = None,
        careers_url: Optional[str] = None,
    ) -> MatchResult:
        """Calculate the explainable match score for an opportunity."""
        full_text = f"{job_title} {description or ''} {employment_type or ''} {experience_level or ''}"
        reasons: List[str] = []
        warnings: List[str] = []

        # 1. Classification & Eligibility
        category = self.classifier.classify(job_title, description, employment_type)
        eligibility = self.eligibility_filter.evaluate(
            title=job_title,
            category=category,
            description=description,
            location=location,
            employment_type=employment_type,
            experience_level=experience_level,
        )
        warnings.extend(eligibility.flags)

        # Immediate penalty if marked ineligible
        if eligibility.status == EligibilityStatus.INELIGIBLE:
            return MatchResult(
                job_id=job_id,
                job_title=job_title,
                company_name=company_name,
                location=location,
                category=category,
                eligibility_status=EligibilityStatus.INELIGIBLE,
                match_score=10.0,
                score_reasons=eligibility.reasons + ["Opportunity marked ineligible."],
                warnings=warnings,
                job_url=job_url,
                company_website=company_website,
                careers_url=careers_url,
            )

        # 2. Category & Role Alignment (Max 25 pts)
        category_score = 0.0
        if "intern" in category.lower():
            category_score = 25.0
            reasons.append(f"Direct match with target internship family: '{category}' (+25.0).")
        elif category == JobCategory.GENERAL_SWE:
            category_score = 15.0
            reasons.append("General software engineering opportunity (+15.0).")
        else:
            category_score = 5.0
            reasons.append("Indirect technical role (+5.0).")

        # 3. Technical Skills Alignment (Max 30 pts)
        job_skills = self._extract_job_skills(full_text)
        matching_skills: List[str] = []
        missing_skills: List[str] = []

        for skill in job_skills:
            if skill in self.candidate_skills or any(skill in s for s in self.candidate_skills):
                matching_skills.append(skill.title())
            else:
                missing_skills.append(skill.title())

        skills_score = 0.0
        if job_skills:
            match_ratio = len(matching_skills) / len(job_skills)
            skills_score = round(30.0 * match_ratio, 1)
            reasons.append(
                f"Matched {len(matching_skills)}/{len(job_skills)} required technical skills "
                f"({', '.join(matching_skills) if matching_skills else 'None'}) (+{skills_score})."
            )
        else:
            skills_score = 15.0
            warnings.append("Posting lists no explicit tech stack keywords; granted baseline score.")
            reasons.append("Baseline skill score applied due to unlisted stack (+15.0).")

        # 4. Relevant Projects & Experience (Max 20 pts)
        project_score = 0.0
        relevant_projects: List[str] = []
        full_text_lower = full_text.lower()

        # AI/ML/RAG match -> SehatSaathi
        if any(kw in full_text_lower for kw in ["ai", "ml", "rag", "fastapi", "llm", "embeddings"]):
            project_score += 8.0
            relevant_projects.append("SehatSaathi (FastAPI, Hybrid RAG, Vector DB)")

        # Backend/APIs/Queues match -> Notification Engine / Lipi Data Systems
        if any(kw in full_text_lower for kw in ["backend", "api", "node", "express", "redis", "mongodb", "mysql", "queue"]):
            project_score += 7.0
            relevant_projects.append("Notification Engine (BullMQ, Redis, Node.js)")
            relevant_projects.append("Lipi Data Systems Internship (REST APIs, MVC)")

        # Fullstack/React match -> Smart Airport / SehatSaathi
        if any(kw in full_text_lower for kw in ["react", "full stack", "fullstack", "frontend"]):
            project_score += 5.0
            relevant_projects.append("Smart Airport Ride Pooling (Fullstack Architecture)")

        project_score = min(20.0, project_score)
        if relevant_projects:
            reasons.append(f"Demonstrated project proof-of-work alignment (+{project_score:.1f}).")
        else:
            project_score = 6.0
            reasons.append("Baseline project relevance applied (+6.0).")

        # 5. Eligibility Weight (Max 15 pts)
        eligibility_score = 0.0
        if eligibility.status == EligibilityStatus.ELIGIBLE:
            eligibility_score = 15.0
            reasons.append("Verified student internship eligibility (+15.0).")
        elif eligibility.status == EligibilityStatus.POTENTIALLY_ELIGIBLE:
            eligibility_score = 10.0
            reasons.append("Potentially eligible candidate profile (+10.0).")
        else:
            eligibility_score = 5.0
            reasons.append("Insufficient metadata to fully verify eligibility (+5.0).")

        # 6. Location & Work Arrangement (Max 10 pts)
        location_score = 0.0
        loc_str = (location or "").lower()
        if any(kw in loc_str for kw in ["remote", "virtual", "wfh", "anywhere"]):
            location_score = 10.0
            reasons.append("Remote work arrangement (+10.0).")
        elif any(kw in loc_str for kw in ["india", "gurgaon", "delhi", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai"]):
            location_score = 10.0
            reasons.append(f"Domestic preferred location '{location}' (+10.0).")
        elif not location:
            location_score = 5.0
            warnings.append("Location unlisted; assuming potential remote.")
            reasons.append("Unlisted location baseline (+5.0).")
        else:
            location_score = 3.0
            warnings.append(f"On-site/hybrid role located in '{location}'.")
            reasons.append("Non-preferred geographic location (+3.0).")

        # 7. Company Signals Bonus (Up to +5 pts)
        company_bonus = 0.0
        if employee_count:
            # Prefer startups (10-100 employees)
            if any(band in employee_count for band in ["1-10", "11-50", "51-100", "50-100"]):
                company_bonus += 3.0
                reasons.append(f"Target startup scale ({employee_count}) (+3.0).")
        if hiring_status and "hiring" in hiring_status.lower():
            company_bonus += 2.0
            reasons.append("Company actively marked as hiring (+2.0).")

        total_score = category_score + skills_score + project_score + eligibility_score + location_score + company_bonus
        final_score = min(100.0, max(0.0, round(total_score, 1)))

        return MatchResult(
            job_id=job_id,
            job_title=job_title,
            company_name=company_name,
            location=location,
            category=category,
            eligibility_status=eligibility.status,
            match_score=final_score,
            matching_skills=sorted(list(set(matching_skills))),
            missing_skills=sorted(list(set(missing_skills))),
            relevant_projects=list(dict.fromkeys(relevant_projects)),
            score_reasons=reasons,
            warnings=warnings,
            job_url=job_url,
            company_website=company_website,
            careers_url=careers_url,
        )

