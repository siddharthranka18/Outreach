"""Latest monthly HN hiring thread; post emails are unverified leads only."""
import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.discovery.andhra_startup_map import _is_target_role
from startup_agent.discovery.portfolio import india_location
from startup_agent.discovery.direct_ats import extract_ats_target
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_name

API = "https://hn.algolia.com/api/v1"
EARLY = re.compile(r"\b(?:intern(?:ship)?|junior|new[- ]grad|entry[- ]level|freshers?)\b", re.I)
EMAIL = re.compile(r"[a-z0-9._+%-]+@[a-z0-9.-]+\.[a-z]{2,}", re.I)
INDIRECT = {"linkedin.com", "github.com", "news.ycombinator.com", "wellfound.com", "forms.gle"}


def parse_comment(comment, employers):
    if comment.get("author") is None or not comment.get("text"):
        return None
    page = BeautifulSoup(comment["text"], "html.parser")
    body = page.get_text(" ", strip=True)
    heading = body.split("|")[0].strip()[:160]
    name = heading.split(" - ")[0].strip()
    location = india_location(body)
    header = page.get_text("\n", strip=True).splitlines()[0]
    role = next((part.strip() for part in header.split("|") if _is_target_role(part)), None)
    title = role or " | ".join(body.split("|")[:5])[:220]
    if not location or not _is_target_role(title) or not (EARLY.search(body) or EMAIL.search(body)):
        return None
    urls = [str(a["href"]) for a in page.select("a[href]") if urlsplit(str(a["href"])).scheme == "https"]
    evidence = employers.get(normalize_name(name))
    domain = evidence[0] if evidence else None
    for url in urls:
        host = (urlsplit(url).hostname or "").removeprefix("www.")
        if not domain and host not in INDIRECT and not extract_ats_target(url, name, url):
            domain = host
    if not domain:
        return None
    evidence = evidence[1] if evidence else {}
    source = f"https://news.ycombinator.com/item?id={comment['id']}"
    # Prefer an actual posting/careers link over the employer homepage.
    job_url = next((u for u in urls if extract_ats_target(u, name, "https://"+domain)
                    or re.search(r"/(?:jobs?|careers?|positions?)(?:/|$)", urlsplit(u).path)), source)
    company = Company(company_name=name, website="https://"+domain, employee_count=evidence.get("employee_count"),
        source_name="hn_hiring", source_url=source, careers_url=evidence.get("careers_url"))
    # Existing routing recognizes inboxes in job descriptions. Redact post emails
    # here so that an HN lead cannot become a contact through that older path.
    safe_body = EMAIL.sub("[contact withheld]", body)
    job = Job(job_title=EMAIL.sub("[contact withheld]", title), job_url=job_url, company_name=name, company_website=company.website,
        source_name="hn_hiring", source_job_id=str(comment["id"]), description=safe_body, location=location, status="open")
    leads = [{"domain": domain, "email": a.lower(), "evidence_url": source, "verified": False}
             for a in sorted(set(EMAIL.findall(body))) if a.rsplit("@",1)[1].lower() == domain.lower()]
    return company, job, leads


def current_hn_contact(hint, domain, now=None):
    """The user opted into current top-level monthly hiring posts as evidence."""
    now=now or datetime.now(timezone.utc)
    try:
        fetched=datetime.fromisoformat(hint.get("checked_at", ""))
        posted=datetime.fromisoformat(hint.get("posted_at", ""))
        return bool(hint.get("evidence_type") == "hn_monthly_hiring" and hint.get("top_level") is True
            and hint.get("thread_author") == "whoishiring" and str(hint.get("thread_id","")).isdigit()
            and hint.get("author") and hint.get("domain") == domain
            and EMAIL.fullmatch(hint.get("email", "")) and hint["email"].rsplit('@',1)[1] == domain
            and re.fullmatch(r"https://news\.ycombinator\.com/item\?id=\d+", hint.get("evidence_url",""))
            and timedelta(0) <= now-fetched <= timedelta(days=2)
            and timedelta(0) <= now-posted <= timedelta(days=45))
    except (ValueError,TypeError): return False


class HnHiringDiscoverySource(BaseDiscoverySource):
    def __init__(self, employers=None, name="hn_hiring", enabled=True, http_client=None, leads_path=None):
        super().__init__(name=name, enabled=enabled)
        self.employers = employers or {}
        self.http_client = http_client or HttpClient(public_only=True)
        self.leads_path = Path(leads_path) if leads_path else None
        self.fetched_count = 0

    def discover(self):
        if not self.is_enabled(): return DiscoveryResult()
        stories = self.http_client.get(API+"/search_by_date", params={"tags":"story,author_whoishiring",
            "query":"Ask HN: Who is hiring?", "hitsPerPage":30}).json()["hits"]
        story = next((s for s in stories if s.get("author") == "whoishiring"
            and re.fullmatch(r"Ask HN: Who is hiring\? \([A-Za-z]+ \d{4}\)", s.get("title", ""))), None)
        if not story: raise ValueError("No latest monthly hiring thread found")
        identifier = str(story["objectID"])
        if not identifier.isdigit(): raise ValueError("Invalid HN thread identifier")
        thread = self.http_client.get(API+"/items/"+identifier).json()
        companies, jobs, leads = {}, {}, []
        for comment in thread.get("children", [])[:500]:
            if comment.get("type") != "comment": continue
            self.fetched_count += 1
            result = parse_comment(comment, self.employers)
            if not result: continue
            company, job, emails = result
            for email in emails:
                email.update(evidence_type="hn_monthly_hiring",top_level=True,thread_author="whoishiring",
                    thread_id=identifier, author=comment.get("author"), posted_at=comment.get("created_at"),
                    checked_at=datetime.now(timezone.utc).isoformat())
            companies[company.website] = company
            jobs[job.job_url] = job
            leads.extend(emails)
        if self.leads_path:
            self.leads_path.parent.mkdir(parents=True, exist_ok=True)
            self.leads_path.write_text(json.dumps(leads, indent=2), encoding="utf-8")
        return DiscoveryResult(companies=list(companies.values()), jobs=list(jobs.values()))
