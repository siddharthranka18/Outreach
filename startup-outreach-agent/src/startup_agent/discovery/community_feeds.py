"""Public internship JSON and programming RSS with conservative location checks."""
from datetime import datetime,timezone
from startup_agent.discovery.base import BaseDiscoverySource,DiscoveryResult
from startup_agent.discovery.andhra_startup_map import _is_target_role
from startup_agent.discovery.structured_jobs import parse_posting
from startup_agent.discovery.portfolio import india_location
from startup_agent.discovery.remote_feeds import wwr_programming_entries
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_name


class CommunityFeedSource(BaseDiscoverySource):
    def __init__(self,name,url,employers=None,http_client=None):
        super().__init__(name=name,enabled=True)
        self.url=url;self.employers=employers or {};self.http_client=http_client or HttpClient(public_only=True)
        self.fetched_count=0

    def discover(self):
        response=self.http_client.get(self.url)
        companies,jobs={},{}
        if self.name.startswith("simplify"):
            for row in response.json():
                self.fetched_count+=1
                if row.get('active') is not True or row.get('is_visible') is False: continue
                title=row.get('title') or ''
                if not _is_target_role(title): continue
                location=india_location(' / '.join(row.get('locations') or []))
                # US-centric repo: unqualified Remote does not establish India permission.
                if not location: continue
                name=row.get('company_name') or '';known=self.employers.get(normalize_name(name))
                if not known: continue
                domain,e=known;website='https://'+domain
                company=Company(company_name=name,website=website,source_name=self.name,source_url=self.url,
                    employee_count=e.get('employee_count'),careers_url=e.get('careers_url'))
                job=Job(job_title=title,job_url=row['url'],company_name=name,company_website=website,
                    source_name=self.name,location=location,employment_type='Internship',status='open',
                    description=row.get('description'),posted_at=datetime.fromtimestamp(row['date_posted'],timezone.utc) if row.get('date_posted') else None)
                companies[website]=company;jobs[job.job_url]=job
        else:
            for company, role, url, description, location in wwr_programming_entries(response.text):
                self.fetched_count+=1
                if not location:
                    continue
                known=self.employers.get(normalize_name(company.strip()))
                if not known: continue
                row={'title':role,'description':description,'url':url,
                     'hiringOrganization':{'name':company.strip(),'url':'https://'+known[0]},
                     'applicantLocationRequirements':{'name':location}}
                parsed=parse_posting(row,self.name,self.url,self.employers)
                if parsed:
                    c,j=parsed;companies[c.website]=c;jobs[j.job_url]=j
        return DiscoveryResult(companies=list(companies.values()),jobs=list(jobs.values()))
