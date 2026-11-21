"""Read bounded early-career searches from Freehire's public API."""

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import logging
import re
import time
from urllib.parse import urlsplit

import httpx
from sqlalchemy import or_, select

from startup_agent.database.repositories import _is_indirect_company_url
from startup_agent.database.models import JobModel
from startup_agent.discovery.andhra_startup_map import _is_target_role
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.discovery.portfolio import india_location
from startup_agent.discovery.remote_feeds import EARLY
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_job_url, normalize_name, normalize_website
from startup_agent.utils.posting_guard import sanitize_untrusted_text

ROOT = "https://freehire.me/api/v1"
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,199}")
CATEGORIES = "software_engineering,backend,frontend,fullstack,mobile,devops,data_engineering,data_science,data_analytics,ml_ai,ai_engineering,qa"
logger = logging.getLogger(__name__)


def https_url(value):
    try:
        parsed = urlsplit(value or "")
        if parsed.scheme == "https" and parsed.hostname and not parsed.username and parsed.port in (None, 443):
            return value
    except (TypeError, ValueError):
        pass
    return ""


class FreehireDiscoverySource(BaseDiscoverySource):
    def __init__(self, employers, cache_path, options, http_client=None):
        super().__init__(name="freehire", enabled=True)
        self.employers = employers
        self.cache_path = cache_path
        self.options = options
        self.http_client = http_client or HttpClient(timeout=10, max_retries=2, public_only=True)
        self.fetched_count = 0
        self.rejections = Counter()

    def request(self, path, params=None):
        return self.http_client.get(f"{ROOT}/{path}", params=params, allowed_domain="freehire.me").json()

    def facets(self):
        try:
            if time.time() - self.cache_path.stat().st_mtime < 86400:
                return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        facets = self.request("jobs/facets")["data"]["facets"]
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(facets), encoding="utf-8")
        temporary.replace(self.cache_path)
        return facets

    def discover(self):
        facets = self.facets()
        if not isinstance(facets, dict) or not facets:
            raise ValueError("Freehire returned no facet vocabulary.")
        domains = {domain: evidence for domain, evidence in self.employers.values()}
        companies, jobs, resolved_companies = {}, {}, {}
        lookups = max(0, min(12, int(self.options.get("company_lookups", 8))))
        limit = max(1, min(25, int(self.options.get("page_size", 25))))
        pages = max(1, min(2, int(self.options.get("max_pages_per_query", 2))))
        for scope in ({"countries": "in", "seniority": "intern,junior"},
                      {"regions": "global", "work_mode": "remote", "seniority": "intern"}):
            filters = {**scope, "category": CATEGORIES}
            for name, values in filters.items():
                vocabulary = facets.get(name)
                if not isinstance(vocabulary, dict) or not set(values.split(",")) <= vocabulary.keys():
                    raise ValueError(f"Freehire facet changed: {name}.")
            for page in range(pages):
                payload = self.request("agent/jobs/search", {
                    **filters, "limit": limit, "offset": page * limit,
                    "posted_within_days": 7,
                })
                meta = payload.get("meta") or {}
                if meta.get("ignored_params") or meta.get("ignored_values"):
                    raise ValueError("Freehire rejected a search filter.")
                listings = payload["data"]
                if not isinstance(listings, list):
                    raise ValueError("Freehire search did not return a job list.")
                self.fetched_count += len(listings)
                for row in listings[:limit]:
                    if not isinstance(row, dict) or row.get("closed_at"):
                        continue
                    title, name, slug = (str(row.get(key) or "").strip()
                                         for key in ("title", "company", "public_slug"))
                    url = https_url(row.get("url"))
                    if not (url and name and SLUG.fullmatch(slug) and EARLY.search(title) and _is_target_role(title)):
                        self.rejections["Missing posting identity or technical early-career title"] += 1
                        continue
                    location = str(row.get("location") or "")
                    if "in" in (row.get("countries") or []):
                        location = location if re.search(r"\bIndia\b", location, re.I) else f"{location}, India".lstrip(", ")
                    elif ("global" in (row.get("regions") or []) and not row.get("countries")
                          and re.fullmatch(r"remote|fully remote|global|worldwide|", location, re.I)):
                        location = "Remote / Worldwide"
                    if not india_location(location):
                        self.rejections["No explicit India/worldwide permission"] += 1
                        continue
                    company_slug = str(row.get("company_slug") or "")
                    raw_website = row.get("company_website") or row.get("company_domain") or ""
                    if isinstance(raw_website, str) and raw_website and "://" not in raw_website:
                        raw_website = "https://" + raw_website
                    website = https_url(raw_website)
                    if not website and SLUG.fullmatch(company_slug):
                        if company_slug not in resolved_companies and lookups:
                            lookups -= 1
                            try:
                                entity = self.request(f"companies/{company_slug}", {"limit": 1})["data"]["company"]
                                info = entity.get("company_info") or {}
                                url_value = (entity.get("website") or entity.get("website_url")
                                             or info.get("website") or info.get("website_url")
                                             or entity.get("domain") or info.get("domain"))
                                if isinstance(url_value, str) and "://" not in url_value:
                                    url_value = "https://" + url_value
                                resolved_companies[company_slug] = https_url(url_value)
                            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                                resolved_companies[company_slug] = ""
                        website = resolved_companies.get(company_slug, "")
                    if not website:
                        known = self.employers.get(normalize_name(name))
                        if known:
                            website = https_url("https://" + known[0])
                    if not website or _is_indirect_company_url(website):
                        self.rejections["Unresolved employer domain"] += 1
                        continue
                    domain = normalize_website(website).split("/", 1)[0]
                    evidence = domains.get(domain, {})
                    company_url = f"https://freehire.me/companies/{company_slug}" if SLUG.fullmatch(company_slug) else url
                    companies[domain] = Company(company_name=name, website=f"https://{domain}",
                        employee_count=evidence.get("employee_count"), source_name=self.name,
                        source_url=evidence.get("source_url") or company_url,
                        careers_url=evidence.get("careers_url"))
                    description, _ = sanitize_untrusted_text(str(row.get("description") or "")[:50000], max_chars=16000)
                    try:
                        posted = datetime.fromisoformat(row["posted_at"]) if row.get("posted_at") else None
                    except (TypeError, ValueError):
                        posted = None
                    jobs[normalize_job_url(url)] = Job(job_title=title, job_url=url, source_name=self.name,
                        company_name=name, company_website=f"https://{domain}", location=location,
                        description=description, source_job_id=slug, posted_at=posted)
                if len(listings) < limit:
                    break
        return DiscoveryResult(list(companies.values()), list(jobs.values()))


def verify_freehire_jobs(session, client=None, now=None):
    """Recheck old stored hits via job detail. Search absence is not closure."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=20)
    client = client or HttpClient(timeout=5, max_retries=0, public_only=True)
    jobs = list(session.scalars(select(JobModel).where(
        JobModel.source_name == "freehire", JobModel.status == "open",
        JobModel.last_seen_at < cutoff,
        or_(JobModel.last_verified_open_at.is_(None), JobModel.last_verified_open_at < cutoff),
    ).order_by(JobModel.last_verified_open_at, JobModel.last_seen_at).limit(10)))
    for job in jobs:
        slug = job.source_job_id or ""
        if not SLUG.fullmatch(slug):
            continue
        try:
            result = client.get(f"{ROOT}/jobs/{slug}", allowed_domain="freehire.me").json()["data"]
            if result.get("public_slug") != slug:
                continue
            if result.get("closed_at"):
                job.status = "closed"
            elif "closed_at" in result:
                job.last_verified_open_at = now
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {404, 410}:
                job.status = "closed"
            elif error.response.status_code == 429 or error.response.status_code >= 500:
                break
        except (httpx.HTTPError, ValueError, KeyError, AttributeError, TypeError):
            logger.info("Freehire expiry check unavailable; keeping unverified postings.")
            break
