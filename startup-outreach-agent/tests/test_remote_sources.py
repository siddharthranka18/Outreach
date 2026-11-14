from unittest.mock import Mock

from startup_agent.discovery.himalayas import HimalayasDiscoverySource
from startup_agent.discovery.remotive import RemotiveDiscoverySource


EMPLOYER = ("studio.example", {"employee_count": "11-50", "source_url": "https://studio.example/about"})


def test_himalayas_paginates_and_checks_country_and_timezone():
    listing = {
        "title": "Backend Engineer", "companyName": "Tiny Studio",
        "seniority": ["Entry-level"], "employmentType": "Full Time",
        "locationRestrictions": [{"alpha2": "IN"}], "expiryDate": 4102444800,
        "applicationLink": "https://himalayas.app/jobs/backend",
    }
    client = Mock()

    def get(url, params):
        jobs = []
        if params.get("seniority") and params["page"] == 2:
            jobs = [
                listing, listing,
                {**listing, "applicationLink": listing["applicationLink"] + "-us",
                 "locationRestrictions": [{"alpha2": "US"}]},
                {**listing, "applicationLink": listing["applicationLink"] + "-timezone",
                 "timezoneRestrictions": ["UTC-5"]},
            ]
        elif params.get("seniority") and params["page"] == 1:
            jobs = [{**listing, "title": "Senior Backend Engineer", "seniority": ["Senior"]}]
        return Mock(**{"json.return_value": {"jobs": jobs}})

    client.get.side_effect = get
    result = HimalayasDiscoverySource({}, http_client=client, employers_by_name={"tiny studio": EMPLOYER}).discover()
    assert [(job.job_url, job.location, job.experience_level) for job in result.jobs] == [
        (listing["applicationLink"], "Remote / India", "Entry-level"),
    ]


def test_remotive_rejects_restricted_roles_and_unreviewed_employers():
    listing = {
        "title": "Backend Engineer Intern", "company_name": "Tiny Studio",
        "candidate_required_location": "Worldwide", "url": "https://remotive.com/remote-jobs/example",
    }
    client = Mock()
    client.get.return_value.json.return_value = {"jobs": [
        listing, listing,
        {**listing, "candidate_required_location": "APAC", "url": listing["url"] + "-apac"},
        {**listing, "company_name": "Unknown Studio", "url": listing["url"] + "-unknown"},
    ]}
    result = RemotiveDiscoverySource({"tiny studio": EMPLOYER}, http_client=client).discover()
    assert [(job.job_url, job.location) for job in result.jobs] == [(listing["url"], "Remote / Worldwide")]
