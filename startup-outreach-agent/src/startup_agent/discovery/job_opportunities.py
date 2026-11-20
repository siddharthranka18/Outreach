"""Optional, disabled-by-default JOA integration. Requires a user-supplied free key."""
import os
import re
from startup_agent.discovery.base import BaseDiscoverySource,DiscoveryResult
from startup_agent.discovery.structured_jobs import parse_posting
from startup_agent.utils.normalizers import normalize_name
from startup_agent.utils.http_client import HttpClient

class JobOpportunitiesSource(BaseDiscoverySource):
    def __init__(self,employers=None,name='job_opportunities',http_client=None):
        super().__init__(name=name,enabled=True)
        self.employers=employers or {};self.http_client=http_client or HttpClient(public_only=True)
        self.fetched_count=0

    def discover(self):
        key=os.getenv('JOA_API_KEY','').strip()
        if not key:raise ValueError('Optional Job Opportunities source needs JOA_API_KEY; keep disabled otherwise.')
        # One small page, no metered pagination or automatic retries on quota errors.
        payload=self.http_client.get('https://api.jobopportunitiesapi.org/v1/jobs',
            params={'country':'IN','limit':20},headers={'Authorization':'Bearer '+key}).json()
        companies,jobs={},{}
        for row in payload['data']:
            self.fetched_count+=1
            if row.get('status')!='live' or row.get('provider_type') not in {'employer_ats','employer_site'}:continue
            if row.get('description_truncated') is True:continue
            if row.get('country')!='IN' and 'IN' not in row.get('countries',[]):continue
            name=row.get('company') or '';known=self.employers.get(normalize_name(name))
            if not known:continue
            posting={'title':row.get('title'),'description':row.get('description'), 'url':row.get('apply_url'),
                     'hiringOrganization':{'name':name,'url':'https://'+known[0]},
                     'jobLocation':{'address':{'addressCountry':'India'}}}
            result=parse_posting(posting,self.name,'https://jobopportunitiesapi.org',self.employers)
            if result:
                c,j=result;companies[c.website]=c;jobs[j.job_url]=j
        return DiscoveryResult(companies=list(companies.values()),jobs=list(jobs.values()))
