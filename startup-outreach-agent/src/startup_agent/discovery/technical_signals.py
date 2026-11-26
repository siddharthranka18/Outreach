"""Extract attributable technical signals from pages already visited for outreach."""

import os
import re
from urllib.parse import urljoin, urlsplit

import httpx

from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.posting_guard import sanitize_untrusted_text

HANDLE = re.compile(r"[a-z0-9][a-z0-9-]{0,38}", re.I)
REPO = re.compile(r"[a-z0-9_.-]{1,100}", re.I)
ADDRESS = re.compile(r"[a-z0-9._+%-]+@[a-z0-9.-]+\.[a-z]{2,}", re.I)
RESERVED = {"about", "apps", "collections", "explore", "features", "marketplace", "orgs",
            "pricing", "search", "settings", "sponsors", "topics", "trending"}


class TechnicalSignalResearch:
    def __init__(self, options, client=None):
        self.client = client or HttpClient(public_only=True, max_retries=0,
            timeout=min(10, max(1, int(options.get("github_api_timeout_seconds", 10)))))
        self.remaining = min(5, max(0, int(options.get("max_companies_per_run", 5))))
        self.limit = min(3, max(1, int(options.get("max_repos_per_company", 3))))
        token = os.getenv("GITHUB_TOKEN", "").strip()
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.blocked = False
        self.cache = {}

    def _get(self, path, params):
        return self.client.get("https://api.github.com/" + path,
            params=params, headers=self.headers, allowed_domain="api.github.com").json()

    def _github(self, org):
        if org in self.cache:
            return self.cache[org]
        if not self.remaining or self.blocked:
            return {}
        self.remaining -= 1
        signal = {}
        try:
            repos = self._get(f"orgs/{org}/repos", {"sort": "updated", "per_page": self.limit})
            repo = next((repo for repo in repos if not repo.get("fork") and not repo.get("archived")
                         and REPO.fullmatch(repo.get("name") or "") and repo.get("name") not in {".", ".."}), None)
            if repo:
                name = repo["name"]
                description, _ = sanitize_untrusted_text(repo.get("description") or "", 280)
                language, _ = sanitize_untrusted_text(repo.get("language") or "", 45)
                signal = {"repo": name, "language": language, "description": description,
                          "url": f"https://github.com/{org}/{name}"}
                issues = self._get(f"repos/{org}/{name}/issues", {"state": "open", "per_page": 3})
                issue = next((issue for issue in issues if "pull_request" not in issue and
                              isinstance(issue.get("number"), int) and issue["number"] > 0), None)
                if issue:
                    title, _ = sanitize_untrusted_text(issue.get("title") or "", 180)
                    if title:
                        signal.update(issue=title, url=f"https://github.com/{org}/{name}/issues/{issue['number']}")
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {401, 403, 429}:
                self.blocked = True
        except (httpx.HTTPError, TypeError, AttributeError, ValueError):
            pass
        self.cache[org] = signal
        return signal

    def inspect(self, pages, domain):
        org_url, technical, alternate = None, {}, None
        for source, page in pages:
            for node in page.select("a[href]"):
                href = node["href"]
                if href.lower().startswith("mailto:"):
                    address = href[7:].split("?", 1)[0].strip().lower()
                    context = node.parent.get_text(" ", strip=True)
                    if (len(context) <= 350 and ADDRESS.fullmatch(address)
                            and address.rsplit("@", 1)[-1] == domain
                            and re.search(r"\b(?:cto|chief technology officer|founder|engineer)\b", context, re.I)
                            and re.search(r"\b(?:hiring|recruiting|send (?:us |me )?your (?:cv|resume)|internship)\b", context, re.I)):
                        alternate = alternate or {"email": address, "source": source}
                    continue
                try:
                    url = urlsplit(urljoin(source, href))
                except ValueError:
                    continue
                if url.scheme != "https" or url.username or url.password:
                    continue
                parts = url.path.strip("/").split("/")
                if (url.netloc == "github.com" and len(parts) == 1 and HANDLE.fullmatch(parts[0])
                        and parts[0].lower() not in RESERVED):
                    org_url = org_url or f"https://github.com/{parts[0].lower()}"
                if (not technical and url.hostname in {domain, "www." + domain}
                        and parts[0] in {"blog", "engineering", "docs", "changelog"}):
                    excerpt, _ = sanitize_untrusted_text(node.get_text(" ", strip=True), 180)
                    if len(parts) > 1 and len(excerpt.split()) >= 5:
                        technical = {"description": excerpt, "url": url._replace(query="", fragment="").geturl()}
        github = self._github(org_url.rsplit("/", 1)[1]) if org_url else {}
        if github.get("issue") or github.get("description"):
            technical = github
        return org_url, technical, alternate
