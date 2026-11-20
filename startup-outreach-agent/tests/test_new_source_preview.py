"""End-to-end saved-fixture discovery -> normal persistence -> actual preview CLI.

Run with pytest -s tests/test_new_source_preview.py to print the complete funnel.
No Telegram, Gemini or live source requests are made.
"""
import json
import shutil
from pathlib import Path
from unittest.mock import Mock
from startup_agent.config.settings import Settings, SourceConfig
from startup_agent.discovery.pipeline import DiscoveryPipeline
from startup_agent.discovery.portfolio import PortfolioDiscoverySource
from startup_agent.discovery.hn_hiring import HnHiringDiscoverySource
from startup_agent.discovery.remote_feeds import RemoteFeedDiscoverySource
from startup_agent.discovery.direct_ats import DirectAtsDiscoverySource
from startup_agent.funnel import source_funnel, format_funnel
from startup_agent import main as cli
from startup_agent.routing import build_outreach_routes

F = Path(__file__).parent / "fixtures"

def test_all_new_sources_through_real_digest_preview(db_session, isolated_engine, tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    shutil.copy(Path(__file__).resolve().parents[1]/"config/candidate_profile.yaml", config/"candidate_profile.yaml")
    (config/"company_sizes.yaml").write_text("{}")
    adapters, sources = [], []
    for name in ("vc_peakxv", "vc_lightspeed", "vc_bessemer"):
        data = json.loads((F/"consider.json").read_text())
        data["jobs"][0]["jobs"][0]["applyUrl"] += "/"+name
        client = Mock()
        client.get.return_value.text = 'window.serverInitialData = {"board":{"id":"fixture"},"csrfToken":"temporary"};'
        client.post.return_value.json.return_value = data
        adapters.append(PortfolioDiscoverySource(name, "https://board.example", {"provider":"consider"}, http_client=client))
    employers = {"studio":("studio.example", {"employee_count":"11-50", "source_url":"https://studio.example/about"})}
    hn = json.loads((F/"hn_hiring.json").read_text())
    client = Mock()
    client.get.side_effect = [Mock(**{"json.return_value":{"hits":hn["hits"]}}),Mock(**{"json.return_value":hn["thread"]})]
    adapters.append(HnHiringDiscoverySource(employers, http_client=client))
    feeds = json.loads((F/"remote_feeds.json").read_text())
    for name, data in feeds.items():
        client = Mock()
        client.get.return_value.json.return_value = data
        adapters.append(RemoteFeedDiscoverySource(employers, name, http_client=client))
    ats = json.loads((F/"public_ats.json").read_text())
    for platform in ("workable", "breezy", "teamtailor", "bamboohr"):
        client = Mock()
        def get(url, platform=platform):
            if platform == "teamtailor": return Mock(text=(F/"teamtailor.xml").read_text())
            if platform == "breezy" and "/p/" in url: return Mock(text=(F/"breezy_detail.html").read_text())
            return Mock(**{"json.return_value":ats["bamboohr_detail" if url.endswith("/detail") else platform]})
        client.get.side_effect = get
        adapters.append(DirectAtsDiscoverySource(name="ats_"+platform, http_client=client, targets=[{
            "platform":platform,"board_token":"studio","company_name":"Studio", "website":"https://studio.example", "employee_count":"11-50"}]))
    for adapter in adapters:
        sources.append(SourceConfig(adapter.name,adapter.name,"fixture",True,"Saved fixture"))
    settings = Settings(base_dir=tmp_path, sources=sources, log_level="ERROR", database_url="sqlite:///:memory:")
    summary = DiscoveryPipeline(settings=settings, session=db_session, custom_adapters=adapters, auto_expand_ats=False).run()
    db_session.commit()
    assert summary.sources_successful == 11 and not summary.sources_failed
    funnel = source_funnel(db_session, settings)
    print("\nSAVED FIXTURE FUNNEL (synthetic opportunities; not live supply)\n"+format_funnel(funnel))
    # Copies of the same employer/title/location collapse through existing upserts.
    assert 0 < sum(row["normalized"] for row in funnel["sources"].values()) <= 11
    assert funnel["sources"]["hn_hiring"]["routed"] == 1
    assert all(route.contact is None for route in build_outreach_routes(db_session, settings))
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls, **kwargs: settings))
    monkeypatch.setattr(cli, "create_db_engine", lambda *args, **kwargs: isolated_engine)
    assert cli.main(["--digest-preview"]) == 0
