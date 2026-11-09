"""Read technical early-career listings from Hasjob's public Atom feed."""

from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from startup_agent.discovery.andhra_startup_map import _is_target_role
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient


FEED_URL = "https://hasjob.co/feed"
ATOM = {"atom": "http://www.w3.org/2005/Atom"}
EARLY_CAREER = re.compile(
    r"\b(?:intern(?:ship)?|freshers?|junior|entry[- ]level|trainee|apprentice)\b",
    re.IGNORECASE,
)


class HasjobDiscoverySource(BaseDiscoverySource):
    def __init__(self, name="hasjob", enabled=True, http_client=None):
        super().__init__(name=name, enabled=enabled)
        self.http_client = http_client or HttpClient()

    def discover(self) -> DiscoveryResult:
        if not self.is_enabled():
            return DiscoveryResult()

        feed = ElementTree.fromstring(self.http_client.get(FEED_URL).content)
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        companies = {}
        jobs = {}
        for entry in feed.findall("atom:entry", ATOM):
            title = entry.findtext("atom:title", "", ATOM).strip()
            technical = _is_target_role(title) or re.search(
                r"\b(?:ai/ml|cybersecurity|data science|forward deployed engineer)\b",
                title,
                re.IGNORECASE,
            )
            if not technical or not EARLY_CAREER.search(title):
                continue
            try:
                published = entry.findtext("atom:published", "", ATOM)
                posted_at = datetime.fromisoformat(published.removesuffix("Z"))
                if posted_at.tzinfo is None:
                    posted_at = posted_at.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if posted_at < cutoff:
                continue

            job_url = entry.findtext("atom:id", "", ATOM)
            if urlparse(job_url).hostname != "hasjob.co":
                continue
            content = BeautifulSoup(entry.findtext("atom:content", "", ATOM), "html.parser")
            employer = content.select_one("p > strong > a[href]")
            if employer is None:
                continue
            website = str(employer["href"])
            company_name = employer.get_text(" ", strip=True)
            parsed = urlparse(website)
            if not company_name or parsed.scheme not in {"https", "http"} or not parsed.hostname:
                continue

            company = Company(
                company_name=company_name, website=website,
                source_name=self.name, source_url=job_url,
            )
            companies.setdefault(company.normalized_website, company)
            jobs[job_url] = Job(
                job_title=title, job_url=job_url, source_name=self.name,
                company_name=company_name, company_website=website,
                location=entry.findtext("atom:location", "", ATOM) or None,
                description=content.get_text(" ", strip=True), posted_at=posted_at,
                status="open",
            )
        return DiscoveryResult(companies=list(companies.values()), jobs=list(jobs.values()))
