from unittest.mock import Mock
import pytest
from startup_agent.discovery.job_opportunities import JobOpportunitiesSource

def test_optional_joa_needs_key_and_preserves_employer_links(monkeypatch):
    monkeypatch.delenv('JOA_API_KEY',raising=False)
    client=Mock();source=JobOpportunitiesSource({'studio':('studio.example',{'employee_count':'11-50'})},http_client=client)
    with pytest.raises(ValueError):source.discover()
    client.get.assert_not_called()
    monkeypatch.setenv('JOA_API_KEY','fixture-key')
    row={'status':'live','country':'IN','provider_type':'employer_ats','company':'Studio','title':'Backend Engineer Intern',
         'apply_url':'https://studio.example/careers/intern','description':'Current students can build Python APIs, work on SQL data pipelines and contribute tests alongside our small engineering team.'}
    client.get.return_value.json.return_value={'data':[row,{**row,'status':'closed'},{**row,'country':'US'},{**row,'provider_type':'aggregator'}]}
    result=source.discover()
    assert len(result.jobs)==1 and result.jobs[0].job_url==row['apply_url']
    assert client.get.call_count==1
    assert client.get.call_args.kwargs['headers']=={'Authorization':'Bearer fixture-key'}
