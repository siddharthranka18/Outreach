"""Small read-only live source probe. Uses an isolated DB and never sends a digest.

Run from the application directory: PYTHONPATH=src python scripts/probe_daily_sources.py
"""
import json
from pathlib import Path
import shutil
import tempfile

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from startup_agent.config.settings import Settings
from startup_agent.database.models import Base
from startup_agent.discovery.pipeline import DiscoveryPipeline
from startup_agent.discovery.portfolio import PortfolioDiscoverySource
from startup_agent.discovery.community_feeds import CommunityFeedSource
from startup_agent.discovery.india_boards import IndiaBoardSource
from startup_agent.discovery.funding_feeds import FundingFeedSource
from startup_agent.funnel import source_funnel
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_name

root=Path(__file__).resolve().parents[1]
config=yaml.safe_load((root/'config/sources.yaml').read_text())['sources']
evidence=yaml.safe_load((root/'config/company_sizes.yaml').read_text())
employers={normalize_name(e['company_name']):(domain,e) for domain,e in evidence.items() if e.get('company_name')}
adapters=[]
for source in config:
    if not source.get('enabled'):continue
    name=source['name'];url=source.get('url');options=source.get('options',{})
    client=HttpClient(public_only=True,timeout=10,max_retries=0)
    if source['type']=='vc_portfolio':
        adapters.append(PortfolioDiscoverySource(name,url,{**options,'max_pages':1,'location_queries':[['India']]},http_client=client))
    elif source['type']=='community_feed':
        adapters.append(CommunityFeedSource(name,url,employers,http_client=client))
    elif source['type']=='india_board':
        adapters.append(IndiaBoardSource(name,url,employers,{**options,'max_details':5},http_client=client))
    elif source['type']=='funding_feed':
        adapters.append(FundingFeedSource(name,url,employers,options,http_client=client))

with tempfile.TemporaryDirectory(prefix='outreach-source-probe-') as temporary:
    workspace=Path(temporary)
    (workspace/'config').mkdir()
    for filename in ('sources.yaml','company_sizes.yaml','candidate_profile.yaml'):
        shutil.copy(root/'config'/filename,workspace/'config'/filename)
    settings=Settings(base_dir=workspace)
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        summary=DiscoveryPipeline(settings=settings,session=session,custom_adapters=adapters,auto_expand_ats=False).run()
        session.commit()
        result=source_funnel(session,settings)
        destination=root/'data/processed/daily_source_probe.json'
        destination.write_text(json.dumps(result,indent=2),encoding='utf-8')
        for name,row in result['sources'].items():
            print(name, 'fetched='+str(row.get('fetched','?')),
                  'stored='+str(row['normalized']), 'size_ok='+str(row['size_eligible']),
                  'eligible='+str(row['role_eligible']), 'routed='+str(row['routed']),
                  'error='+str(row.get('error','')),flush=True)
        print('Failed sources:',summary.sources_failed,flush=True)
        print('Saved report:',destination,flush=True)
