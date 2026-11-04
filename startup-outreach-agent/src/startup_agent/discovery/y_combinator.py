"""Y Combinator startup directory discovery adapter."""

import logging
import re
from typing import Any, Dict, List, Optional
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.models.company import Company
from startup_agent.utils.http_client import HttpClient

logger = logging.getLogger("startup_agent.discovery.yc")

# Default YC public directory search configuration
DEFAULT_YC_APP_ID = "45BWZJ1SGC"
DEFAULT_YC_INDEX = "YCCompany_production"
YC_DIRECTORY_URL = "https://www.ycombinator.com/companies"


class YCombinatorDiscoverySource(BaseDiscoverySource):
    """Discovers startups from the public Y Combinator company directory."""

    def __init__(
        self,
        name: str = "y_combinator",
        enabled: bool = True,
        max_companies: int = 50,
        http_client: Optional[HttpClient] = None,
    ) -> None:
        super().__init__(name=name, enabled=enabled)
        self.max_companies = max_companies
        self.http_client = http_client or HttpClient()

    def _get_algolia_credentials(self) -> Dict[str, str]:
        """Extract public Algolia credentials from YC directory page."""
        try:
            resp = self.http_client.get(YC_DIRECTORY_URL)
            match = re.search(r'window\.AlgoliaOpts\s*=\s*(\{.*?\});', resp.text)
            if match:
                import json
                opts = json.loads(match.group(1))
                return {
                    "app_id": opts.get("app", DEFAULT_YC_APP_ID),
                    "api_key": opts.get("key", ""),
                    "index": DEFAULT_YC_INDEX,
                }
        except Exception as exc:
            logger.warning("Could not dynamically extract YC Algolia options: %s", exc)

        return {
            "app_id": DEFAULT_YC_APP_ID,
            "api_key": "",
            "index": DEFAULT_YC_INDEX,
        }

    def discover(self) -> DiscoveryResult:
        """Fetch and normalize companies from Y Combinator directory."""
        if not self.is_enabled():
            return DiscoveryResult()

        logger.info("Executing Y Combinator discovery (target limit: %d)...", self.max_companies)
        creds = self._get_algolia_credentials()
        app_id = creds["app_id"]
        api_key = creds["api_key"]
        index_name = creds["index"]

        if not api_key:
            logger.error("Missing Algolia API key for Y Combinator discovery.")
            return DiscoveryResult()

        query_url = f"https://{app_id}-dsn.algolia.net/1/indexes/{index_name}/query"
        payload = {
            "params": f"hitsPerPage={self.max_companies}&query=&facetFilters=[[\"isHiring:true\"]]"
        }
        headers = {
            "X-Algolia-Application-Id": app_id,
            "X-Algolia-API-Key": api_key,
        }

        resp = self.http_client.post(query_url, json_data=payload, headers=headers)
        data = resp.json()
        hits: List[Dict[str, Any]] = data.get("hits", [])

        companies: List[Company] = []
        for hit in hits:
            name = hit.get("name")
            website = hit.get("website")
            slug = hit.get("slug")

            # Fall back to YC profile if company has no direct website listed
            if not website and slug:
                website = f"https://www.ycombinator.com/companies/{slug}"

            if not name or not website:
                continue

            # Determine employee count string
            team_size = hit.get("team_size")
            employee_count = str(team_size) if team_size is not None else None

            # Funding stage / Batch
            stage = hit.get("stage")
            batch = hit.get("batch")
            funding_stage = f"{stage} ({batch})" if stage and batch else (stage or batch)

            # Industry
            industry = hit.get("industry")
            subindustry = hit.get("subindustry")
            ind_val = subindustry or industry

            hiring_status = "Actively Hiring" if hit.get("isHiring") else None
            yc_url = f"https://www.ycombinator.com/companies/{slug}" if slug else YC_DIRECTORY_URL

            try:
                company = Company(
                    company_name=name.strip(),
                    website=website.strip(),
                    source_name=self.name,
                    source_url=yc_url,
                    employee_count=employee_count,
                    industry=ind_val,
                    location=hit.get("all_locations"),
                    funding_stage=funding_stage,
                    careers_url=yc_url,
                    hiring_status=hiring_status,
                )
                companies.append(company)
            except Exception as exc:
                logger.debug("Skipping malformed YC record '%s': %s", name, exc)
                continue

        logger.info("Y Combinator discovery finished: extracted %d companies.", len(companies))
        return DiscoveryResult(companies=companies, jobs=[])

