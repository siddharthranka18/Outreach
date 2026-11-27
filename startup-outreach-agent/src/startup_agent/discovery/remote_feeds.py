"""Cheap public feeds with explicit country permission and reviewed employer identity."""
from collections import Counter
import logging
import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.discovery.andhra_startup_map import _is_target_role
from startup_agent.discovery.portfolio import india_location
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_name, normalize_job_url
from startup_agent.discovery.employer_lookup import known_employer

FEEDS = {
    "remoteok": ("https://remoteok.com/api", "remoteok.com", "Remote OK"),
    "jobicy": ("https://jobicy.com/api/v2/remote-jobs", "jobicy.com", "Jobicy"),
    "working_nomads": ("https://www.workingnomads.com/api/exposed_jobs/", "workingnomads.com", "Working Nomads"),
}
EARLY = re.compile(r"\b(?:intern(?:ship)?|junior|entry[- ]level|new[- ]grad|fresher)\b", re.I)
logger = logging.getLogger(__name__)


def wwr_programming_entries(content):
    """Yield RSS postings with evidence they are open to applicants in India."""
    feed = BeautifulSoup(content, "xml")
    if not feed.find("rss"):
        raise ValueError("Expected We Work Remotely RSS.")
    for item in feed.find_all("item"):
        title, link = item.find("title"), item.find("link")
        if title is None or link is None:
            continue
        url = link.get_text(" ", strip=True)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {"weworkremotely.com", "www.weworkremotely.com"}:
            continue
        company, _, role = title.get_text(" ", strip=True).partition(":")
        description = item.find("description")
        description_html = description.get_text() if description else ""
        region = " / ".join(node.get_text(" ", strip=True) for node in item.find_all(["region", "country"]))
        labels = [label.strip() for label in re.split(r"[/,;|]", region) if label.strip()]
        exclusion = r"\b(?:except|excluding|outside|not including|restricted to|only)\b"
        if re.search(r"\b(?:except|excluding|outside|not including)\s+India\b", region, re.I):
            location = ""
        elif any(re.fullmatch(r"India", label, re.I) for label in labels):
            location = "India"
        elif not re.search(exclusion, region, re.I) and any(
            re.fullmatch(r"Worldwide|Anywhere in the World|Global Remote", label, re.I) for label in labels
        ):
            location = "Worldwide"
        elif not region:
            plain = BeautifulSoup(description_html, "html.parser").get_text(" ", strip=True)
            location = "Worldwide" if re.search(
                r"\b(?:region|location|remote)\s*:\s*Anywhere in the World\b(?!\s*[,(-]?\s*(?:except|excluding))",
                plain, re.I,
            ) else ""
        else:
            location = ""
        yield company.strip(), role.strip(), url, description_html, location


class RemoteFeedDiscoverySource(BaseDiscoverySource):
    def __init__(self, employers, name, enabled=True, http_client=None):
        super().__init__(name=name, enabled=enabled)
        self.employers = employers
        self.http_client = http_client or HttpClient(public_only=True)
        self.fetched_count = 0
        self.rejections = Counter()

    def discover(self):
        if not self.is_enabled(): return DiscoveryResult()
        endpoint, source_host, _ = FEEDS[self.name]
        payload = self.http_client.get(endpoint).json()
        listings = payload["jobs"] if self.name == "jobicy" else payload
        companies, jobs = {}, {}
        for row in listings:
            title = row.get("position") if self.name == "remoteok" else row.get("jobTitle") if self.name == "jobicy" else row.get("title")
            if not title: continue  # Remote OK's first object is API metadata.
            self.fetched_count += 1
            if not _is_target_role(title) or not EARLY.search(title):
                self.rejections["No technical early-career title"] += 1
                continue
            location = row.get("jobGeo") if self.name == "jobicy" else row.get("location")
            # Feed geography must explicitly permit India/worldwide. Remote alone never qualifies.
            label = india_location(location or "")
            if not label:
                self.rejections["No explicit India/worldwide permission"] += 1
                continue
            name = row.get("companyName") if self.name == "jobicy" else row.get("company_name") if self.name == "working_nomads" else row.get("company")
            employer = known_employer(name,self.employers,row.get('company_website') or row.get('companyWebsite'))
            if not employer:
                self.rejections["Employer domain/size not reviewed"] += 1
                continue
            url = row.get("url") or ""
            if urlsplit(url).scheme != "https" or (urlsplit(url).hostname or "").removeprefix("www.") != source_host:
                self.rejections["Invalid source posting URL"] += 1
                continue
            domain, evidence = employer
            website = "https://" + domain
            companies[domain] = Company(company_name=name, website=website, employee_count=evidence.get("employee_count"),
                source_name=self.name, source_url=evidence["source_url"], careers_url=evidence.get("careers_url"))
            description = row.get("jobDescription") if self.name == "jobicy" else row.get("description")
            jobs[normalize_job_url(url)] = Job(job_title=title, job_url=url, source_name=self.name,
                company_name=name, company_website=website, location=label,
                description=BeautifulSoup(description or "", "html.parser").get_text(" ", strip=True),
                source_job_id=str(row.get("id") or url), status="open")
        logger.info("%s: fetched=%d normalized=%d; rejected=%s", self.name, self.fetched_count, len(jobs), dict(self.rejections))
        return DiscoveryResult(companies=list(companies.values()), jobs=list(jobs.values()))
