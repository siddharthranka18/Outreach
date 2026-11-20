"""Bounded public VC searches. Consider protocol inspected 2026-11-20.

Getro boards remain disabled: no public search protocol could be verified.
Never use the network-owner bearer API or a static third-party job snapshot.
"""
import argparse
import json
import logging
import re
import httpx
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.discovery.andhra_startup_map import _is_target_role
from startup_agent.discovery.hasjob import EARLY_CAREER
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_job_url

logger = logging.getLogger(__name__)
EARLY_TECH = re.compile(r"\b(?:intern(?:ship)?|junior|fresher|entry[- ]level|new[- ]grad(?:uate)?|trainee|apprentice)\b",re.I)


def india_location(text):
    """An unqualified remote label is insufficient for an India applicant."""
    text = text or ""
    if re.search(r"\b(?:US|USA|United States|EU|Europe|UK)\s*(?:only|residents|citizens)\b|\b(?:must|requires?)\b.{0,35}\b(?:visa|authorization)\b", text, re.I):
        return None
    if re.search(r"\bIndia\b", text, re.I):
        return "India / " + text
    if re.search(r"\b(?:worldwide|anywhere|global remote)\b", text, re.I):
        return "Remote / Worldwide"
    return None


def size_band(raw):
    """Retain the full published range; never truncate a band at the cap."""
    value = str(raw or "").replace(",", "").replace("\u2013", "-")
    match = re.fullmatch(r"\s*(\d+\s*-\s*\d+|\d+\+|\d+)\s*(?:employees)?\s*", value)
    if not match:
        return None
    band = match.group(1).replace(" ", "")
    if "-" in band and int(band.split("-")[0]) > int(band.split("-")[1]):
        return None
    return band


def parse_consider(payload, name, board_url):
    companies, jobs = {}, {}
    for group in payload.get("jobs", []):
        company = group.get("company") or {}
        domain = company.get("domain") or ""
        if not re.fullmatch(r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", domain):
            continue
        company_name = company.get("name") or domain
        # Prefer published bands; exact staff count is used only if no band exists.
        band = size_band((company.get("sizeLV") or {}).get("label"))
        band = band or size_band(company.get("staffCount"))
        stages = company.get("stages") or []
        stage = ", ".join(str(s) for s in stages if "employees" not in str(s)) or None
        source = board_url + "/companies/" + (company.get("slug") or "")
        companies[domain] = Company(company_name=company_name, website="https://" + domain,
            employee_count=band, funding_stage=stage, source_name=name, source_url=source,
            careers_url=source)
        for row in group.get("jobs", []):
            # Harvest all observed boards even when this particular role is senior.
            from startup_agent.discovery.direct_ats import extract_ats_target
            for observed in (row.get('applyUrl'),row.get('url')):
                if observed and extract_ats_target(observed,company_name,'https://'+domain):
                    companies[domain].ats_urls.append(observed)
            title = row.get("title") or ""
            places = [str(s) for s in row.get("locations", [])]
            places.extend(str(p.get("value") or p.get("label") or "")
                          for p in row.get("normalizedLocations", []) if isinstance(p, dict))
            location = india_location(" / ".join(places))
            url = row.get("applyUrl") or row.get("url") or ""
            if not location or not _is_target_role(title) or not EARLY_TECH.search(title):
                continue
            if urlsplit(url).scheme != "https":
                continue
            jobs[normalize_job_url(url)] = Job(job_title=title, job_url=url, source_name=name,
                company_name=company_name, company_website="https://" + domain, location=location,
                description=row.get("description"), source_job_id=str(row.get("jobId") or url),
                status="open")
    return DiscoveryResult(companies=list(companies.values()), jobs=list(jobs.values()))


class PortfolioDiscoverySource(BaseDiscoverySource):
    def __init__(self, name, url, options=None, enabled=True, http_client=None):
        super().__init__(name=name, enabled=enabled)
        self.url = (url or "").rstrip("/")
        self.options = options or {}
        self.http_client = http_client or HttpClient(public_only=True, timeout=20, max_retries=1)
        self.fetched_count = 0
        self.partial_error = ''

    def discover(self):
        if not self.is_enabled():
            return DiscoveryResult()
        if self.options.get("provider") != "consider":
            raise ValueError("Public Getro search unverified; leave this board disabled.")
        page = self.http_client.get(self.url + "/jobs").text
        marker = re.search(r"window.serverInitialData\s*=\s*", page)
        if not marker:
            raise ValueError("Consider page no longer exposes initial search state.")
        initial = json.JSONDecoder().raw_decode(page[marker.end():])[0]
        headers = {"X-CSRF-Token": initial["csrfToken"], "Accept": "application/json"}
        companies, jobs = {}, {}
        # Sequence is returned by the public UI; no guessed offset or private API.
        # A broad Remote search is only discovery; local India/worldwide checks still apply.
        queries=self.options.get('location_queries',[['India']])
        page_size=max(1,min(25,int(self.options.get('page_size',10))))
        for locations in queries[:2]:
            meta={"size":page_size}
            for _ in range(max(1,min(int(self.options.get("max_pages", 5)), 8))):
                try:
                    payload = self.http_client.post(self.url + "/api-boards/search-jobs", headers=headers,
                        json_data={"meta": meta, "board": initial["board"],
                                   "query": {"locations": locations}, "grouped": True}).json()
                except (httpx.HTTPError,OSError,ValueError) as exc:
                    if not companies:raise
                    self.partial_error=type(exc).__name__
                    logger.warning('%s kept %d company groups after a partial search failure.',self.name,len(companies))
                    return DiscoveryResult(companies=list(companies.values()),jobs=list(jobs.values()))
                if payload.get("errors"):
                    raise ValueError("Consider search rejected the public query.")
                self.fetched_count += sum(len(g.get("jobs", [])) for g in payload.get("jobs", []))
                result = parse_consider(payload, self.name, self.url)
                companies.update({c.website: c for c in result.companies})
                jobs.update({normalize_job_url(j.job_url): j for j in result.jobs})
                next_meta = payload.get("meta") or {}
                if not payload.get("jobs") or not next_meta.get("sequence") or next_meta == meta:
                    break
                meta = {**next_meta, "size": page_size}
        return DiscoveryResult(companies=list(companies.values()), jobs=list(jobs.values()))


def export_suggestions(companies, path):
    """A separate evidence file for human review; never update company_sizes.yaml."""
    output = {}
    for company in companies:
        if company.employee_count:
            output[urlsplit(company.website).hostname] = {
                "company_name": company.company_name, "employee_count": company.employee_count,
                "source_url": company.source_url, "funding_stage": company.funding_stage,
                "review_required": True,
            }
    path = Path(path)
    if path.name.casefold() == "company_sizes.yaml":
        raise ValueError("Write suggestions separately from reviewed evidence.")
    path.write_text(yaml.safe_dump(output, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    from startup_agent.config.settings import Settings
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", required=True)
    args = parser.parse_args()
    companies = []
    for source in Settings.load().sources:
        if source.type == "vc_portfolio" and source.enabled:
            try:
                companies.extend(PortfolioDiscoverySource(source.name, source.url, source.options).discover().companies)
            except Exception as exc:
                logger.warning("Portfolio export failed for %s: %s", source.name, type(exc).__name__)
    export_suggestions(companies, args.export)
