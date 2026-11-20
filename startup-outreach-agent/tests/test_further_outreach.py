from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import json
from pathlib import Path
import pytest
from bs4 import BeautifulSoup
from startup_agent.hosted_delivery import hiring_email,verified_contact
from startup_agent.discovery.hn_hiring import current_hn_contact
from startup_agent.routing import junior_pitch_context
from startup_agent.matching.profile import CandidateProfile
from startup_agent.discovery.community_feeds import CommunityFeedSource
from startup_agent.discovery.india_boards import IndiaBoardSource,cutshort_metadata
from startup_agent.discovery.structured_jobs import parse_posting
from startup_agent.discovery.direct_ats import extract_ats_target,DirectAtsDiscoverySource
from startup_agent.discovery.funding_feeds import resolve_funding_company
from startup_agent.discovery.board_tracking import remember_boards,stored_targets,sweep_stale
from startup_agent.database.repositories import CompanyRepository,JobRepository
from startup_agent.models.company import Company
from startup_agent.models.job import Job

F=Path(__file__).parent/'fixtures'
EMPLOYERS={'studio':('studio.example',{'employee_count':'11-50','source_url':'https://studio.example/about'})}

@pytest.mark.parametrize('prefix',['founders','team','apply','internships','engineering','hello','contact'])
def test_approved_small_company_inboxes(prefix):
    soup=BeautifulSoup(f'<a href="mailto:{prefix}@studio.example">Email us</a>','html.parser')
    assert hiring_email(soup,'studio.example',allow_generic=True,employee_count='11-50')==prefix+'@studio.example'
    assert hiring_email(soup,'studio.example',allow_generic=True,employee_count='51-200') is None
    assert hiring_email(soup,'studio.example',allow_generic=False,employee_count='11-50') is None

def test_hn_opt_in_requires_current_top_level_provenance_and_size():
    now=datetime.now(timezone.utc)
    hint={'email':'founder@studio.example','domain':'studio.example','evidence_url':'https://news.ycombinator.com/item?id=123',
          'thread_id':'100','thread_author':'whoishiring','author':'founder','top_level':True,'evidence_type':'hn_monthly_hiring',
          'checked_at':now.isoformat(),'posted_at':(now-timedelta(days=3)).isoformat()}
    assert current_hn_contact(hint,'studio.example',now)
    assert verified_contact([],'studio.example',hn_leads=[hint],employee_count='11-50',trust_hn=True)==(hint['email'],hint['evidence_url'])
    assert verified_contact([],'studio.example',hn_leads=[hint],employee_count=None,trust_hn=True) is None
    assert verified_contact([],'studio.example',hn_leads=[hint],employee_count='11-50') is None
    for change in ({'top_level':False},{'checked_at':(now-timedelta(days=3)).isoformat()},{'domain':'other.example'},{'evidence_url':'https://example.com/123'}):
        assert not current_hn_contact({**hint,**change},'studio.example',now)

def test_junior_pitch_does_not_turn_into_direct_application():
    company=SimpleNamespace(company_name='Studio',employee_count='11-50')
    job=SimpleNamespace(job_title='Junior Software Engineer',description='We need 0-1 years experience building Python APIs and SQL integrations. Work with our engineering team to build backend services, write tests and learn from code reviews.',
        location='Bengaluru, India',employment_type='Full-time',experience_level='0-1 years',job_url='https://studio.example/junior',status='open')
    profile=CandidateProfile.load()
    assert 'internship or part-time' in junior_pitch_context(job,company,profile)
    job.experience_level='2 years';assert junior_pitch_context(job,company,profile) is None
    job.experience_level='0-1 years';job.location='US only';assert junior_pitch_context(job,company,profile) is None
    job.location='India';company.employee_count='51-200';assert junior_pitch_context(job,company,profile) is None

def test_simplify_active_india_only_and_wwr_attribution():
    data=json.loads((F/'further_sources.json').read_text(encoding='utf-8'))
    client=Mock();client.get.return_value.json.return_value=data['simplify']
    result=CommunityFeedSource('simplify_summer2027','https://raw.githubusercontent.com/fixture',EMPLOYERS,client).discover()
    assert len(result.jobs)==1
    assert extract_ats_target(result.jobs[0].job_url,'Studio','https://studio.example')['platform']=='ashby'
    client.get.return_value.text=(F/'wwr.xml').read_text()
    result=CommunityFeedSource('we_work_remotely','https://weworkremotely.com/rss',EMPLOYERS,client).discover()
    assert len(result.jobs)==1 and result.jobs[0].job_url.startswith('https://weworkremotely.com/')

def test_weekday_public_ssr_and_cutshort_published_enum():
    data=json.loads((F/'further_sources.json').read_text(encoding='utf-8'))
    client=Mock();client.get.return_value.text='<script id="__NEXT_DATA__" type="application/json">'+json.dumps(data['weekday'])+'</script>'
    result=IndiaBoardSource('weekday','https://www.weekday.works/jobs/it-fresher-jobs',{}, {'country':'India'},client).discover()
    assert len(result.jobs)==1 and result.companies[0].employee_count=='11-50 employees'
    page=BeautifulSoup('<script id="__NEXT_DATA__">'+json.dumps(data['cutshort'])+'</script>','html.parser')
    company,size,agency=cutshort_metadata(page)
    assert size=='0-20' and company['links']['website']=='https://studio.example' and not agency

def test_paid_student_guardrails_and_unknown_size_still_unknown():
    row=json.loads((F/'further_sources.json').read_text(encoding='utf-8'))['posting']
    row['description']+=' We use Docker and Git.'
    assert parse_posting(row,'student','https://board.example/job',{},True)
    assert not parse_posting({**row,'baseSalary':{}},'student','https://board.example/job',{},True)
    assert not parse_posting({**row,'description':'Unpaid training program'},'student','https://board.example/job',{},True)
    assert not parse_posting({**row,'validThrough':'2020-01-01T00:00:00Z'},'student','https://board.example/job',{},True)

def test_funding_observed_domains_never_infer_size():
    soup=BeautifulSoup('<p>Indian SaaS tools.</p><a href="https://studio.example">Studio</a>','html.parser')
    result=resolve_funding_company('Studio raises Seed funding',soup,{})
    assert result[1]=='studio.example' and result[2]=={}
    assert resolve_funding_company('Studio raises Series B funding',soup,{}) is None

def test_board_persistence_and_three_successful_missing_polls(db_session):
    c=CompanyRepository(db_session).upsert_company(Company(company_name='Studio',website='https://studio.example',
        source_name='vc',source_url='https://board.example',employee_count='11-50'))
    url='https://jobs.ashbyhq.com/studio/123'
    remember_boards(c,[url,url])
    targets=stored_targets(db_session,{'ashby'})
    assert len(targets)==1
    assert stored_targets(db_session,{'lever'})==[]
    job=JobRepository(db_session).upsert_job(Job(job_title='Backend Engineer Intern',job_url=url,company_id=c.id,source_name='ashby:studio'))
    assert sweep_stale(db_session,[(targets[0],[])])==0 and job.missing_ats_polls==1
    assert sweep_stale(db_session,[])==0 and job.missing_ats_polls==1  # failed poll is never an empty snapshot
    assert sweep_stale(db_session,[(targets[0],[])])==0
    assert sweep_stale(db_session,[(targets[0],[])])==1 and job.status=='closed'
    job.status='skipped';assert sweep_stale(db_session,[(targets[0],[])])==0 and job.status=='skipped'

def test_freshness_does_not_expire_old_but_live_advert(db_session):
    c=CompanyRepository(db_session).upsert_company(Company(company_name='Studio',website='https://studio.example',
        source_name='vc',source_url='https://board.example',employee_count='11-50'))
    j=JobRepository(db_session).upsert_job(Job(job_title='Backend Engineer Intern',job_url='https://studio.example/old',
        source_name='fixture',company_id=c.id,posted_at=datetime.now(timezone.utc)-timedelta(days=80)))
    assert sweep_stale(db_session)==0
    j.last_seen_at=datetime.now(timezone.utc)-timedelta(days=31)
    assert sweep_stale(db_session)==1

def test_freshteam_jsonld_fixture_and_token_detection():
    row=json.loads((F/'further_sources.json').read_text(encoding='utf-8'))['posting']
    row['url']='https://studio.freshteam.com/jobs/token/intern'
    client=Mock();client.get.return_value.text='<script type="application/ld+json">'+json.dumps(row)+'</script>'
    target=extract_ats_target(row['url'],'Studio','https://studio.example','11-50')
    jobs=DirectAtsDiscoverySource(http_client=client).fetch_board_jobs(target)
    assert len(jobs)==1 and jobs[0].source_name=='freshteam:studio'
    assert 'Python' in jobs[0].description

def test_sqlite_evidence_feeds_himalayas_and_remotive_without_yaml(db_session,tmp_path):
    from startup_agent.config.settings import Settings,SourceConfig
    from startup_agent.discovery.pipeline import DiscoveryPipeline
    CompanyRepository(db_session).upsert_company(Company(company_name='Studio',website='https://studio.example',
        source_name='vc',source_url='https://board.example/studio',employee_count='11-50'))
    sources=[SourceConfig(name,name,'public_jobs_api',True,'fixture') for name in ['himalayas','remotive']]
    adapters=DiscoveryPipeline(settings=Settings(base_dir=tmp_path,sources=sources),session=db_session)._resolve_adapters()
    assert adapters[0].employers_by_name['studio'][0]=='studio.example'
    assert adapters[1].employers['studio'][1]['employee_count']=='11-50'

def test_reviewed_evidence_backfills_old_jobs_not_fetched_again(db_session,tmp_path):
    from startup_agent.config.settings import Settings
    from startup_agent.discovery.pipeline import DiscoveryPipeline
    (tmp_path/'config').mkdir()
    (tmp_path/'config/company_sizes.yaml').write_text('studio.example:\n  employee_count: "11-50"\n  source_url: https://studio.example/about\n')
    company=CompanyRepository(db_session).upsert_company(Company(company_name='Studio',website='https://studio.example',
        source_name='old_feed',source_url='https://board.example/studio'))
    DiscoveryPipeline(settings=Settings(base_dir=tmp_path),session=db_session)._backfill_reviewed_sizes()
    assert company.employee_count=='11-50'

def test_employer_domain_lookup_handles_name_variants_without_size_borrowing():
    from startup_agent.discovery.employer_lookup import known_employer
    assert known_employer('Studio Incorporated',EMPLOYERS,'https://www.studio.example/about')[0]=='studio.example'
    assert known_employer('Studio',EMPLOYERS,'https://different.example') is None
    assert known_employer('Studio',EMPLOYERS)==EMPLOYERS['studio']

def test_handled_companies_do_not_consume_employer_page_budget(db_session,tmp_path,monkeypatch):
    from startup_agent.hosted_delivery import enquiry_candidates
    from startup_agent.config.settings import Settings
    CompanyRepository(db_session).upsert_company(Company(company_name='Studio',website='https://studio.example',
        source_name='vc',source_url='https://board.example',employee_count='11-50',careers_url='https://studio.example/careers'))
    monkeypatch.setattr('startup_agent.hosted_delivery.gallery_leads',lambda *args,**kwargs:[])
    monkeypatch.setattr('startup_agent.hosted_delivery.funded_employers',lambda *args,**kwargs:[])
    fetch=Mock();monkeypatch.setattr('startup_agent.hosted_delivery.employer_page',fetch)
    assert enquiry_candidates(db_session,Settings(base_dir=tmp_path),CandidateProfile.load(),history=[{
        'url':'https://studio.example/#outreach-enquiry','status':'skipped'}])==[]
    fetch.assert_not_called()

def test_cheap_feeds_run_before_per_company_yc_job_fetches(db_session,tmp_path):
    from startup_agent.config.settings import Settings,SourceConfig
    from startup_agent.discovery.pipeline import DiscoveryPipeline
    sources=[SourceConfig('y_combinator','YC','directory',True,'fixture'),
             SourceConfig('we_work_remotely','WWR','community_feed',True,'fixture',url='https://weworkremotely.com/rss')]
    adapters=DiscoveryPipeline(settings=Settings(base_dir=tmp_path,sources=sources),session=db_session)._resolve_adapters()
    assert [adapter.name for adapter in adapters]==['we_work_remotely','y_combinator']
