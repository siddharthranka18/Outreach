from unittest.mock import Mock

import httpx
import yaml

from startup_agent.config.settings import Settings
from startup_agent.database.repositories import CompanyRepository
from startup_agent.discovery.curated_boards import CuratedStartupDiscoverySource
from startup_agent.discovery.pipeline import DiscoveryPipeline


def test_curated_boards_pause_provider_without_losing_independent_results(tmp_path):
    evidence = {
        "first.example": {"company_name": "First", "source_url": "https://fund.example/first",
                          "ats_url": "https://jobs.ashbyhq.com/first", "public_board_only": True},
        "second.example": {"company_name": "Second", "source_url": "https://fund.example/second",
                           "ats_url": "https://jobs.ashbyhq.com/second", "public_board_only": True},
        "third.example": {"company_name": "Third", "source_url": "https://fund.example/third",
                          "ats_url": "https://jobs.lever.co/third", "public_board_only": True},
        "fourth.example": {"company_name": "Fourth", "source_url": "https://fund.example/fourth",
                           "public_board_only": True},
    }
    client = Mock()
    request = httpx.Request("GET", "https://api.ashbyhq.com/posting-api/job-board/first")
    client.get.side_effect = [
        httpx.HTTPStatusError("slow down", request=request, response=httpx.Response(429)),
        httpx.Response(200, json=[]),
    ]
    state = tmp_path / "cooldowns.json"
    adapter = CuratedStartupDiscoverySource(evidence, state, http_client=client)
    result = adapter.discover()
    assert len(result.companies) == 4
    assert all(company.employee_count is None for company in result.companies)
    assert len(adapter.successful_polls) == 1
    assert adapter.successful_polls[0][0]["board_token"] == "third"
    assert [call.args[0].split("?")[0] for call in client.get.call_args_list] == [
        str(request.url), "https://api.lever.co/v0/postings/third",
    ]
    CuratedStartupDiscoverySource(evidence, state, http_client=client).discover()
    assert client.get.call_count == 2


def test_cohort_without_headcount_is_stored_by_discovery_pipeline(db_session, tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.config_dir.mkdir()
    evidence = {"cohort.example": {"company_name": "Cohort", "source_url": "https://fund.example/cohort",
                                    "public_board_only": True}}
    (settings.config_dir / "company_sizes.yaml").write_text(yaml.safe_dump(evidence))
    client = Mock()
    adapter = CuratedStartupDiscoverySource(evidence, settings.data_dir / "processed/cooldowns.json", client)
    summary = DiscoveryPipeline(settings, session=db_session, custom_adapters=[adapter],
                                auto_expand_ats=False).run()
    assert summary.companies_inserted == 1
    assert CompanyRepository(db_session).get_company_by_website("https://cohort.example").employee_count is None
    client.get.assert_not_called()
