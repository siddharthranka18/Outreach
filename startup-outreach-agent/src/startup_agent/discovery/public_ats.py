"""Additional keyless ATS protocols, verified on public employer boards 2026-11-20."""
import json
import re
import html
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from startup_agent.models.job import Job
from startup_agent.utils.normalizers import normalize_job_url

PLATFORMS = {"workable", "breezy", "teamtailor", "bamboohr", "personio", "freshteam"}


def text(value):
    return BeautifulSoup(html.unescape(str(value or "")), "html.parser").get_text(" ", strip=True)


def fetch_public_ats(target, client):
    platform, board = target["platform"], target["board_token"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", board):
        raise ValueError("Unsafe board token")
    rows = []
    if platform == "workable":
        data = client.get(f"https://apply.workable.com/api/v1/widget/accounts/{board}?details=true").json()
        for row in data["jobs"]:
            places = row.get("locations") or [row]
            location = " / ".join(", ".join(str(p.get(k) or "") for k in ("city", "region", "country")).strip(", ") for p in places)
            rows.append((row["title"], row.get("url"), location,
                         row.get("description"), row.get("employment_type"), row.get("shortcode")))
    elif platform == "breezy":
        data = client.get(f"https://{board}.breezy.hr/json").json()
        for row in data[:200]:
            url = row.get("url") or ""
            if urlsplit(url).hostname != f"{board}.breezy.hr":
                continue
            description = row.get("description")
            # Fetch details on a bounded selection; never manufacture a description.
            if len(rows) < 40:
                page = BeautifulSoup(client.get(url).text, "html.parser")
                for node in page.select('script[type="application/ld+json"]'):
                    try:
                        item = json.loads(node.string or node.get_text())
                        if isinstance(item, dict) and item.get("@type") == "JobPosting":
                            description = item.get("description")
                    except (ValueError, TypeError):
                        continue
            location = " / ".join(p.get("name") or "" for p in row.get("locations", []) or [row.get("location") or {}])
            rows.append((row["name"], url, location, description, (row.get("type") or {}).get("name"), row.get("id")))
    elif platform == "bamboohr":
        data = client.get(f"https://{board}.bamboohr.com/careers/list").json()
        for row in data["result"][:100]:
            identifier = str(row["id"])
            if not identifier.isdigit():
                continue
            # Rich country/description fields are absent from the list response.
            details = client.get(f"https://{board}.bamboohr.com/careers/{identifier}/detail").json()["result"]["jobOpening"]
            if details.get("jobOpeningStatus") not in (None, "Open"):
                continue
            location = {**(details.get("location") or {}), **(details.get("atsLocation") or {})}
            location = ", ".join(str(location.get(k) or "") for k in ("city", "state", "country", "addressCountry")).strip(", ")
            rows.append((details["jobOpeningName"], details.get("jobOpeningShareUrl") or f"https://{board}.bamboohr.com/careers/{identifier}",
                location, details.get("description"), details.get("employmentStatusLabel"), identifier))
    elif platform == "freshteam":
        from startup_agent.discovery.structured_jobs import jobposting_nodes
        root = f"https://{board}.freshteam.com/jobs"
        page = BeautifulSoup(client.get(root).text, "html.parser")
        postings = jobposting_nodes(page)
        # Some employer lists link to individual pages containing the JSON-LD.
        for link in list(dict.fromkeys(a["href"] for a in page.select('a[href]')
                    if re.fullmatch(r"(?:https://"+re.escape(board)+r"\.freshteam\.com)?/jobs/[A-Za-z0-9_-]+(?:/[^?#]*)?", a["href"])))[:30]:
            from urllib.parse import urljoin
            postings.extend(jobposting_nodes(BeautifulSoup(client.get(urljoin(root, link)).text, "html.parser")))
        for item in postings:
            locations = item.get("jobLocation") or []
            if isinstance(locations, dict): locations = [locations]
            location = " / ".join(", ".join(str(v) for v in (p.get("address") or {}).values()) for p in locations)
            rows.append((item.get("title"), item.get("url"), location,
                         item.get("description"), ', '.join(item['employmentType']) if isinstance(item.get('employmentType'),list) else item.get("employmentType"), str(item.get("identifier") or item.get("url"))))
    elif platform in {"teamtailor", "personio"}:
        url = f"https://{board}.teamtailor.com/jobs.rss?per_page=100" if platform == "teamtailor" else f"https://{board}.jobs.personio.de/xml"
        doc = BeautifulSoup(client.get(url).text, "xml")
        if not doc.find("rss" if platform == "teamtailor" else "workzag-jobs"):
            raise ValueError("ATS XML feed changed shape or redirected to a non-feed page")
        for item in doc.find_all("item" if platform == "teamtailor" else "position")[:200]:
            def value(key):
                node = item.find(key)
                return node.get_text(" ", strip=True) if node else ""
            if platform == "teamtailor":
                location = " / ".join(n.get_text(" ", strip=True) for n in item.find_all(["city", "country"]))
                rows.append((value("title"), value("link"), location, value("description"), None, value("guid")))
            else:
                rows.append((value("name"), f"https://{board}.jobs.personio.de/job/{value('id')}",
                    value("office"), value("jobDescriptions"), value("employmentType"), value("id")))
    jobs = {}
    for title, url, location, description, employment, identifier in rows:
        if not title or not url or urlsplit(url).scheme != "https":
            continue
        key = normalize_job_url(url)
        if key in jobs:
            old = jobs[key]
            if location and location not in (old.location or ""):
                old.location = " / ".join(filter(None, [old.location, location]))
            continue
        jobs[key] = Job(job_title=title, job_url=url, company_name=target["company_name"],
            company_website=target["website"], source_name=f"{platform}:{board}",
            location=location or None, description=text(description) or None,
            employment_type=employment, source_job_id=str(identifier) if identifier else None, status="open")
    return list(jobs.values())
