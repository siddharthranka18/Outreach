"""Public SSR data from Weekday/Cutshort; no login or private API access."""
import json
import re
from bs4 import BeautifulSoup
from startup_agent.discovery.structured_jobs import StructuredBoardSource,parse_posting,jobposting_nodes,EARLY
from startup_agent.discovery.base import DiscoveryResult
from startup_agent.utils.normalizers import normalize_name


def next_props(page):
    node=page.select_one('script#__NEXT_DATA__')
    return json.loads(node.string)['props']['pageProps'] if node else {}


def cutshort_metadata(page):
    queries=(next_props(page).get('dehydratedState') or {}).get('queries',[])
    company={};size_labels={};for_client=False
    for query in queries:
        data=(query.get('state') or {}).get('data') or {}
        for rows in (data.get('type_based_company_sizes') or {}).values():
            size_labels.update({r['_id']:r['label'] for r in rows})
        if (query.get('queryKey') or [''])[0]=='jobData':
            jobdata=(data.get('data') or {}).get('pageData') or {}
            details=jobdata.get('companyDetails') or {}
            company=details.get('company') or details
            for_client=bool(jobdata.get('hiringForClient') or details.get('hiringForClient'))
    return company,size_labels.get(company.get('newSize')),for_client


class IndiaBoardSource(StructuredBoardSource):
    def discover(self):
        page=BeautifulSoup(self.http_client.get(self.url).text,'html.parser')
        companies,jobs={},{}
        if self.name=='weekday':
            props=next_props(page)
            rows=props.get('jobs')
            if rows is None: raise ValueError('Weekday public SSR jobs missing')
            if 'India' not in (props.get('filters') or {}).get('locations',[]):
                raise ValueError('Weekday response does not confirm India filter')
            for row in rows:
                self.fetched_count+=1
                if not EARLY.search(row.get('title','')):continue
                name=row.get('company') or '';known=self.employers.get(normalize_name(name))
                domain=row.get('companyDomain') or (known[0] if known else '')
                if not domain or 'partner network' in name.lower():continue
                if re.search(r'\b(?:US|USA|EU|Europe|UK)\s*(?:only|residents)\b',row.get('location') or '',re.I):continue
                posting={'title':row['title'],'description':row.get('snippet'),'url':row.get('url'),
                    'hiringOrganization':{'name':name,'url':'https://'+domain},
                    'jobLocation':{'address':{'addressLocality':row.get('location'),'addressCountry':'India'}}}
                # Only the explicitly India-specific list is configured. Never label USA lists as India.
                if self.options.get('country')!='India':continue
                evidence=dict(self.employers)
                if row.get('companySize'):
                    evidence[normalize_name(name)]=(domain,{'employee_count':row['companySize'].replace('\u2013','-'), 'source_url':self.url})
                result=parse_posting(posting,self.name,self.url,evidence)
                if result:
                    c,j=result;j.experience_level=row.get('experience');companies[c.website]=c;jobs[j.job_url]=j
        else:
            urls=list(dict.fromkeys(a['href'] for a in page.select('a[href]') if '/job/' in a['href']
                and EARLY.search(a.get_text(' ',strip=True)+' '+a['href'])))
            from urllib.parse import urljoin,urlsplit
            for path in urls[:max(1,min(30,int(self.options.get('max_details',30))))]:
                url=urljoin(self.url,path)
                if urlsplit(url).hostname!='cutshort.io':continue
                try:
                    detail=BeautifulSoup(self.http_client.get(url).text,'html.parser')
                    org,size,for_client=cutshort_metadata(detail)
                    if for_client:continue
                    for posting in jobposting_nodes(detail):
                        self.fetched_count+=1
                        employer=posting.get('hiringOrganization') or {}
                        employer['url']=(org.get('links') or {}).get('website')
                        if size and '-' in size:
                            lo,hi=size.split('-',1);employer['numberOfEmployees']={'minValue':int(lo),'maxValue':int(hi)}
                        posting['hiringOrganization']=employer
                        result=parse_posting(posting,self.name,url,self.employers)
                        if result:
                            c,j=result;companies[c.website]=c;jobs[j.job_url]=j
                except Exception:
                    import logging
                    logging.getLogger(__name__).warning('Cutshort public detail could not be parsed; skipping.')
        return DiscoveryResult(companies=list(companies.values()),jobs=list(jobs.values()))
