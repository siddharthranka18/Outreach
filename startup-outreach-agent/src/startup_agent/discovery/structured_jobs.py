"""Public JobPosting JSON-LD parsing shared by employer and Indian boards."""
import json
import logging
import re
from datetime import datetime,timezone
from urllib.parse import urlsplit, urljoin
from bs4 import BeautifulSoup
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.discovery.andhra_startup_map import _is_target_role
from startup_agent.discovery.portfolio import india_location
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_name

logger = logging.getLogger(__name__)
EARLY = re.compile(r"\b(?:intern(?:ship)?|junior|fresher|entry[- ]level|new[- ]grad)\b", re.I)

def jobposting_nodes(page):
    def walk(item):
        if isinstance(item, list):
            for child in item: yield from walk(child)
        elif isinstance(item, dict):
            if item.get("@type") == "JobPosting": yield item
            for key in ("@graph", "itemListElement", "item"):
                if key in item: yield from walk(item[key])
    nodes = []
    for node in page.select('script[type="application/ld+json"]'):
        try: nodes.extend(walk(json.loads(node.string or node.get_text())))
        except (ValueError, TypeError): continue
    return nodes


def parse_posting(row, source_name, source_url, employers, paid_only=False):
    if row.get('validThrough'):
        try:
            if datetime.fromisoformat(row['validThrough'].replace('Z','+00:00')).replace(tzinfo=None) < datetime.now(timezone.utc).replace(tzinfo=None):return None
        except ValueError:pass
    title = row.get("title") or ""
    description = BeautifulSoup(row.get("description") or "", "html.parser").get_text(" ",strip=True)
    if not _is_target_role(title) or not EARLY.search(title): return None
    if re.search(r"unpaid|campus ambassador|commission.only|training (?:fee|program)", title+" "+description, re.I): return None
    if paid_only:
        salary = row.get("baseSalary") or {}
        value = salary.get("value") or {}
        amount = value.get("minValue", value.get("value", 0)) if isinstance(value,dict) else value
        try:
            if float(amount) <= 0 or len(description) < 80: return None
        except (TypeError,ValueError): return None
        from startup_agent.matching.profile import CandidateProfile
        skills=CandidateProfile.load().all_skills
        overlap=sum(bool(re.search(r'(?<!\w)'+re.escape(skill)+r'(?!\w)',description,re.I)) for skill in skills)
        if overlap<2:return None
    raw_locations = row.get("jobLocation") or []
    if isinstance(raw_locations,dict): raw_locations = [raw_locations]
    places = []
    for location in raw_locations:
        address = location.get("address") or {}
        places.append(", ".join('India' if v=='IN' else str(v.get("name","") if isinstance(v,dict) else v) for k,v in address.items() if not k.startswith('@')))
    requirements = row.get("applicantLocationRequirements") or []
    if isinstance(requirements,dict): requirements=[requirements]
    places.extend(str(r.get("name", "")) for r in requirements)
    label = india_location(" / ".join(places).replace(" IN", " India"))
    if not label: return None
    org = row.get("hiringOrganization") or {}
    name = org.get("name") or ""
    known = employers.get(normalize_name(name))
    website = org.get("url") or org.get("sameAs") or ("https://"+known[0] if known else "")
    if isinstance(website,list): website = next((u for u in website if isinstance(u,str) and "linkedin.com" not in u), "")
    parsed=urlsplit(website)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username: return None
    if parsed.hostname in {"linkedin.com","www.linkedin.com",urlsplit(source_url).hostname}: return None
    domain=parsed.hostname.removeprefix("www.")
    evidence = known[1] if known and known[0] == domain else {}
    employees=org.get("numberOfEmployees") or {}
    size=None
    if isinstance(employees,dict) and employees.get("minValue") and employees.get("maxValue"):
        size=f"{employees['minValue']}-{employees['maxValue']}"
    size=evidence.get("employee_count") or size
    company=Company(company_name=name,website="https://"+domain,source_name=source_name,source_url=source_url,employee_count=size)
    job=Job(job_title=title,job_url=row.get("url") or source_url,company_name=name,company_website=company.website,
            source_name=source_name,description=description,location=label,
            employment_type=', '.join(row['employmentType']) if isinstance(row.get('employmentType'),list) else row.get("employmentType"),status="open")
    return company,job


class StructuredBoardSource(BaseDiscoverySource):
    def __init__(self,name,url,employers=None,options=None,http_client=None):
        super().__init__(name=name,enabled=True)
        self.url=url;self.employers=employers or {};self.options=options or {}
        self.http_client=http_client or HttpClient(public_only=True,max_retries=1)
        self.fetched_count=0

    def discover(self):
        page=BeautifulSoup(self.http_client.get(self.url).text,"html.parser")
        pages=[(self.url,page)]
        pattern=self.options.get("detail_pattern", r"/jobs?/")
        urls=list(dict.fromkeys(urljoin(self.url,a['href']) for a in page.select('a[href]')
                if re.search(pattern,a['href']) and urlsplit(urljoin(self.url,a['href'])).hostname==urlsplit(self.url).hostname))
        for url in urls[:min(int(self.options.get("max_details",20)),40)]:
            if url==self.url: continue
            try: pages.append((url,BeautifulSoup(self.http_client.get(url).text,'html.parser')))
            except Exception as exc: logger.warning("%s detail unavailable (%s)",self.name,type(exc).__name__)
        companies,jobs={},{}
        for url,soup in pages:
            for row in jobposting_nodes(soup):
                self.fetched_count+=1
                result=parse_posting(row,self.name,url,self.employers,self.options.get('paid_only',False))
                if result:
                    company,job=result;companies[company.website]=company;jobs[job.job_url]=job
        if not self.fetched_count:
            logger.warning("%s: no public JobPosting data; no private endpoint or login attempted.",self.name)
        return DiscoveryResult(companies=list(companies.values()),jobs=list(jobs.values()))
