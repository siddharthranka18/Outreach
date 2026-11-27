"""Repository layer for Company and Job persistence operations."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Union
from urllib.parse import urlparse
from sqlalchemy import select
from sqlalchemy.orm import Session
from startup_agent.database.models import CompanyModel, JobModel, JobRelistModel
from startup_agent.utils.job_key import canonical_job_key
from startup_agent.utils.simhash import description_simhash, hamming_distance
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.normalizers import (
    normalize_job_url,
    normalize_name,
    normalize_website,
)


INDIRECT_COMPANY_HOSTS = {
    "jobs.ashbyhq.com",
    "jobs.lever.co",
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.smartrecruiters.com",
    "wellfound.com",
    "remotive.com",
    "andhrastartupmap.in",
    "ycombinator.com", "workatastartup.com", "himalayas.app", "remoteok.com", "jobicy.com",
    "workingnomads.com", "weworkremotely.com", "news.ycombinator.com", "cutshort.io", "peerlist.io",
    "apply.workable.com", "jobs.weekday.works", "startups.gallery",
}


def _is_indirect_company_url(value: Optional[str]) -> bool:
    """Return whether a URL is an aggregator/profile/ATS rather than a company site."""
    if not value:
        return False
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower().removeprefix("www.")
    return host in INDIRECT_COMPANY_HOSTS or any(host.endswith('.'+suffix) for suffix in
        ('recruitee.com','breezy.hr','teamtailor.com','bamboohr.com','freshteam.com','jobs.personio.de','myworkdayjobs.com'))


class CompanyRepository:
    """Handles database persistence and deduplication for companies."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _to_model(self, company: Union[Company, CompanyModel]) -> CompanyModel:
        """Convert a domain Company dataclass to a CompanyModel if needed."""
        if isinstance(company, CompanyModel):
            return company
        return CompanyModel(
            company_name=company.company_name,
            normalized_name=company.normalized_name,
            website=company.website,
            normalized_website=company.normalized_website,
            source_name=company.source_name,
            source_url=company.source_url,
            employee_count=company.employee_count,
            industry=company.industry,
            location=company.location,
            funding_stage=company.funding_stage,
            careers_url=company.careers_url,
            hiring_status=company.hiring_status,
            created_at=company.created_at,
            updated_at=company.updated_at,
            last_verified_at=company.last_verified_at,
        )

    def create_company(self, company: Union[Company, CompanyModel]) -> CompanyModel:
        """Create and persist a new company record."""
        model = self._to_model(company)
        self.session.add(model)
        self.session.flush()
        return model

    def get_company_by_id(self, company_id: int) -> Optional[CompanyModel]:
        """Retrieve a company by its primary key ID."""
        stmt = select(CompanyModel).where(CompanyModel.id == company_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_company_by_website(self, website: str) -> Optional[CompanyModel]:
        """Retrieve a company matching the normalized website."""
        norm_site = normalize_website(website)
        stmt = select(CompanyModel).where(CompanyModel.normalized_website == norm_site)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_company_by_normalized_name(self, name: str) -> Optional[CompanyModel]:
        """Retrieve a company matching normalized name."""
        norm_name = normalize_name(name)
        stmt = select(CompanyModel).where(CompanyModel.normalized_name == norm_name)
        return self.session.execute(stmt).scalars().first()

    def list_companies(self, limit: int = 100, offset: int = 0) -> List[CompanyModel]:
        """List companies with pagination."""
        stmt = (
            select(CompanyModel)
            .order_by(CompanyModel.company_name)
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(stmt).scalars().all())

    def upsert_company_with_status(
        self, company: Union[Company, CompanyModel]
    ) -> Tuple[CompanyModel, bool]:
        """Upsert a company returning the persisted model and a boolean (True if created, False if updated)."""
        if isinstance(company, CompanyModel):
            norm_website = company.normalized_website
            norm_name = company.normalized_name
        else:
            norm_website = company.normalized_website
            norm_name = company.normalized_name

        existing = self.get_company_by_website(norm_website)
        if not existing and norm_name:
            candidate = self.get_company_by_normalized_name(norm_name)
            if candidate and (
                candidate.normalized_website.split("/", 1)[0] == norm_website.split("/", 1)[0]
                or _is_indirect_company_url(company.website)
                or _is_indirect_company_url(candidate.website)
            ):
                existing = candidate

        now = datetime.now(timezone.utc)

        if existing:
            fields_to_check = [
                "company_name",
                "website",
                "employee_count",
                "industry",
                "location",
                "funding_stage",
                "careers_url",
                "hiring_status",
            ]
            for attr in fields_to_check:
                incoming_val = getattr(company, attr, None)
                if incoming_val is not None and str(incoming_val).strip() != "":
                    if (
                        attr == "website"
                        and not _is_indirect_company_url(existing.website)
                        and _is_indirect_company_url(str(incoming_val))
                    ):
                        continue
                    setattr(existing, attr, incoming_val)

            existing.normalized_name = normalize_name(existing.company_name)
            existing.normalized_website = normalize_website(existing.website)
            existing.updated_at = now
            existing.last_verified_at = now
            self.session.flush()
            return existing, False

        new_model = self._to_model(company)
        new_model.last_verified_at = now
        self.session.add(new_model)
        self.session.flush()
        return new_model, True

    def upsert_company(self, company: Union[Company, CompanyModel]) -> CompanyModel:
        """Upsert a company avoiding duplicates without overwriting values with null."""
        model, _ = self.upsert_company_with_status(company)
        return model


class JobRepository:
    """Handles database persistence and deduplication for advertised jobs."""

    def __init__(self, session: Session, repost_options: dict | None = None) -> None:
        self.session = session
        self.repost_options = repost_options or {}

    def _similar_job(self, company_id, fingerprint, job, cutoff):
        recent = self.session.scalars(select(JobModel).where(
            JobModel.company_id == company_id, JobModel.last_seen_at >= cutoff,
        ).order_by(JobModel.first_seen_at, JobModel.id))
        threshold = int(self.repost_options.get("hamming_distance_threshold", 3))
        for candidate in recent:
            if candidate.location and job.location and normalize_name(candidate.location) != normalize_name(job.location):
                continue
            if not candidate.description_simhash:
                candidate.description_simhash = description_simhash(candidate.description)
            if candidate.description_simhash and hamming_distance(fingerprint, candidate.description_simhash) <= threshold:
                return candidate
        return None

    def _record_relist(self, existing, identity, now, cutoff):
        if not identity or (identity == existing.normalized_job_url and not existing.repost_count):
            return
        sightings = list(self.session.scalars(select(JobRelistModel).where(JobRelistModel.job_id == existing.id)))
        if identity != existing.normalized_job_url and not any(item.identity == identity for item in sightings):
            # Store the original identity so a later canonical URL update cannot count it as a relist.
            if not any(item.identity == existing.normalized_job_url for item in sightings):
                original = JobRelistModel(job_id=existing.id, identity=existing.normalized_job_url,
                                          observed_at=existing.first_seen_at)
                self.session.add(original)
                sightings.append(original)
            relist = JobRelistModel(job_id=existing.id, identity=identity, observed_at=now)
            self.session.add(relist)
            sightings.append(relist)
        days = {item.observed_at.date() for item in sightings if item.observed_at.date() >= cutoff.date()}
        days.discard(existing.first_seen_at.date())
        existing.repost_count = len(days)
        existing.is_ghost_job = len(days) >= int(self.repost_options.get("ghost_job_min_relists", 2))

    def _to_model(self, job: Union[Job, JobModel]) -> JobModel:
        """Convert domain Job to JobModel if needed."""
        if isinstance(job, JobModel):
            return job
        if job.company_id is None:
            raise ValueError("Job must be linked to a company_id before persistence.")
        return JobModel(
            company_id=job.company_id,
            job_title=job.job_title,
            normalized_title=job.normalized_title,
            description=job.description,
            location=job.location,
            employment_type=job.employment_type,
            experience_level=job.experience_level,
            job_url=job.job_url,
            normalized_job_url=job.normalized_job_url,
            source_name=job.source_name,
            source_job_id=job.source_job_id,
            posted_at=job.posted_at,
            first_seen_at=job.first_seen_at,
            last_seen_at=job.last_seen_at,
            status=job.status,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    def create_job(self, job: Union[Job, JobModel]) -> JobModel:
        """Create and persist a new job record."""
        model = self._to_model(job)
        self.session.add(model)
        self.session.flush()
        return model

    def get_job_by_id(self, job_id: int) -> Optional[JobModel]:
        """Retrieve a job by its primary key ID."""
        stmt = select(JobModel).where(JobModel.id == job_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_jobs_by_company(self, company_id: int) -> List[JobModel]:
        """Retrieve all jobs belonging to a specific company."""
        stmt = (
            select(JobModel)
            .where(JobModel.company_id == company_id)
            .order_by(JobModel.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_jobs(self, limit: int = 100, offset: int = 0) -> List[JobModel]:
        """List all jobs with pagination."""
        stmt = (
            select(JobModel)
            .order_by(JobModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(stmt).scalars().all())

    def upsert_job_with_status(
        self, job: Union[Job, JobModel]
    ) -> Tuple[JobModel, bool]:
        """Upsert a job returning the persisted model and a boolean (True if created, False if updated)."""
        company_id = job.company_id
        if company_id is None:
            raise ValueError("Job must be linked to a company_id before persistence.")

        source_name = job.source_name
        source_job_id = job.source_job_id
        norm_url = (
            job.normalized_job_url
            if hasattr(job, "normalized_job_url")
            else normalize_job_url(job.job_url)
        )
        norm_title = (
            job.normalized_title
            if hasattr(job, "normalized_title")
            else normalize_name(job.job_title)
        )

        existing: Optional[JobModel] = None

        # 1. Match by source-specific job ID
        if source_job_id and source_job_id.strip():
            stmt = select(JobModel).where(
                JobModel.company_id == company_id,
                JobModel.source_name == source_name,
                JobModel.source_job_id == source_job_id.strip(),
            )
            existing = self.session.execute(stmt).scalars().first()

        # 2. Match by normalized job URL
        if not existing and norm_url:
            stmt = select(JobModel).where(
                JobModel.company_id == company_id,
                JobModel.normalized_job_url == norm_url,
            )
            existing = self.session.execute(stmt).scalars().first()

        company = self.session.get(CompanyModel, company_id)
        key = canonical_job_key(company.website, job.job_title, job.location) if company else None
        if not existing and key:
            matches = list(self.session.scalars(select(JobModel).where(
                JobModel.company_id == company_id, JobModel.canonical_job_key == key,
                JobModel.source_name != source_name,
            ).limit(2)))
            if len(matches) == 1:
                existing = matches[0]
                if source_name == "freehire":
                    return existing, False

        # 4. Match by normalized title and location for the same company
        if not existing and norm_title:
            location_val = job.location.strip().lower() if job.location else None
            stmt = select(JobModel).where(
                JobModel.company_id == company_id,
                JobModel.normalized_title == norm_title,
            )
            candidates = list(self.session.execute(stmt).scalars().all())
            for candidate in candidates:
                cand_loc = (
                    candidate.location.strip().lower() if candidate.location else None
                )
                if location_val is None or cand_loc is None or location_val == cand_loc:
                    existing = candidate
                    break

        now = datetime.now(timezone.utc)
        fingerprint = description_simhash(job.description) if self.repost_options else None
        similar = False
        if fingerprint:
            cutoff = now - timedelta(days=int(self.repost_options.get("ghost_job_window_days", 90)))
            if existing is None:
                existing = self._similar_job(company_id, fingerprint, job, cutoff)
            if existing is not None:
                stored_hash = existing.description_simhash or description_simhash(existing.description)
                similar = bool(stored_hash and hamming_distance(fingerprint, stored_hash) <= int(
                    self.repost_options.get("hamming_distance_threshold", 3)
                ))
                if similar:
                    self._record_relist(existing, norm_url, now, cutoff)

        if existing:
            if fingerprint and (not existing.description_simhash or existing.normalized_job_url == norm_url):
                existing.description_simhash = fingerprint
            if (similar and ":" in source_name and existing.source_name == source_name
                    and existing.normalized_job_url != norm_url and existing.status not in {"skipped", "applied"}
                    and (existing.status == "closed" or existing.liveness_status == "expired")):
                existing.job_url = job.job_url
                existing.normalized_job_url = norm_url
                existing.source_job_id = source_job_id
                existing.description_simhash = fingerprint
                existing.liveness_status = "unverified"
                existing.last_liveness_check_at = None
                existing.missing_ats_polls = 0
            fields_to_check = [
                "job_title",
                "description",
                "location",
                "employment_type",
                "experience_level",
                "posted_at",
            ]
            for attr in fields_to_check:
                incoming_val = getattr(job, attr, None)
                if incoming_val is not None:
                    if isinstance(incoming_val, str) and not incoming_val.strip():
                        continue
                    setattr(existing, attr, incoming_val)

            existing.last_seen_at = now
            if existing.source_name == source_name:
                existing.canonical_job_key = key or existing.canonical_job_key
                if source_name == "freehire":
                    existing.last_verified_open_at = now
            elif (existing.source_name == "freehire" and existing.normalized_job_url == norm_url
                  and existing.status not in {"skipped", "applied"}):
                # The native board is authoritative once it observes this posting.
                existing.source_name = source_name
                existing.source_job_id = source_job_id
            existing.updated_at = now
            if existing.status not in {"skipped", "applied"}:
                existing.status = getattr(job, "status", "open") or "open"
            self.session.flush()
            return existing, False

        new_model = self._to_model(job)
        if fingerprint:
            new_model.description_simhash = fingerprint
        new_model.canonical_job_key = key
        if source_name == "freehire":
            new_model.last_verified_open_at = now
        new_model.first_seen_at = now
        new_model.last_seen_at = now
        self.session.add(new_model)
        self.session.flush()
        return new_model, True

    def upsert_job(self, job: Union[Job, JobModel]) -> JobModel:
        """Upsert a job avoiding duplicates and updating timestamps."""
        model, _ = self.upsert_job_with_status(job)
        return model
