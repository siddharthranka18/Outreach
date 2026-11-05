"""Explainable, deterministic match scoring for startup opportunities."""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Set

from startup_agent.matching.classifier import JobCategory, JobClassifier, OpportunityType
from startup_agent.matching.eligibility import EligibilityFilter, EligibilityResult, EligibilityStatus
from startup_agent.matching.profile import CandidateProfile

# Curated technical dictionary for identifying technologies in job postings
SKILL_TAXONOMY = {
    "python": ["python", "py"],
    "javascript": ["javascript", "js"],
    "typescript": ["typescript", "ts"],
    "java": ["java"],
    "c++": ["c++", "cpp"],
    "c#": ["c#", "csharp", ".net"],
    "react": ["react", "react.js", "reactjs"],
    "react native": ["react native", "react-native"],
    "node.js": ["node.js", "nodejs", "node"],
    "express.js": ["express", "express.js", "expressjs"],
    "fastapi": ["fastapi", "fast-api"],
    "django": ["django"],
    "flask": ["flask"],
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
    "socket.io": ["socket.io", "websockets", "websocket"],
    "bullmq": ["bullmq", "message queue", "celery", "rabbitmq", "kafka"],
}


@dataclass
class MatchResult:
    """Detailed, explainable matching outcome for a job posting."""

    job_id: Optional[int]
    job_title: str
    company_name: str
    location: Optional[str]
    category: str
    opportunity_type: OpportunityType
    eligibility_status: EligibilityStatus
    match_score: float  # 0.0 to 100.0
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    description_completeness: str = "Adequate"  # "Adequate", "Minimal", "Missing"
    matching_skills: List[str] = field(default_factory=list)
    missing_skills: List[str] = field(default_factory=list)
    relevant_projects: List[str] = field(default_factory=list)
    score_reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    work_auth_warning: Optional[str] = None
    job_url: str = ""
    company_website: Optional[str] = None
    careers_url: Optional[str] = None


class OpportunityScorer:
    """Calculates explainable, bounded (0-100) technical match scores."""

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
        """Calculate the explainable technical match score for an opportunity."""
        raw_desc = (description or "").strip()
        full_text = f"{job_title} {raw_desc} {employment_type or ''} {experience_level or ''}"
        reasons: List[str] = []
        warnings: List[str] = []

        # 1. Classify Opportunity Type & Role Category
        opportunity_type = self.classifier.determine_opportunity_type(
            title=job_title,
            employment_type=employment_type,
            experience_level=experience_level,
            description=description,
        )
        category = self.classifier.classify(job_title, description, employment_type)

        # 2. Evaluate Eligibility Separately
        eligibility = self.eligibility_filter.evaluate(
            title=job_title,
            category=category,
            opportunity_type=opportunity_type,
            description=description,
            location=location,
            employment_type=employment_type,
            experience_level=experience_level,
        )
        warnings.extend(eligibility.flags)

        # 3. Description Completeness Assessment
        if len(raw_desc) == 0:
            desc_completeness = "Missing"
            warnings.append("Insufficient job description information for reliable technical matching.")
        elif len(raw_desc) < 100:
            desc_completeness = "Minimal"
            warnings.append("Job description is minimal; technical matching is low-confidence.")
        else:
            desc_completeness = "Adequate"

        # 4. Immediate Handling of Ineligible Roles
        if eligibility.status == EligibilityStatus.INELIGIBLE:
            return MatchResult(
                job_id=job_id,
                job_title=job_title,
                company_name=company_name,
                location=location,
                category=category,
                opportunity_type=opportunity_type,
                eligibility_status=EligibilityStatus.INELIGIBLE,
                match_score=0.0,
                score_breakdown={
                    "role_alignment": 0.0,
                    "skills_score": 0.0,
                    "project_evidence": 0.0,
                    "experience_fit": 0.0,
                    "total": 0.0,
                },
                description_completeness=desc_completeness,
                score_reasons=eligibility.reasons + ["Role is marked ineligible."],
                warnings=warnings,
                work_auth_warning=eligibility.work_auth_warning,
                job_url=job_url,
                company_website=company_website,
                careers_url=careers_url,
            )

        # 5. Component 1: Role Family Alignment (Max 25.0 pts)
        role_alignment_score = 0.0
        cat_lower = category.lower()
        if any(target in cat_lower for target in ["ai/ml", "backend", "full stack", "software dev"]):
            role_alignment_score = 25.0
            reasons.append(f"Direct match with target technical domain: '{category}' (25.0/25).")
        elif any(target in cat_lower for target in ["data eng", "frontend", "data science"]):
            role_alignment_score = 18.0
            reasons.append(f"Secondary technical domain alignment: '{category}' (18.0/25).")
        elif category == JobCategory.GENERAL_SWE:
            role_alignment_score = 15.0
            reasons.append("General software engineering domain (15.0/25).")
        else:
            role_alignment_score = 5.0
            reasons.append(f"Indirect technical domain: '{category}' (5.0/25).")

        # 6. Component 2: Technical Skills Overlap (Max 40.0 pts)
        job_skills = self._extract_job_skills(full_text)
        matching_skills: List[str] = []
        missing_skills: List[str] = []

        for skill in job_skills:
            if skill in self.candidate_skills or any(skill in s for s in self.candidate_skills):
                matching_skills.append(skill.title())
            else:
                missing_skills.append(skill.title())

        skills_score = 0.0
        n_detected = len(job_skills)
        if n_detected == 0:
            skills_score = 0.0
            reasons.append("No technical stack requirements parsed from posting (0.0/40).")
        else:
            match_ratio = len(matching_skills) / n_detected
            # Avoid single-keyword inflation
            if n_detected == 1:
                max_pts = 15.0
            elif n_detected == 2:
                max_pts = 28.0
            else:
                max_pts = 40.0

            skills_score = round(max_pts * match_ratio, 1)
            reasons.append(
                f"Skills match: {len(matching_skills)}/{n_detected} detected technologies "
                f"({', '.join(matching_skills) if matching_skills else 'None'}) ({skills_score:.1f}/40)."
            )

        # 7. Component 3: Project & Portfolio Evidence (Max 25.0 pts)
        project_score = 0.0
        relevant_projects: List[str] = []
        full_text_lower = full_text.lower()

        # 1. SehatSaathi: Strong evidence for RAG, LLM, Vector DBs, AI Agents, and FastAPI backend
        has_rag_vector = bool(
            re.search(r"\b(rag|retrieval-augmented|retrieval augmented|qdrant|vector (?:db|database|search|store)|embeddings?|semantic search|rerank(?:ing)?|bm25)\b", full_text_lower)
        )
        has_llm_agents = bool(
            re.search(r"\b(llms?|large language models?|prompt engineering|ai agents?|agentic|agent frameworks?|tool use|evals?|ollama|groq)\b", full_text_lower)
        )
        has_fastapi_backend = bool(re.search(r"\bfastapi\b", full_text_lower))

        if has_rag_vector and has_llm_agents:
            project_score += 10.0
            relevant_projects.append("SehatSaathi (FastAPI, Hybrid RAG, Qdrant)")
        elif has_rag_vector or has_llm_agents or has_fastapi_backend:
            project_score += 8.0
            relevant_projects.append("SehatSaathi (FastAPI, Hybrid RAG, Qdrant)")

        # 2. Notification Engine: Strong evidence for backend, distributed systems, queues, and event processing
        has_queues = bool(
            re.search(r"\b(bullmq|celery|rabbitmq|kafka|sqs|message queues?|queue architecture|task queues?|queue-worker|worker process(?:es)?|background jobs?)\b", full_text_lower)
        )
        has_events = bool(
            re.search(r"\b(event-driven|event driven|event stream(?:ing)?|pub/?sub|pubsub|socket\.io|websockets?)\b", full_text_lower)
        )
        has_redis_broker = bool(re.search(r"\bredis\b", full_text_lower)) and bool(re.search(r"\b(cache|caching|queue|broker|pubsub|store)\b", full_text_lower))

        if has_queues or has_events or has_redis_broker:
            project_score += 8.0
            relevant_projects.append("Notification Engine (BullMQ, Redis, Node.js)")

        # 3. Smart Airport Ride Pooling: Evidence for full-stack/backend, concurrency, geospatial, and database-related roles
        has_geospatial = bool(re.search(r"\b(geospatial|2dsphere|spatial index(?:ing)?|gis)\b", full_text_lower))
        has_concurrency = bool(re.search(r"\b(concurrency|optimistic locking|pessimistic locking|race conditions?)\b", full_text_lower))
        has_ride_matching = bool(re.search(r"\b(ride pooling|ride-pooling|dispatch algorithm|matching algorithms?)\b", full_text_lower))
        has_high_throughput_db = bool(re.search(r"\b(high throughput|high-throughput|sub-second latency)\b", full_text_lower))

        if has_geospatial or has_concurrency or has_ride_matching or has_high_throughput_db:
            project_score += 6.0
            relevant_projects.append("Smart Airport Ride Pooling (Fullstack Architecture)")

        # 4. Lipi Data Systems Internship: Evidence for verified internship responsibilities (mobile, MVC, telemetry)
        has_mobile = bool(re.search(r"\b(react native|expo|mobile application|mobile apps?)\b", full_text_lower))
        has_mvc = bool(re.search(r"\b(mvc|model-view-controller)\b", full_text_lower))
        has_telemetry = bool(re.search(r"\b(workforce management|telemetry|gps tracking|location tracking)\b", full_text_lower))

        if has_mobile or has_mvc or has_telemetry:
            project_score += 5.0
            relevant_projects.append("Lipi Data Systems Internship (REST APIs, MVC)")

        # 5. AI Shopping Assistant: Conversational agent with LangChain and tool calling
        has_langchain_tools = bool(re.search(r"\b(langchain|langgraph|tool calling|function calling|conversational assistant|streamlit)\b", full_text_lower))
        if has_langchain_tools and "SehatSaathi (FastAPI, Hybrid RAG, Qdrant)" not in relevant_projects:
            project_score += 4.0
            relevant_projects.append("AI Shopping Assistant (LangChain, Tool Calling)")

        project_score = min(25.0, round(project_score, 1))
        if relevant_projects:
            reasons.append(f"Demonstrated project proof-of-work synergy ({project_score:.1f}/25).")
        else:
            reasons.append("No direct project proof-of-work synergy (0.0/25).")

        # 8. Component 4: Experience Level Fit (Max 10.0 pts)
        experience_score = 0.0
        exp_match = re.search(r"(\d+)\+?\s*years?", experience_level or "")
        req_years = int(exp_match.group(1)) if exp_match else None

        if opportunity_type in (OpportunityType.INTERNSHIP, OpportunityType.COOP_STUDENT, OpportunityType.GRADUATE_ENTRY_LEVEL):
            experience_score = 10.0
            reasons.append("Optimal early-career/student seniority fit (10.0/10).")
        elif req_years is not None and req_years <= 2:
            experience_score = 10.0
            reasons.append("Entry-level experience requirements (10.0/10).")
        elif req_years is not None and req_years <= 3:
            experience_score = 6.0
            reasons.append("Requires 2-3 years experience; slight stretch for student (6.0/10).")
        elif req_years is not None and req_years <= 4:
            experience_score = 3.0
            reasons.append("Requires 3-4 years experience; significant stretch (3.0/10).")
        else:
            experience_score = 5.0
            reasons.append("Unstated experience level; baseline fit applied (5.0/10).")

        # 9. Compute Total Technical Match Score (strictly 0.0 to 100.0)
        total_tech_score = round(
            min(100.0, max(0.0, role_alignment_score + skills_score + project_score + experience_score)),
            1,
        )

        score_breakdown = {
            "role_alignment": role_alignment_score,
            "skills_score": skills_score,
            "project_evidence": project_score,
            "experience_fit": experience_score,
            "total": total_tech_score,
        }

        return MatchResult(
            job_id=job_id,
            job_title=job_title,
            company_name=company_name,
            location=location,
            category=category,
            opportunity_type=opportunity_type,
            eligibility_status=eligibility.status,
            match_score=total_tech_score,
            score_breakdown=score_breakdown,
            description_completeness=desc_completeness,
            matching_skills=sorted(list(set(matching_skills))),
            missing_skills=sorted(list(set(missing_skills))),
            relevant_projects=list(dict.fromkeys(relevant_projects)),
            score_reasons=reasons,
            warnings=warnings,
            work_auth_warning=eligibility.work_auth_warning,
            job_url=job_url,
            company_website=company_website,
            careers_url=careers_url,
        )
