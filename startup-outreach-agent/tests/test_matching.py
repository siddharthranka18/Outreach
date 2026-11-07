"""Unit and integration tests for candidate matching, classification, and ranking (Prompt 4.1)."""

from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from startup_agent.database.repositories import CompanyRepository, JobRepository
from startup_agent.matching.classifier import JobCategory, JobClassifier, OpportunityType
from startup_agent.matching.eligibility import EligibilityFilter, EligibilityStatus
from startup_agent.matching.profile import CandidateProfile
from startup_agent.matching.ranker import OpportunityRanker
from startup_agent.matching.resume_extractor import ResumeExtractor
from startup_agent.matching.scorer import OpportunityScorer
from startup_agent.matching.startup_filter import (
    StartupEligibilityFilter,
    StartupEligibilityStatus,
)
from startup_agent.models.company import Company
from startup_agent.models.job import Job


@pytest.fixture
def sample_profile() -> CandidateProfile:
    """Fixture returning the candidate profile."""
    return CandidateProfile.load()


def test_job_classification() -> None:
    """Test classification of various job titles into standardized categories and opportunity types."""
    classifier = JobClassifier()

    # Category checks
    assert classifier.classify("Software Engineer Intern") == JobCategory.SOFTWARE_DEV_INTERN
    assert classifier.classify("Backend Developer Intern") == JobCategory.BACKEND_INTERN
    assert classifier.classify("Machine Learning Intern") == JobCategory.AI_ML_INTERN
    assert classifier.classify("AI Research Intern") == JobCategory.AI_ML_INTERN
    assert classifier.classify("Full Stack Intern") == JobCategory.FULL_STACK_INTERN
    assert classifier.classify("Frontend Engineering Intern") == JobCategory.FRONTEND_INTERN
    assert classifier.classify("Data Science Intern") == JobCategory.DATA_SCIENCE_INTERN
    assert classifier.classify("Data Engineering Intern") == JobCategory.DATA_ENG_INTERN

    # Non-internship engineering
    assert classifier.classify("Software Engineer") == JobCategory.GENERAL_SWE
    assert classifier.classify("Full Stack Developer") == JobCategory.GENERAL_SWE

    # Unrelated roles (expanded in Prompt 4.1)
    assert classifier.classify("Account Executive, Enterprise") == JobCategory.UNRELATED
    assert classifier.classify("Senior Recruiter") == JobCategory.UNRELATED
    assert classifier.classify("Preschool Daycare Teacher") == JobCategory.UNRELATED
    assert classifier.classify("AI Solutions Associate") == JobCategory.UNRELATED
    assert classifier.classify("Creator Internship") == JobCategory.UNRELATED
    assert classifier.classify("Robotics Intern") == JobCategory.SOFTWARE_DEV_INTERN
    assert classifier.classify("Electrical Engineering Intern") == JobCategory.UNRELATED
    assert classifier.classify("Mechanical Engineering Placement, New Grad") == JobCategory.UNRELATED
    assert classifier.classify("Finance Operations Lead") == JobCategory.UNRELATED
    assert classifier.classify("Demand Generation Manager") == JobCategory.UNRELATED
    assert classifier.classify("Product Marketing Manager") == JobCategory.UNRELATED
    assert classifier.classify("Legal Counsel") == JobCategory.UNRELATED

    # Opportunity Types
    assert (
        classifier.determine_opportunity_type("Software Engineer Intern")
        == OpportunityType.INTERNSHIP
    )
    assert (
        classifier.determine_opportunity_type("SWE Co-op Fall 2025")
        == OpportunityType.COOP_STUDENT
    )
    assert (
        classifier.determine_opportunity_type("Graduate Software Engineer")
        == OpportunityType.GRADUATE_ENTRY_LEVEL
    )
    assert (
        classifier.determine_opportunity_type("Entry Level Developer")
        == OpportunityType.GRADUATE_ENTRY_LEVEL
    )
    assert (
        classifier.determine_opportunity_type("Software Engineer", employment_type="Full-time")
        == OpportunityType.REGULAR_FULL_TIME
    )
    assert (
        classifier.determine_opportunity_type("Senior Backend Architect")
        == OpportunityType.SENIOR_STAFF
    )
    assert (
        classifier.determine_opportunity_type("Staff Engineer", experience_level="7+ years")
        == OpportunityType.SENIOR_STAFF
    )


def test_internship_eligibility_filtering(sample_profile: CandidateProfile) -> None:
    """Test eligibility categorization (Eligible, Potentially Eligible, Ineligible, Insufficient Info)."""
    filter_engine = EligibilityFilter(sample_profile)

    # 1. Eligible: explicit remote internship with adequate description (>80 chars)
    res_eligible = filter_engine.evaluate(
        title="Software Engineering Intern",
        category=JobCategory.SOFTWARE_DEV_INTERN,
        opportunity_type=OpportunityType.INTERNSHIP,
        location="Remote",
        description="Looking for passionate CS students with Python or React experience to develop backend services and modern interfaces.",
    )
    assert res_eligible.status == EligibilityStatus.ELIGIBLE

    # 2. Ineligible: senior title
    res_senior = filter_engine.evaluate(
        title="Senior Backend Engineer",
        category=JobCategory.GENERAL_SWE,
        opportunity_type=OpportunityType.SENIOR_STAFF,
        location="Remote",
        description="Requires 8+ years of backend system design experience.",
    )
    assert res_senior.status == EligibilityStatus.INELIGIBLE

    # 3. Ineligible: unrelated role
    res_unrelated = filter_engine.evaluate(
        title="Account Executive",
        category=JobCategory.UNRELATED,
        opportunity_type=OpportunityType.OTHER_UNKNOWN,
    )
    assert res_unrelated.status == EligibilityStatus.INELIGIBLE

    # 4. Ineligible: ordinary full-time role is outside strict fresher targeting
    res_us_ft = filter_engine.evaluate(
        title="Software Engineer",
        category=JobCategory.GENERAL_SWE,
        opportunity_type=OpportunityType.REGULAR_FULL_TIME,
        location="San Francisco, CA",
        description="Develop scalable backend services using Python and Postgres. Build high-throughput APIs and data pipelines for our platform.",
        experience_level="2-4 years",
    )
    assert res_us_ft.status == EligibilityStatus.INELIGIBLE
    assert any("not explicitly marked" in reason for reason in res_us_ft.reasons)

    # 5. Insufficient Info: completely empty description
    res_minimal = filter_engine.evaluate(
        title="Software Engineer",
        category=JobCategory.GENERAL_SWE,
        opportunity_type=OpportunityType.REGULAR_FULL_TIME,
        description="",
    )
    assert res_minimal.status == EligibilityStatus.INSUFFICIENT_INFO


def test_scoring_bounded_and_breakdown(sample_profile: CandidateProfile) -> None:
    """Test that scoring is strictly bounded between 0 and 100, and breakdown is populated."""
    scorer = OpportunityScorer(sample_profile)

    res = scorer.score(
        job_id=1,
        job_title="AI / Backend Software Intern",
        company_name="NeuraGen Labs",
        job_url="https://neuragen.example/jobs/1",
        description="We are seeking an intern to build FastAPI REST APIs and RAG pipelines with Docker, Python, and Rust.",
        location="Remote",
        employment_type="Internship",
        employee_count="11-50",
        hiring_status="Actively Hiring",
    )

    # Must be strictly within 0 to 100
    assert 0.0 <= res.match_score <= 100.0
    assert res.match_score >= 75.0

    # Verify score breakdown components sum to match_score
    sb = res.score_breakdown
    assert "role_alignment" in sb
    assert "skills_score" in sb
    assert "project_evidence" in sb
    assert "experience_fit" in sb
    components_sum = sb["role_alignment"] + sb["skills_score"] + sb["project_evidence"] + sb["experience_fit"]
    assert abs(components_sum - res.match_score) < 0.01

    assert "Fastapi" in res.matching_skills or "Python" in res.matching_skills or "Rag" in res.matching_skills
    assert "Rust" in res.missing_skills
    assert any("SehatSaathi" in proj for proj in res.relevant_projects)
    assert res.eligibility_status == EligibilityStatus.ELIGIBLE
    assert res.opportunity_type == OpportunityType.INTERNSHIP


def test_single_keyword_skill_scaling(sample_profile: CandidateProfile) -> None:
    """Test that a single-keyword match (like only 'LLM') does not receive a misleadingly high skill score."""
    scorer = OpportunityScorer(sample_profile)

    # Job description mentions only LLMs and generic management text
    res = scorer.score(
        job_id=2,
        job_title="Full Stack Engineer",
        company_name="Pogo",
        job_url="https://pogo.example/job/2",
        description="Work on our customer products with LLMs and prompt engineering tools.",
        location="Remote",
        employment_type="Full-time",
    )

    # In Prompt 4, 1-keyword match gave 30/30 skill points.
    # In Prompt 4.1, 1-keyword match gives at most 15.0 / 40.0 skill points.
    assert res.score_breakdown["skills_score"] <= 15.0
    assert len(res.matching_skills) == 1
    assert "Llm" in res.matching_skills
    assert res.opportunity_type == OpportunityType.REGULAR_FULL_TIME


def test_missing_description_scoring(sample_profile: CandidateProfile) -> None:
    """Test that a missing or empty description gets 0 skill points and completeness='Missing'."""
    scorer = OpportunityScorer(sample_profile)

    res = scorer.score(
        job_id=3,
        job_title="Software Engineering Intern",
        company_name="Stealth Startup",
        job_url="https://stealth.example/intern",
        description="",
        location="Remote",
    )

    assert res.description_completeness == "Missing"
    assert res.score_breakdown["skills_score"] == 0.0
    assert any("Insufficient job description" in w for w in res.warnings)


def test_opportunity_ranking_order(db_session: Session, sample_profile: CandidateProfile) -> None:
    """Test that OpportunityRanker sorts highest-match opportunities first."""
    co_repo = CompanyRepository(db_session)
    job_repo = JobRepository(db_session)

    company = co_repo.create_company(
        Company(
            company_name="Tech Venture",
            website="https://techventure.io",
            source_name="test",
            source_url="https://techventure.io",
            employee_count="11-50",
            hiring_status="Actively Hiring",
        )
    )

    # Job 1: High match (Remote Python/AI Intern)
    job_repo.create_job(
        Job(
            company_id=company.id,
            job_title="AI Engineering Intern",
            job_url="https://techventure.io/job/1",
            source_name="test",
            description="Build Python FastAPI and RAG vector applications.",
            location="Remote",
            employment_type="Internship",
        )
    )

    # Job 2: Moderate match (General Full Stack Engineer)
    job_repo.create_job(
        Job(
            company_id=company.id,
            job_title="Full Stack Engineer",
            job_url="https://techventure.io/job/2",
            source_name="test",
            description="Work on React and Node.js applications.",
            location="San Francisco, CA",
        )
    )

    # Job 3: Unrelated / Ineligible (Sales Executive)
    job_repo.create_job(
        Job(
            company_id=company.id,
            job_title="Senior Enterprise Account Executive",
            job_url="https://techventure.io/job/3",
            source_name="test",
            description="Manage outbound B2B software sales pipelines.",
            location="New York",
        )
    )

    ranker = OpportunityRanker(profile=sample_profile, session=db_session)
    ranked = ranker.rank_opportunities()

    assert len(ranked) == 3
    # First ranked must be the high-match intern role
    assert ranked[0].job_title == "AI Engineering Intern"
    assert ranked[0].match_score > ranked[1].match_score
    # Ineligible role is ranked last with lowest score
    assert ranked[2].eligibility_status == EligibilityStatus.INELIGIBLE


def test_small_startup_filter_boundaries() -> None:
    """Only confirmed companies at or below the configured size are eligible."""
    startup_filter = StartupEligibilityFilter(max_employees=200)

    assert startup_filter.evaluate("1-10").status == StartupEligibilityStatus.ELIGIBLE
    assert startup_filter.evaluate("51-200 employees").status == StartupEligibilityStatus.ELIGIBLE
    assert startup_filter.evaluate("201-500").status == StartupEligibilityStatus.INELIGIBLE
    assert startup_filter.evaluate("500+").status == StartupEligibilityStatus.INELIGIBLE
    assert startup_filter.evaluate("101-250").status == StartupEligibilityStatus.UNKNOWN
    assert startup_filter.evaluate(None).status == StartupEligibilityStatus.UNKNOWN


def test_ranker_excludes_large_and_unknown_companies(
    db_session: Session, sample_profile: CandidateProfile
) -> None:
    """The shortlist keeps broad discovery data but ranks only confirmed small startups."""
    co_repo = CompanyRepository(db_session)
    job_repo = JobRepository(db_session)

    for name, domain, employee_count in [
        ("Small Startup", "small.example", "11-50"),
        ("Large Company", "large.example", "1001-5000"),
        ("Unknown Company", "unknown.example", None),
    ]:
        company = co_repo.create_company(
            Company(
                company_name=name,
                website=f"https://{domain}",
                source_name="test",
                source_url=f"https://{domain}",
                employee_count=employee_count,
            )
        )
        job_repo.create_job(
            Job(
                company_id=company.id,
                job_title="Backend Engineering Intern",
                job_url=f"https://{domain}/jobs/backend-intern",
                source_name="test",
                description=(
                    "Undergraduate interns will build Python and FastAPI backend services "
                    "with PostgreSQL, Docker, and production REST APIs."
                ),
                location="Remote",
                employment_type="Internship",
            )
        )

    ranked = OpportunityRanker(profile=sample_profile, session=db_session).rank_opportunities()

    assert [result.company_name for result in ranked] == ["Small Startup"]


def test_strict_fresher_experience_filtering(sample_profile: CandidateProfile) -> None:
    """Experience-heavy descriptions are rejected even when ATS metadata is missing."""
    filter_engine = EligibilityFilter(sample_profile)
    result = filter_engine.evaluate(
        title="Backend Engineer",
        category=JobCategory.BACKEND,
        opportunity_type=OpportunityType.REGULAR_FULL_TIME,
        description=(
            "Build backend services and APIs in Python. Candidates must have 3+ years "
            "of professional software engineering experience."
        ),
        location="Remote",
    )

    assert result.status == EligibilityStatus.INELIGIBLE
    assert any("fresher ceiling" in reason for reason in result.reasons)


def test_strict_fresher_filter_rejects_unknown_role_type(
    sample_profile: CandidateProfile,
) -> None:
    """A generic role cannot enter the shortlist without an early-career signal."""
    result = EligibilityFilter(sample_profile).evaluate(
        title="AI Researcher",
        category=JobCategory.GENERAL_SWE,
        opportunity_type=OpportunityType.OTHER_UNKNOWN,
        description="",
        location="San Francisco",
    )

    assert result.status == EligibilityStatus.INELIGIBLE
    assert any("not explicitly identified" in reason for reason in result.reasons)


def test_us_restricted_remote_intern_is_not_marked_fully_eligible(
    sample_profile: CandidateProfile,
) -> None:
    """Remote (US) still requires geographic/work-authorization review."""
    result = EligibilityFilter(sample_profile).evaluate(
        title="Software Engineering Intern",
        category=JobCategory.SOFTWARE_DEV_INTERN,
        opportunity_type=OpportunityType.INTERNSHIP,
        description=(
            "Undergraduate interns will build Python backend services and production APIs "
            "with the software engineering team."
        ),
        location="US / Remote (US)",
    )

    assert result.status == EligibilityStatus.POTENTIALLY_ELIGIBLE
    assert result.work_auth_warning is not None


def test_gurugram_internship_is_domestic_and_eligible(
    sample_profile: CandidateProfile,
) -> None:
    """Gurugram and Indian location codes are recognized as domestic."""
    result = EligibilityFilter(sample_profile).evaluate(
        title="Backend Engineer Intern",
        category=JobCategory.BACKEND_INTERN,
        opportunity_type=OpportunityType.INTERNSHIP,
        description=(
            "Undergraduate interns will build Python backend services, REST APIs, and "
            "production database integrations with the engineering team."
        ),
        location="Gurugram, HR, IN / Gurugram, Haryana, IN",
    )

    assert result.status == EligibilityStatus.ELIGIBLE
    assert result.work_auth_warning is None


def test_resume_extractor_safe_supplementation(tmp_path: Path, sample_profile: CandidateProfile) -> None:
    """Test that resume extraction supplements without overwriting existing verified profile data."""
    extractor = ResumeExtractor()
    initial_skills_count = len(sample_profile.all_skills)

    # Non-existent PDF path returns unchanged profile without error
    non_existent = tmp_path / "missing.pdf"
    res_profile = extractor.supplement_profile(sample_profile, non_existent)
    assert len(res_profile.all_skills) == initial_skills_count

    # Plain text extraction directly from vocabulary
    mock_text = "Experienced in Kubernetes, Golang, and GraphQL alongside Python."
    detected = extractor.extract_skills_from_text(mock_text)
    assert "kubernetes" in detected
    assert "graphql" in detected


def test_ambiguous_engineering_classification() -> None:
    """Test classification of GTM Engineer, Sales Engineer, Software Engineer, and Backend Engineer."""
    classifier = JobClassifier()

    # Core engineering titles remain technical regardless of description length
    assert classifier.classify("Software Engineer") == JobCategory.GENERAL_SWE
    assert classifier.classify("Backend Engineer") == JobCategory.GENERAL_SWE
    assert classifier.determine_opportunity_type("Software Engineer", employment_type="Full-time") == OpportunityType.REGULAR_FULL_TIME
    assert classifier.determine_opportunity_type("Backend Engineer", employment_type="Full-time") == OpportunityType.REGULAR_FULL_TIME

    # Ambiguous GTM Engineer with missing/insufficient description
    assert classifier.classify("GTM Engineer", description="") == JobCategory.UNRELATED
    assert classifier.determine_opportunity_type("GTM Engineer", description="") == OpportunityType.OTHER_UNKNOWN

    # Ambiguous GTM Engineer with purely sales/marketing description
    sales_desc = "Partner with sales reps to build lead lists, attend demo calls, update Salesforce CRM, and track outbound metrics."
    assert classifier.classify("GTM Engineer", description=sales_desc) == JobCategory.UNRELATED
    assert classifier.determine_opportunity_type("GTM Engineer", description=sales_desc) == OpportunityType.OTHER_UNKNOWN

    # Genuinely technical GTM Engineer with software development responsibilities (Pogo GTM Engineer)
    technical_gtm_desc = (
        "As a GTM Engineer, you have 2-5 years of professional software engineering experience. "
        "You will ship code that drives pipeline, build AI-powered systems with LLMs and RAG, "
        "and architect backend services, webhooks, APIs, and production systems."
    )
    assert classifier.classify("GTM Engineer", description=technical_gtm_desc) in (JobCategory.GENERAL_SWE, JobCategory.AI_ML)
    assert classifier.determine_opportunity_type("GTM Engineer", description=technical_gtm_desc, employment_type="FullTime") == OpportunityType.REGULAR_FULL_TIME

    # Ambiguous Sales Engineer with standard pre-sales demo description
    presales_desc = "Deliver technical product demos, respond to RFP questionnaires, and guide customers through initial software onboarding."
    assert classifier.classify("Sales Engineer", description=presales_desc) == JobCategory.UNRELATED
    assert classifier.determine_opportunity_type("Sales Engineer", description=presales_desc) == OpportunityType.OTHER_UNKNOWN

    # Genuinely technical Sales/Solutions Engineer with software development responsibilities
    technical_sales_desc = (
        "Build custom software engineering integrations and write code in Python and TypeScript. "
        "Architect backend services, data pipelines, and develop production APIs for enterprise clients."
    )
    assert classifier.classify("Sales Engineer", description=technical_sales_desc) in (JobCategory.GENERAL_SWE, JobCategory.SOFTWARE_DEV)
    assert classifier.determine_opportunity_type("Sales Engineer", description=technical_sales_desc, employment_type="Full-time") == OpportunityType.REGULAR_FULL_TIME


def test_degree_specific_eligibility(sample_profile: CandidateProfile) -> None:
    """Test degree-specific eligibility (PhD required vs preferred, Master's, Bachelor's, and missing descriptions)."""
    filter_engine = EligibilityFilter(sample_profile)

    # 1. PhD required in description -> undergraduate candidate is Ineligible
    res_phd_req = filter_engine.evaluate(
        title="AI Research Scientist",
        category=JobCategory.AI_ML,
        opportunity_type=OpportunityType.REGULAR_FULL_TIME,
        location="Remote",
        description="We are seeking candidates with a Ph.D. in Computer Science or currently enrolled in a PhD program. PhD required.",
    )
    assert res_phd_req.status == EligibilityStatus.INELIGIBLE
    assert any("PhD" in r for r in res_phd_req.reasons)

    # 2. PhD in title with missing description is still outside target scope
    res_phd_title_missing = filter_engine.evaluate(
        title="PhD Intern, AI Applied Scientist (2027)",
        category=JobCategory.AI_ML_INTERN,
        opportunity_type=OpportunityType.INTERNSHIP,
        location="San Francisco, CA",
        description="",
    )
    assert res_phd_title_missing.status == EligibilityStatus.INELIGIBLE
    assert any("PhD" in r for r in res_phd_title_missing.reasons)

    # 3. PhD in title with mandatory PhD description -> Ineligible
    res_phd_title_mandatory = filter_engine.evaluate(
        title="PhD Intern, Machine Learning",
        category=JobCategory.AI_ML_INTERN,
        opportunity_type=OpportunityType.INTERNSHIP,
        location="Remote",
        description="Candidates must be currently enrolled in a PhD program in Computer Science or related fields to be eligible.",
    )
    assert res_phd_title_mandatory.status == EligibilityStatus.INELIGIBLE

    # 4. PhD preferred in description -> Potentially Eligible with warning
    res_phd_pref = filter_engine.evaluate(
        title="Machine Learning Engineer Intern",
        category=JobCategory.AI_ML_INTERN,
        opportunity_type=OpportunityType.INTERNSHIP,
        location="Remote",
        description="Build machine learning models with Python. Open to all students; PhD preferred or equivalent research track.",
    )
    assert res_phd_pref.status == EligibilityStatus.ELIGIBLE or res_phd_pref.status == EligibilityStatus.POTENTIALLY_ELIGIBLE
    assert any("PhD degree preferred" in f or "PhD degree is preferred" in f for f in res_phd_pref.flags)

    # 5. Master's required in description -> Ineligible for undergraduate
    res_ms_req = filter_engine.evaluate(
        title="Software Engineer Intern",
        category=JobCategory.SOFTWARE_DEV_INTERN,
        opportunity_type=OpportunityType.INTERNSHIP,
        location="Remote",
        description="Must be currently enrolled in a Master's degree program in Computer Science. Master's required.",
    )
    assert res_ms_req.status == EligibilityStatus.INELIGIBLE
    assert any("Master's" in r for r in res_ms_req.reasons)

    # 6. Bachelor's / undergraduate explicitly accepted -> Eligible
    res_bs_accepted = filter_engine.evaluate(
        title="Software Engineer Intern",
        category=JobCategory.SOFTWARE_DEV_INTERN,
        opportunity_type=OpportunityType.INTERNSHIP,
        location="Remote",
        description="We welcome passionate undergraduate students currently pursuing a Bachelor's or B.Tech degree in Computer Science.",
    )
    assert res_bs_accepted.status == EligibilityStatus.ELIGIBLE

    # 7. Degree requirement missing in description -> do not assume
    res_no_degree = filter_engine.evaluate(
        title="Software Engineer Intern",
        category=JobCategory.SOFTWARE_DEV_INTERN,
        opportunity_type=OpportunityType.INTERNSHIP,
        location="Remote",
        description="Join our engineering team to write Python and React code for our core web application.",
    )
    assert res_no_degree.status == EligibilityStatus.ELIGIBLE


def test_reduced_project_overcounting(sample_profile: CandidateProfile) -> None:
    """Test that project evidence is tightly coupled to specific technical evidence and not overcounted."""
    scorer = OpportunityScorer(sample_profile)

    # 1. Job with only generic "software" and "api" in description without specific tech
    res_generic = scorer.score(
        job_id=101,
        job_title="Software Developer",
        company_name="Generic Corp",
        job_url="https://generic.example/jobs/1",
        description="Looking for a software developer to build APIs and software systems for business clients.",
        location="Remote",
        employment_type="Full-time",
    )
    # Generic words should not trigger SehatSaathi, Notification Engine, or Smart Airport
    assert len(res_generic.relevant_projects) == 0
    assert res_generic.score_breakdown["project_evidence"] == 0.0

    # 2. Job with specific RAG / Vector search triggers only SehatSaathi
    res_rag = scorer.score(
        job_id=102,
        job_title="AI Engineer Intern",
        company_name="VectorAI",
        job_url="https://vectorai.example/jobs/2",
        description="Build RAG pipelines and vector database retrieval systems using Qdrant and LLM agent frameworks.",
        location="Remote",
        employment_type="Internship",
    )
    assert res_rag.relevant_projects == ["SehatSaathi (FastAPI, Hybrid RAG, Qdrant)"]
    assert res_rag.score_breakdown["project_evidence"] == 10.0

    # 3. Job with distributed queues triggers only Notification Engine
    res_queue = scorer.score(
        job_id=103,
        job_title="Backend Systems Engineer Intern",
        company_name="QueueFlow",
        job_url="https://queueflow.example/jobs/3",
        description="Design distributed queue architecture, background worker processes, and message queues with RabbitMQ and BullMQ.",
        location="Remote",
        employment_type="Internship",
    )
    assert res_queue.relevant_projects == ["Notification Engine (BullMQ, Redis, Node.js)"]
    assert res_queue.score_breakdown["project_evidence"] == 8.0

    # 4. Job with geospatial and concurrency triggers only Smart Airport
    res_geo = scorer.score(
        job_id=104,
        job_title="Backend Engineer Intern",
        company_name="FleetTech",
        job_url="https://fleettech.example/jobs/4",
        description="Implement geospatial 2dsphere indexing and high-throughput ride pooling dispatch algorithms handling concurrency and optimistic locking.",
        location="Remote",
        employment_type="Internship",
    )
    assert res_geo.relevant_projects == ["Smart Airport Ride Pooling (Fullstack Architecture)"]
    assert res_geo.score_breakdown["project_evidence"] == 6.0

    # 5. Job with React Native mobile and MVC triggers only Lipi Data Systems
    res_mobile = scorer.score(
        job_id=105,
        job_title="Mobile Developer Intern",
        company_name="AppWorks",
        job_url="https://appworks.example/jobs/5",
        description="Develop cross-platform mobile applications using React Native and Expo, following MVC architecture and telemetry tracking.",
        location="Remote",
        employment_type="Internship",
    )
    assert res_mobile.relevant_projects == ["Lipi Data Systems Internship (REST APIs, MVC)"]
    assert res_mobile.score_breakdown["project_evidence"] == 5.0

