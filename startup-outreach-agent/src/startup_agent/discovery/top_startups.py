"""TopStartups.io startup and job discovery adapter."""

import logging
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from bs4 import BeautifulSoup
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_website

logger = logging.getLogger("startup_agent.discovery.top_startups")

TOP_STARTUPS_JOBS_URL = "https://topstartups.io/jobs/"


def _clean_company_website(raw_url: str) -> str:
    """Strip tracking parameters while keeping valid protocol and host."""
    parsed = urlparse(raw_url)
    clean_params = [(k, v) for k, v in parse_qsl(parsed.query) if not k.startswith("utm_")]
    cleaned_query = urlencode(clean_params)
    return urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path, "", cleaned_query, ""))


class TopStartupsDiscoverySource(BaseDiscoverySource):
    """Discovers startups and open roles from TopStartups.io directory."""

    def __init__(
        self,
        name: str = "top_startups",
        enabled: bool = True,
        url: str = TOP_STARTUPS_JOBS_URL,
        http_client: Optional[HttpClient] = None,
    ) -> None:
        super().__init__(name=name, enabled=enabled)
        self.url = url
        self.http_client = http_client or HttpClient()

    def discover(self) -> DiscoveryResult:
        """Fetch and parse TopStartups.io job and startup listings."""
        if not self.is_enabled():
            return DiscoveryResult()

        logger.info("Executing TopStartups.io discovery at %s...", self.url)
        resp = self.http_client.get(self.url)
        soup = BeautifulSoup(resp.text, "html.parser")

        items = soup.find_all("div", class_="infinite-item")
        if not items:
            # Fallback selector for different layout variations
            items = soup.select(".card-body, #item-card-filter")

        companies: List[Company] = []
        jobs: List[Job] = []
        seen_websites = set()

        for item in items:
            try:
                # 1. Company Name and Website
                company_link = item.find("a", id="startup-website-link") or item.find("a", href=True)
                if not company_link:
                    continue

                raw_website = company_link.get("href", "").strip()
                if not raw_website or raw_website.startswith("#") or "topstartups.io/jobs" in raw_website:
                    continue

                clean_website = _clean_company_website(raw_website)
                company_name_tag = company_link.find(["h7", "h6", "h5", "h4", "span"])
                company_name = company_name_tag.get_text(strip=True) if company_name_tag else company_link.get_text(strip=True)

                if not company_name:
                    continue

                # Employee size tag
                employee_tag = item.find(id="company-size-tags") or item.find("span", class_="badge")
                employee_count = employee_tag.get_text(strip=True) if employee_tag else None

                norm_site = normalize_website(clean_website)
                if norm_site not in seen_websites:
                    company = Company(
                        company_name=company_name,
                        website=clean_website,
                        source_name=self.name,
                        source_url=self.url,
                        employee_count=employee_count,
                        hiring_status="Actively Hiring",
                    )
                    companies.append(company)
                    seen_websites.add(norm_site)

                # 2. Advertised Job Title and URL
                job_title_tag = item.find(id="job-title") or item.find("h5")
                if job_title_tag:
                    job_title = job_title_tag.get_text(strip=True)
                    # Check parent anchor for application link
                    parent_a = job_title_tag.find_parent("a") or item.find("a", href=lambda h: h and ("ashbyhq" in h or "greenhouse" in h or "lever.co" in h or "/job/" in h))
                    job_url = parent_a.get("href", "").strip() if parent_a else None

                    if job_title and job_url:
                        # Extract location and experience metadata
                        location = None
                        exp_level = None
                        for h7 in item.find_all("h7"):
                            text = h7.get_text(strip=True)
                            if "Experience:" in text:
                                exp_level = text.replace("Experience:", "").strip()
                            elif any(icon in str(h7) for icon in ["map-marker", "fa-map"]):
                                location = text

                        job = Job(
                            job_title=job_title,
                            job_url=job_url,
                            source_name=self.name,
                            company_name=company_name,
                            company_website=clean_website,
                            location=location,
                            experience_level=exp_level,
                            status="open",
                        )
                        jobs.append(job)

            except Exception as exc:
                logger.debug("Skipping unparseable TopStartups item: %s", exc)
                continue

        logger.info(
            "TopStartups.io discovery finished: extracted %d companies and %d jobs.",
            len(companies),
            len(jobs),
        )
        return DiscoveryResult(companies=companies, jobs=jobs)

