import hashlib
import hmac
import json
from unittest.mock import Mock
from startup_agent import main as cli
from startup_agent.config.settings import Settings
from startup_agent.discovery.pipeline import DiscoverySummary
from startup_agent.hosted_delivery import hosted_request

def test_summary_is_covered_by_existing_signature(monkeypatch):
    secret = "fixture-only-secret-0000000000000000000000"
    def post(endpoint, *, json, **kwargs):
        assert json["signature"] == hmac.new(secret.encode(), json["payload"].encode(), hashlib.sha256).hexdigest()
        assert __import__('json').loads(json["payload"])["summary"] == "fixture fetch: 1 eligible: 0"
        return Mock(**{"json.return_value":{"ok":True,"sent":0}})
    monkeypatch.setattr("startup_agent.hosted_delivery.httpx.post", post)
    assert hosted_request("https://script.google.com/fixture", secret, "local-123", [], summary="fixture fetch: 1 eligible: 0")["sent"] == 0

def test_all_source_failure_reports_then_returns_failure(monkeypatch, isolated_engine, tmp_path):
    monkeypatch.setattr(cli, "initialize_app", lambda: Settings(base_dir=tmp_path))
    monkeypatch.setattr(cli, "create_db_engine", lambda *args: isolated_engine)
    monkeypatch.setattr(cli, "source_funnel", lambda *args: {"sources":{}, "rejections":{}})
    monkeypatch.setattr(cli, "run_discovery_pipeline", lambda **kwargs: DiscoverySummary(sources_attempted=2, sources_failed=[("a","offline"),("b","offline")]))
    publish = Mock(return_value=0)
    monkeypatch.setattr(cli, "publish_hosted_shortlist", publish)
    assert cli.main(["--hosted-daily"]) == 1
    assert publish.call_args.kwargs == {"discovery_failed":True}
