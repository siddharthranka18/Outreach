"""Discovery pipeline orchestration for multi-source extraction and persistence."""

from dataclasses import dataclass, field
import logging
import time
from typing import Dict, List, Optional, Tuple, Type
from sqlalchemy.orm import Session

from startup_agent.config.settings import Settings
from startup_agent.database.engine import create_db_engine
from startup_agent.database.repositories import CompanyRepository, JobRepository
from startup_agent.database.session import create_session_factory, session_scope
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.discovery.direct_ats import DirectAtsDiscoverySource
from startup_agent.discovery.top_startups import TopStartupsDiscoverySource
from startup_agent.discovery.y_combinator import YCombinatorDiscoverySource
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.normalizers import normalize_name, normalize_website

logger = logging.getLogger("startup_agent.discovery.pipeline")

# Registry of supported discovery adapter implementations
SOURCE_ADAPTER_REGISTRY: Dict[str, Type[BaseDiscoverySource]] = {
    "y_combinator": YCombinatorDiscoverySource,
    "top_startups": TopStartupsDiscoverySource,
    "company_career_sites": DirectAtsDiscoverySource,
    "direct_ats": DirectAtsDiscoverySource,
}


@dataclass
class DiscoverySummary:
    """Summary metrics of a completed discovery pipeline execution."""

    sources_attempted: int = 0
    sources_successful: int = 0
    sources_failed: List[Tuple[str, str]] = field(default_factory=list)
    companies_discovered: int = 0
    companies_inserted: int = 0
    companies_updated: int = 0
    jobs_discovered: int = 0
    jobs_inserted: int = 0
    jobs_updated: int = 0
    duration_seconds: float = 0.0

    @property
    def has_failures(self) -> bool:
        """Check if any attempted source produced an error."""
        return len(self.sources_failed) > 0

    @property
    def all_failed(self) -> bool:
        """Check if every attempted source failed."""
        return self.sources_attempted > 0 and self.sources_successful == 0


class DiscoveryPipeline:
    """Orchestrates source adapter discovery, normalization, and relational upsert."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        session: Optional[Session] = None,
        custom_adapters: Optional[List[BaseDiscoverySource]] = None,
    ) -> None:
        self.settings = settings or Settings.load()
        self.session = session
        self.custom_adapters = custom_adapters

    def _resolve_adapters(self) -> List[BaseDiscoverySource]:
        """Resolve enabled source adapter instances based on configuration."""
        if self.custom_adapters is not None:
            return self.custom_adapters

        adapters: List[BaseDiscoverySource] = []
        for src in self.settings.sources:
            if not src.enabled:
                continue
            adapter_cls = SOURCE_ADAPTER_REGISTRY.get(src.name)
            if adapter_cls:
                adapters.append(adapter_cls(name=src.name, enabled=True))
            else:
                logger.warning("No registered discovery adapter for source: '%s'", src.name)
        return adapters

    def run(self) -> DiscoverySummary:
        """Execute the discovery pipeline across all resolved sources."""
        start_time = time.time()
        summary = DiscoverySummary()
        adapters = self._resolve_adapters()

        if not adapters:
            logger.warning("No enabled discovery adapters configured.")
            return summary

        collected_companies: List[Company] = []
        collected_jobs: List[Job] = []

        # 1. Source Discovery Phase with Source-Level Isolation
        for adapter in adapters:
            summary.sources_attempted += 1
            logger.info("Starting discovery for source: '%s'...", adapter.name)
            try:
                raw_result = adapter.discover()
                if isinstance(raw_result, DiscoveryResult):
                    discovered_cos = raw_result.companies
                    discovered_jbs = raw_result.jobs
                elif isinstance(raw_result, list):
                    discovered_cos = raw_result
                    discovered_jbs = []
                else:
                    discovered_cos = []
                    discovered_jbs = []

                collected_companies.extend(discovered_cos)
                collected_jobs.extend(discovered_jbs)
                summary.sources_successful += 1
                logger.info(
                    "Source '%s' completed successfully (%d companies, %d jobs).",
                    adapter.name,
                    len(discovered_cos),
                    len(discovered_jbs),
                )
            except Exception as exc:
                logger.error("Source '%s' encountered an unhandled error: %s", adapter.name, exc, exc_info=True)
                summary.sources_failed.append((adapter.name, str(exc)))

        summary.companies_discovered = len(collected_companies)
        summary.jobs_discovered = len(collected_jobs)

        # 2. Persistence Phase within Transactional Scope
        if self.session is not None:
            self._persist_entities(self.session, collected_companies, collected_jobs, summary)
        else:
            engine = create_db_engine(self.settings.database_url)
            session_factory = create_session_factory(engine)
            with session_scope(session_factory) as session:
                self._persist_entities(session, collected_companies, collected_jobs, summary)

        summary.duration_seconds = round(time.time() - start_time, 2)
        logger.info(
            "Discovery pipeline completed in %.2fs: %d companies (+%d, ~%d), %d jobs (+%d, ~%d).",
            summary.duration_seconds,
            summary.companies_discovered,
            summary.companies_inserted,
            summary.companies_updated,
            summary.jobs_discovered,
            summary.jobs_inserted,
            summary.jobs_updated,
        )
        return summary

    def _persist_entities(
        self,
        session: Session,
        companies: List[Company],
        jobs: List[Job],
        summary: DiscoverySummary,
    ) -> None:
        """Persist companies and linked jobs into the database with duplicate checks."""
        company_repo = CompanyRepository(session)
        job_repo = JobRepository(session)

        # Lookup caches: normalized_website -> company_id, normalized_name -> company_id
        company_id_by_website: Dict[str, int] = {}
        company_id_by_name: Dict[str, int] = {}

        # 1. Upsert Companies
        for company in companies:
            try:
                model, is_new = company_repo.upsert_company_with_status(company)
                if is_new:
                    summary.companies_inserted += 1
                else:
                    summary.companies_updated += 1

                company_id_by_website[model.normalized_website] = model.id
                company_id_by_name[model.normalized_name] = model.id
            except Exception as exc:
                logger.error("Failed to upsert company '%s': %s", company.company_name, exc)

        # 2. Resolve Company IDs and Upsert Jobs
        for job in jobs:
            try:
                # Link company_id if not already established
                if job.company_id is None:
                    target_id = None
                    if job.company_website:
                        norm_site = normalize_website(job.company_website)
                        target_id = company_id_by_website.get(norm_site)
                        if not target_id:
                            existing_co = company_repo.get_company_by_website(norm_site)
                            if existing_co:
                                target_id = existing_co.id

                    if not target_id and job.company_name:
                        norm_name = normalize_name(job.company_name)
                        target_id = company_id_by_name.get(norm_name)
                        if not target_id:
                            existing_co = company_repo.get_company_by_normalized_name(norm_name)
                            if existing_co:
                                target_id = existing_co.id

                    if target_id is None:
                        logger.warning(
                            "Could not resolve company for job '%s' (%s). Skipping job.",
                            job.job_title,
                            job.company_name or job.company_website,
                        )
                        continue
                    job.company_id = target_id

                model, is_new = job_repo.upsert_job_with_status(job)
                if is_new:
                    summary.jobs_inserted += 1
                else:
                    summary.jobs_updated += 1
            except Exception as exc:
                logger.error("Failed to upsert job '%s': %s", job.job_title, exc)


def run_discovery_pipeline(
    settings: Optional[Settings] = None,
    session: Optional[Session] = None,
) -> DiscoverySummary:
    """Convenience helper to execute the discovery pipeline."""
    pipeline = DiscoveryPipeline(settings=settings, session=session)
    return pipeline.run()

