"""Check Venomics AI's official careers page for its internship listing."""

from bs4 import BeautifulSoup

from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient

CAREERS_URL = "https://venomics.ai/careers.html"
WEBSITE = "https://venomics.ai"


class VenomicsDiscoverySource(BaseDiscoverySource):
    def __init__(self, name="venomics_careers", enabled=True, http_client=None):
        super().__init__(name=name, enabled=enabled)
        self.http_client = http_client or HttpClient()

    def discover(self) -> DiscoveryResult:
        if not self.is_enabled():
            return DiscoveryResult()
        page = BeautifulSoup(self.http_client.get(CAREERS_URL).text, "html.parser")
        for card in page.select(".career-role"):
            heading = card.find("h3")
            summary = card.select_one(".career-role-summary")
            if not heading or heading.get_text(strip=True).casefold() != "internships" or not summary:
                continue
            if "machine learning" not in summary.get_text(" ", strip=True).casefold():
                continue
            description = "Internship programme includes machine learning and computational biology. Location and work arrangement are unlisted."
            if page.select_one('#apply a[data-email-local="careers"]'):
                description += " The employer invites applications at careers@venomics.ai."
            return DiscoveryResult(
                companies=[Company(
                    company_name="Venomics AI", website=WEBSITE, source_name=self.name,
                    source_url=CAREERS_URL, careers_url=CAREERS_URL,
                )],
                jobs=[Job(
                    job_title="Internships (Machine Learning / Computational Biology)",
                    job_url=CAREERS_URL, source_name=self.name, source_job_id="internships",
                    company_name="Venomics AI", company_website=WEBSITE,
                    employment_type="Internship", description=description, status="open",
                )],
            )
        return DiscoveryResult()
