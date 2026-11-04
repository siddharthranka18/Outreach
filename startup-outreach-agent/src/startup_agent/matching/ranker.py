"""Opportunity ranking engine for evaluating stored database jobs."""

import logging
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from startup_agent.config.settings import Settings
from startup_agent.database.engine import create_db_engine
from startup_agent.database.models import CompanyModel, JobModel
from startup_agent.database.session import create_session_factory, session_scope
from startup_agent.matching.profile import CandidateProfile
from startup_agent.matching.scorer import MatchResult, OpportunityScorer

logger = logging.getLogger("startup_agent.matching.ranker")


class OpportunityRanker:
    """Evaluates and ranks stored database opportunities against candidate profile."""

    def __init__(
        self,
        profile: Optional[CandidateProfile] = None,
        session: Optional[Session] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or Settings.load()
        self.profile = profile or CandidateProfile.load()
        self.session = session
        self.scorer = OpportunityScorer(self.profile)

    def rank_opportunities(
        self,
        min_score: float = 0.0,
        limit: int = 50,
    ) -> List[MatchResult]:
        """Fetch, evaluate, and rank opportunities from database."""
        if self.session is not None:
            return self._evaluate_jobs(self.session, min_score, limit)

        engine = create_db_engine(self.settings.database_url)
        session_factory = create_session_factory(engine)
        with session_scope(session_factory) as session:
            return self._evaluate_jobs(session, min_score, limit)

    def _evaluate_jobs(
        self,
        session: Session,
        min_score: float,
        limit: int,
    ) -> List[MatchResult]:
        """Internal helper executing queries and scoring."""
        stmt = (
            select(JobModel, CompanyModel)
            .join(CompanyModel, JobModel.company_id == CompanyModel.id)
            .order_by(JobModel.created_at.desc())
        )
        rows = session.execute(stmt).all()

        results: List[MatchResult] = []
        for job_model, company_model in rows:
            match_res = self.scorer.score(
                job_id=job_model.id,
                job_title=job_model.job_title,
                company_name=company_model.company_name,
                job_url=job_model.job_url,
                description=job_model.description,
                location=job_model.location,
                employment_type=job_model.employment_type,
                experience_level=job_model.experience_level,
                employee_count=company_model.employee_count,
                hiring_status=company_model.hiring_status,
                company_website=company_model.website,
                careers_url=company_model.careers_url,
            )

            if match_res.match_score >= min_score:
                results.append(match_res)

        # Sort descending by match_score
        results.sort(key=lambda r: r.match_score, reverse=True)
        return results[:limit]

