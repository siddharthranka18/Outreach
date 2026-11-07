"""Y Combinator startup directory discovery adapter."""

import logging
import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin
from bs4 import BeautifulSoup
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient

logger = logging.getLogger("startup_agent.discovery.yc")

# Default YC public directory search configuration
DEFAULT_YC_APP_ID = "45BWZJ1SGC"
DEFAULT_YC_INDEX = "YCCompany_production"
YC_DIRECTORY_URL = "https://www.ycombinator.com/companies"


class YCombinatorDiscoverySource(BaseDiscoverySource):
    """Discovers startups from the public Y Combinator company directory."""

    def __init__(
        self,
        name: str = "y_combinator",
        enabled: bool = True,
        max_companies: int = 75,
        max_employees: int = 200,
        include_jobs: bool = True,
        target_region_groups: Optional[List[List[str]]] = None,
        http_client: Optional[HttpClient] = None,
    ) -> None:
        super().__init__(name=name, enabled=enabled)
        self.max_companies = max_companies
        self.max_employees = max_employees
        self.include_jobs = include_jobs
        self.target_region_groups = target_region_groups or [
            ["India", "South Asia"],
            ["Fully Remote", "Remote"],
        ]
        self.http_client = http_client or HttpClient()

    @staticmethod
    def _is_early_career_candidate(title: str, card_text: str) -> bool:
        """Avoid detail-page requests for roles that cannot fit a fresher."""
        combined = f"{title} {card_text}".lower()
        patterns = [
            r"\bintern(?:ship)?\b",
            r"\bnew grad(?:uate)?\b",
            r"\bgraduate\b",
            r"\bentry[- ]level\b",
            r"\bjunior\b",
            r"\bapprentice\b",
            r"\bco-?op\b",
            r"\b0\s*(?:-|to)\s*2\s*years?\b",
            r"\bany\s*\(new grads? ok\)\b",
        ]
        return any(re.search(pattern, combined) for pattern in patterns)

    def _fetch_job_description(self, job_url: str) -> Optional[str]:
        """Fetch the public YC detail page and prefer its descriptive metadata."""
        try:
            response = self.http_client.get(job_url)
            soup = BeautifulSoup(response.text, "html.parser")
            meta = soup.find("meta", attrs={"name": "description"})
            if meta and meta.get("content"):
                return str(meta["content"]).strip()

            about_heading = soup.find(
                lambda tag: tag.name in {"h1", "h2", "h3"}
                and tag.get_text(" ", strip=True).lower() == "about the role"
            )
            if about_heading:
                chunks: List[str] = []
                for sibling in about_heading.find_all_next():
                    if sibling is not about_heading and sibling.name in {"h1", "h2"}:
                        break
                    if sibling.name in {"p", "li"}:
                        text = sibling.get_text(" ", strip=True)
                        if text:
                            chunks.append(text)
                if chunks:
                    return " ".join(chunks)
        except Exception as exc:
            logger.warning("Could not fetch YC job detail %s: %s", job_url, exc)
        return None

    def _discover_company_jobs(self, company: Company, slug: str) -> List[Job]:
        """Extract early-career roles from one public YC company jobs page."""
        jobs_url = f"https://www.ycombinator.com/companies/{slug}/jobs"
        try:
            response = self.http_client.get(jobs_url)
        except Exception as exc:
            logger.warning("Could not fetch YC jobs for %s: %s", company.company_name, exc)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        expected_prefix = f"/companies/{slug}/jobs/"
        jobs: List[Job] = []
        seen_urls = set()

        for link in soup.find_all("a", href=True):
            href = str(link.get("href", ""))
            if expected_prefix not in href:
                continue

            job_url = urljoin(YC_DIRECTORY_URL, href)
            if job_url in seen_urls:
                continue

            title = link.get_text(" ", strip=True)
            if not title:
                continue

            card = link.parent.parent if link.parent and link.parent.parent else link.parent
            card_parts = list(card.stripped_strings) if card else [title]
            card_text = " | ".join(card_parts)
            if not self._is_early_career_candidate(title, card_text):
                continue

            location = card_parts[1] if len(card_parts) > 1 else None
            experience_level = card_parts[-1] if len(card_parts) > 2 else None
            description = self._fetch_job_description(job_url)
            employment_type = "Internship" if re.search(r"\bintern", title, re.IGNORECASE) else "Full-time"
            source_job_id = href.rstrip("/").split("/")[-1].split("-", 1)[0]

            jobs.append(
                Job(
                    job_title=title,
                    job_url=job_url,
                    source_name="yc_jobs",
                    company_name=company.company_name,
                    company_website=company.website,
                    description=description,
                    location=location,
                    employment_type=employment_type,
                    experience_level=experience_level,
                    source_job_id=source_job_id,
                    status="open",
                )
            )
            seen_urls.add(job_url)

        return jobs

    def _get_algolia_credentials(self) -> Dict[str, str]:
        """Extract public Algolia credentials from YC directory page."""
        try:
            resp = self.http_client.get(YC_DIRECTORY_URL)
            match = re.search(r'window\.AlgoliaOpts\s*=\s*(\{.*?\});', resp.text)
            if match:
                import json
                opts = json.loads(match.group(1))
                return {
                    "app_id": opts.get("app", DEFAULT_YC_APP_ID),
                    "api_key": opts.get("key", ""),
                    "index": DEFAULT_YC_INDEX,
                }
        except Exception as exc:
            logger.warning("Could not dynamically extract YC Algolia options: %s", exc)

        return {
            "app_id": DEFAULT_YC_APP_ID,
            "api_key": "",
            "index": DEFAULT_YC_INDEX,
        }

    def discover(self) -> DiscoveryResult:
        """Fetch and normalize companies from Y Combinator directory."""
        if not self.is_enabled():
            return DiscoveryResult()

        logger.info("Executing Y Combinator discovery (target limit: %d)...", self.max_companies)
        creds = self._get_algolia_credentials()
        app_id = creds["app_id"]
        api_key = creds["api_key"]
        index_name = creds["index"]

        if not api_key:
            logger.error("Missing Algolia API key for Y Combinator discovery.")
            return DiscoveryResult()

        query_url = f"https://{app_id}-dsn.algolia.net/1/indexes/{index_name}/query"
        headers = {
            "X-Algolia-Application-Id": app_id,
            "X-Algolia-API-Key": api_key,
        }

        hits_by_id: Dict[str, Dict[str, Any]] = {}
        for region_group in self.target_region_groups:
            facet_filters = [
                ["isHiring:true"],
                [f"regions:{region}" for region in region_group],
            ]
            payload = {
                "params": (
                    f"hitsPerPage={self.max_companies}&query="
                    f"&facetFilters={quote_plus(json.dumps(facet_filters))}"
                    f"&numericFilters=team_size%3C%3D{self.max_employees}"
                )
            }
            response = self.http_client.post(
                query_url, json_data=payload, headers=headers
            )
            for hit in response.json().get("hits", []):
                hit_id = str(hit.get("objectID") or hit.get("id") or hit.get("slug") or "")
                if hit_id:
                    hits_by_id[hit_id] = hit

        hits = list(hits_by_id.values())

        companies: List[Company] = []
        jobs: List[Job] = []
        for hit in hits:
            name = hit.get("name")
            website = hit.get("website")
            slug = hit.get("slug")

            # Fall back to YC profile if company has no direct website listed
            if not website and slug:
                website = f"https://www.ycombinator.com/companies/{slug}"

            if not name or not website:
                continue

            # Determine employee count string
            team_size = hit.get("team_size")
            employee_count = str(team_size) if team_size is not None else None

            # Funding stage / Batch
            stage = hit.get("stage")
            batch = hit.get("batch")
            funding_stage = f"{stage} ({batch})" if stage and batch else (stage or batch)

            # Industry
            industry = hit.get("industry")
            subindustry = hit.get("subindustry")
            ind_val = subindustry or industry

            hiring_status = "Actively Hiring" if hit.get("isHiring") else None
            yc_url = f"https://www.ycombinator.com/companies/{slug}" if slug else YC_DIRECTORY_URL

            try:
                company = Company(
                    company_name=name.strip(),
                    website=website.strip(),
                    source_name=self.name,
                    source_url=yc_url,
                    employee_count=employee_count,
                    industry=ind_val,
                    location=hit.get("all_locations"),
                    funding_stage=funding_stage,
                    careers_url=yc_url,
                    hiring_status=hiring_status,
                )
                companies.append(company)
                if self.include_jobs and slug:
                    jobs.extend(self._discover_company_jobs(company, slug))
            except Exception as exc:
                logger.debug("Skipping malformed YC record '%s': %s", name, exc)
                continue

        logger.info(
            "Y Combinator discovery finished: extracted %d small companies and %d early-career jobs.",
            len(companies),
            len(jobs),
        )
        return DiscoveryResult(companies=companies, jobs=jobs)

