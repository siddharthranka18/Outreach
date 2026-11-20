import socket
import httpx
import pytest
from startup_agent.utils.http_client import HttpClient

@pytest.mark.parametrize("url", ["http://example.com", "https://user:pass@example.com", "https://127.0.0.1", "https://example.com:444"])
def test_public_fetch_rejects_unsafe_before_request(monkeypatch, url):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError): HttpClient(public_only=True).get(url)

def test_redirects_recheck_dns_and_employer_domain(monkeypatch):
    original = httpx.Client
    requests = []
    def resolve(host, *a, **k):
        return [(2,1,6,'',('127.0.0.1' if host == 'private.example' else '8.8.8.8',443))]
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    target = ["https://private.example"]
    def respond(request):
        requests.append(request)
        assert "StartupJobOutreachAgent" in request.headers["User-Agent"]
        return httpx.Response(302, headers={"Location":target[0]})
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    client = HttpClient(public_only=True, rate_limit_delay=0)
    with pytest.raises(ValueError): client.get("https://studio.example")
    assert len(requests) == 1
    target[0] = "https://other.example"
    with pytest.raises(ValueError): client.get("https://studio.example", allowed_domain="studio.example")
    target[0] = "https://studio.example/loop"
    with pytest.raises(httpx.RequestError): client.get("https://studio.example")
    assert len(requests) == 7  # 1 private + 1 external + 5 bounded loop hops
