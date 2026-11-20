import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from startup_agent.discovery.remote_feeds import RemoteFeedDiscoverySource

@pytest.mark.parametrize("name", ["remoteok", "jobicy", "working_nomads"])
def test_remote_fixture_strictness_and_original_attribution(name):
    data = json.loads((Path(__file__).parent / "fixtures/remote_feeds.json").read_text())[name]
    rows = data["jobs"] if name == "jobicy" else data
    row = rows[-1]
    title = "position" if name == "remoteok" else "jobTitle" if name == "jobicy" else "title"
    location = "jobGeo" if name == "jobicy" else "location"
    company = "companyName" if name == "jobicy" else "company_name" if name == "working_nomads" else "company"
    rows.extend([row.copy(), {**row, title:"Senior Software Engineer"}, {**row, location:"Remote"},
                 {**row, location:"US only"}, {**row, company:"Unknown"}, {**row, "url":"http://127.0.0.1/x"}])
    client = Mock()
    client.get.return_value.json.return_value = data
    source = RemoteFeedDiscoverySource({"studio":("studio.example", {"employee_count":"11-50", "source_url":"https://studio.example/about"})}, name, http_client=client)
    result = source.discover()
    assert len(result.jobs) == 1
    assert result.jobs[0].source_name == name
    assert result.jobs[0].job_url == row["url"]
    assert source.fetched_count == 7
    assert source.rejections["No explicit India/worldwide permission"] == 2
