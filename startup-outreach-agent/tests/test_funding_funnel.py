
from datetime import date
from pathlib import Path
from unittest.mock import Mock
from startup_agent.discovery.funding_leads import funded_employers
from startup_agent.funnel import format_funnel

def test_funding_resolves_only_reviewed_employers_and_isolates_failures():
    client = Mock()
    client.get.return_value.text = Path('tests/fixtures/funding.csv').read_text()
    evidence = {'tiny.example': {'company_name': 'Tiny Studio', 'employee_count': '11-50',
                                'careers_url': 'https://tiny.example/careers'}}
    leads = funded_employers(evidence, client, date(2026, 11, 20))
    assert len(leads) == 1
    assert leads[0]['website'] == 'https://tiny.example'
    client.get.side_effect = RuntimeError('offline')
    assert funded_employers(evidence, client, date(2026, 11, 20)) == []

def test_funnel_distinguishes_unknown_fetched_counts():
    result = format_funnel({'sources': {'test': dict(normalized=2, size_known=1, size_eligible=1,
                                                    role_eligible=1, routed=0)}, 'rejections': {'Unknown': 1}})
    assert 'fetched=n/a' in result
    assert 'routed=0' in result
