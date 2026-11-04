"""Unit and integration tests for candidate matching, classification, and ranking."""

from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from startup_agent.database.repositories import CompanyRepository, JobRepository
from startup_agent.matching.classifier import JobCategory, JobClassifier
from startup_agent.matching.eligibility import EligibilityFilter, EligibilityStatus
from startup_agent.matching.profile import CandidateProfile
from startup_agent.matching.ranker import OpportunityRanker
from startup_agent.matching.resume_extractor import ResumeExtractor
from startup_agent.matching.scorer import OpportunityScorer
from startup_agent.models.company import Company
from startup_agent.models.job import Job


@pytest.fixture
def sample_profile() -> CandidateProfile:
    """Fixture returning the candidate profile."""
    return CandidateProfile.load()


def test_job_classification() -> None:
    """Test classification of various job titles into standardized categories."""
    classifier = JobClassifier()

    # Internships
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

    # Unrelated roles
    assert classifier.classify("Account Executive, Enterprise") == JobCategory.UNRELATED
    assert classifier.classify("Senior Recruiter") == JobCategory.UNRELATED
    assert classifier.classify("Preschool Daycare Teacher") == JobCategory.UNRELATED
    assert classifier.classify("Finance Operations Lead") == JobCategory.UNRELATED


def test_internship_eligibility_filtering(sample_profile: CandidateProfile) -> None:
    """Test eligibility categorization (Eligible, Potentially Eligible, Ineligible)."""
    filter_engine = EligibilityFilter(sample_profile)

    # Eligible: explicit remote internship
    res_eligible = filter_engine.evaluate(
        title="Software Engineering Intern",
        category=JobCategory.SOFTWARE_DEV_INTERN,
        location="Remote",
        description="Looking for passionate CS students with Python or React experience.",
    )
    assert res_eligible.status == EligibilityStatus.ELIGIBLE

    # Ineligible: senior title
    res_senior = filter_engine.evaluate(
        title="Senior Backend Engineer",
        category=JobCategory.GENERAL_SWE,
        location="Remote",
        description="Requires 8+ years of backend system design experience.",
    )
    assert res_senior.status == EligibilityStatus.INELIGIBLE

    # Ineligible: unrelated role
    res_unrelated = filter_engine.evaluate(
        title="Account Executive",
        category=JobCategory.UNRELATED,
    )
    assert res_unrelated.status == EligibilityStatus.INELIGIBLE

    # Insufficient Info: minimal description
    res_minimal = filter_engine.evaluate(
        title="Software Engineer",
        category=JobCategory.GENERAL_SWE,
        description="",
    )
    assert res_minimal.status == EligibilityStatus.INSUFFICIENT_INFO


def test_scoring_and_skill_detection(sample_profile: CandidateProfile) -> None:
    """Test explainable scoring with matching and missing skills identification."""
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

    assert res.match_score >= 80.0
    assert "Fastapi" in res.matching_skills or "Python" in res.matching_skills or "Rag" in res.matching_skills
    assert "Rust" in res.missing_skills
    assert any("SehatSaathi" in proj for proj in res.relevant_projects)
    assert res.eligibility_status == EligibilityStatus.ELIGIBLE


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

