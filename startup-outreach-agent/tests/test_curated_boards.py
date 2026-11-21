from unittest.mock import Mock

import httpx

from startup_agent.discovery.curated_boards import CuratedStartupDiscoverySource


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
