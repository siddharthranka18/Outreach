"""Recent funding RSS -> observed employer domains. Never infer a verified headcount."""
import json
import logging
import re
from datetime import datetime,timedelta,timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from startup_agent.discovery.base import BaseDiscoverySource,DiscoveryResult
from startup_agent.models.company import Company
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_name

logger=logging.getLogger(__name__)
STAGE=re.compile(r'\b(pre[- ]seed|seed|angel|series[- ]a)\b',re.I)
TECH=re.compile(r'\b(AI|ML|SaaS|devtools|fintech|healthtech|deeptech|deep.tech|software|developer tools)\b',re.I)
EXCLUDED={'linkedin.com','twitter.com','x.com','facebook.com','youtube.com','crunchbase.com','inc42.com','yourstory.com','entrackr.com'}


def resolve_funding_company(title,page,employers):
    text=page.get_text(' ',strip=True)
    # A seed mention elsewhere in a general article is not evidence of this round.
    stage=STAGE.search(title)
    if not stage or not TECH.search(title+' '+text[:1200]):return None
    if not re.search(r'\b(?:India|Indian|Bengaluru|Bangalore|Delhi|Mumbai|Pune|Hyderabad|Chennai|Gurugram)\b',title+' '+text[:2500],re.I):return None
    candidate=re.split(r'\b(?:raises|raised|secures|bags|lands)\b',title,flags=re.I)[0].strip(' :-')
    candidate=re.sub(r'^.*?\bstartup\s+','',candidate,flags=re.I).strip()
    for name,(domain,evidence) in employers.items():
        if re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',title,re.I):
            return evidence.get('company_name') or candidate,domain,evidence,stage.group(1)
    # Only an actual outbound employer link labelled with the startup's name.
    for a in page.select('a[href]'):
        parsed=urlsplit(a['href']);host=(parsed.hostname or '').removeprefix('www.')
        label=normalize_name(a.get_text(' ',strip=True))
        if parsed.scheme=='https' and not parsed.username and host not in EXCLUDED and label and label==normalize_name(candidate):
            return candidate,host,{},stage.group(1)
    return None


class FundingFeedSource(BaseDiscoverySource):
    def __init__(self,name,url,employers=None,options=None,http_client=None):
        super().__init__(name=name,enabled=True)
        self.url=url;self.employers=employers or {};self.options=options or {}
        self.http_client=http_client or HttpClient(public_only=True,timeout=10,max_retries=1)
        self.fetched_count=0

    def discover(self):
        feed=BeautifulSoup(self.http_client.get(self.url).text,'xml')
        if not feed.find('rss'):raise ValueError('Funding source did not return RSS')
        companies={};now=datetime.now(timezone.utc);articles=0
        for item in feed.find_all('item')[:40]:
            self.fetched_count+=1
            if articles>=8:break
            title=item.find('title').get_text(' ',strip=True)
            if not STAGE.search(title) or not re.search(r'raises?|funding|round|secures|bags',title,re.I):continue
            try:
                posted=parsedate_to_datetime(item.find('pubDate').get_text())
                if posted.tzinfo is None:posted=posted.replace(tzinfo=timezone.utc)
                if not now-timedelta(days=30)<=posted<=now:continue
            except (ValueError,AttributeError,TypeError):continue
            link=item.find('link').get_text()
            if urlsplit(link).hostname!=urlsplit(self.url).hostname:continue
            try:
                articles+=1
                page=BeautifulSoup(self.http_client.get(link).text,'html.parser')
                result=resolve_funding_company(title,page,self.employers)
                if not result:continue
                name,domain,e,stage=result
                companies[domain]=Company(company_name=name,website='https://'+domain,
                    source_name=self.name,source_url=link,employee_count=e.get('employee_count'),
                    funding_stage=stage,careers_url=e.get('careers_url') or 'https://'+domain+'/careers',location='India')
            except Exception as exc:logger.warning('%s article unavailable (%s)',self.name,type(exc).__name__)
        # Unknown-size funding companies are stored for research but still fail every outreach size gate.
        return DiscoveryResult(companies=list(companies.values()))
