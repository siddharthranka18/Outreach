"""Read a bounded sample of the public Startups Gallery India directory."""

import re
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from startup_agent.utils.http_client import HttpClient

INDIA_DIRECTORY = "https://startups.gallery/categories/locations/countries/india"


def gallery_leads(client: HttpClient) -> list[dict]:
    try:
        directory = BeautifulSoup(client.get(INDIA_DIRECTORY).text, "html.parser")
    except httpx.HTTPError:
        return []
    urls = {}
    for link in directory.select("a[href]"):
        url = urljoin(INDIA_DIRECTORY, link["href"])
        parsed = urlsplit(url)
        if parsed.netloc == "startups.gallery" and re.fullmatch(r"/companies/[a-z0-9-]+/?", parsed.path):
            urls[f"https://startups.gallery{parsed.path.rstrip('/')}"] = None
    leads = []
    for url in list(urls)[:10]:
        try:
            page = BeautifulSoup(client.get(url).text, "html.parser")
        except httpx.HTTPError:
            continue
        heading = page.find("h1")
        if not heading:
            continue
        size = re.search(r"(?m)^\s*(\d{1,3})\s*[-–—]\s*(\d{1,3})\s*$",
                         page.get_text("\n").split("Explore similar companies", 1)[0])
        links = {
            link.get_text(" ", strip=True).casefold(): link["href"]
            for link in page.select("a[href]")
            if link.get_text(" ", strip=True).casefold() in {"visit website", "view jobs"}
        }
        if not size or not heading.get_text(" ", strip=True) or not links.get("visit website"):
            continue
        leads.append({
            "company_name": heading.get_text(" ", strip=True),
            "website": links["visit website"],
            "careers_url": links.get("view jobs"),
            "employee_count": "-".join(size.groups()),
            "source_url": url,
            "ats_urls": [
                link["href"] for link in page.select("a[href]")
                if urlsplit(link["href"]).hostname in {
                    "jobs.ashbyhq.com", "jobs.lever.co", "job-boards.greenhouse.io", "boards.greenhouse.io",
                }
            ],
        })
    return leads
