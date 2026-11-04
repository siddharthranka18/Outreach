# Startup Job Outreach Agent

A modular, personal automation system designed to discover early-stage startups and identify software development internships or potential internship opportunities.

---

## Current Status: Prompt 3 (Discovery Pipeline & Multi-Source Extraction)

The application includes:
- **Multi-Source Discovery Pipeline**: Clean orchestration layer executing source adapters independently with source-level error isolation.
- **Implemented Live Adapters**:
  - **Y Combinator**: Queries YC directory's public Algolia search API to extract high-signal hiring startups.
  - **TopStartups.io**: Scrapes public startup lists and open job postings, resolving clean company websites and application URLs.
  - **Direct ATS Boards**: Integrates official public REST APIs for **Greenhouse**, **Ashby**, and **Lever** to ingest advertised roles.
- **Resilient HTTP Client**: Built on `httpx` with exponential backoff retries, request timeouts, rate limiting, and standard User-Agent identification.
- **Foreign Key & Entity Resolution**: Automatically resolves company identities for incoming jobs and links records before transactional persistence.
- **Deduplication & Non-Destructive Merges**: Idempotent upserting that never overwrites existing non-null data with missing attributes.
- **Automated Tests**: 27 unit and integration tests with 100% mocked HTTP calls and isolated in-memory databases.

> **Note:** Telegram alerts, LLM personalized scoring/drafting, and Gmail dispatch remain intentionally deferred to subsequent prompts.

---

## Architecture Flow

```
Source Adapters (YC, TopStartups, ATS)
               │
               ▼ (Emits domain dataclasses)
        DiscoveryResult
               │
               ▼
     DiscoveryPipeline (Orchestration)
        ├── 1. Error Isolation & Execution
        ├── 2. Normalization & Validation
        ├── 3. Upsert Companies (CompanyRepository)
        ├── 4. Link & Resolve Company IDs
        └── 5. Upsert Jobs (JobRepository)
               │
               ▼
   Persistent SQLite Database (outreach.db)
```

---

## Directory Structure

```
startup-outreach-agent/
├── alembic/                 # Alembic migration environment and versions
│   └── versions/
│       └── 47d70b6f08a2_create_companies_and_jobs_tables.py
├── config/
│   └── sources.yaml         # Configured discovery sources
├── data/
│   ├── raw/                 # Raw ingestion caches (gitignored)
│   └── processed/           # SQLite databases & processed data (gitignored)
├── docs/                    # Technical documentation
├── logs/                    # Runtime log files (gitignored)
├── src/
│   └── startup_agent/
│       ├── __init__.py
│       ├── main.py          # Application CLI entry point
│       ├── config/
│       │   ├── __init__.py
│       │   └── settings.py  # Environment and YAML settings loader
│       ├── database/
│       │   ├── engine.py    # SQLite engine with foreign key enforcement
│       │   ├── session.py   # sessionmaker & transactional session_scope
│       │   ├── models.py    # SQLAlchemy 2.x CompanyModel & JobModel
│       │   └── repositories.py # CompanyRepository & JobRepository
│       ├── discovery/
│       │   ├── __init__.py
│       │   ├── base.py      # BaseDiscoverySource & DiscoveryResult
│       │   ├── y_combinator.py # Y Combinator Algolia directory adapter
│       │   ├── top_startups.py # TopStartups.io scraper adapter
│       │   ├── direct_ats.py   # Greenhouse, Ashby, Lever REST adapter
│       │   └── pipeline.py     # DiscoveryPipeline orchestrator
│       ├── models/
│       │   ├── company.py   # Company domain dataclass
│       │   └── job.py       # Job domain dataclass
│       └── utils/
│           ├── http_client.py   # Resilient HTTPX client with retries
│           ├── logging_config.py# Console and file logger
│           └── normalizers.py   # URL, website, and name normalizers
├── tests/
│   ├── conftest.py          # Isolated in-memory SQLite fixtures
│   ├── test_company.py      # Company domain model tests
│   ├── test_config.py       # Configuration and YAML tests
│   ├── test_discovery.py   # Adapter parsing & pipeline integration tests
│   ├── test_main.py         # CLI and bootstrap tests
│   ├── test_normalizers.py  # Normalization & URL stripping tests
│   └── test_persistence.py  # Persistence, FKs, & deduplication tests
├── .env.example             # Local environment variables template
├── .gitignore               # Repository ignore rules
├── alembic.ini              # Migration configuration
├── pytest.ini               # Pytest configuration
├── requirements.txt         # Core dependencies
├── README.md                # Project documentation
└── run.py                   # Root execution script
```

---

## Setup & Execution

### 1. Virtual Environment & Dependencies
```bash
cd startup-outreach-agent

# Create and activate virtual environment
python -m venv .venv

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1

# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
alembic upgrade head
```

### 2. Manual Discovery Run
To execute the discovery pipeline across all enabled sources:

```bash
python run.py --discover
```

Example report output:
```text
=================================================================
                STARTUP DISCOVERY RUN REPORT                    
=================================================================
 Execution Duration      : 6.29 seconds
 Sources Attempted       : 3
 Sources Successful      : 3
 Sources Failed          : 0
-----------------------------------------------------------------
 Companies Discovered    : 58
   - New Insertions      : 56
   - Existing Updated    : 2
-----------------------------------------------------------------
 Advertised Jobs Found   : 167
   - New Insertions      : 164
   - Existing Updated    : 3
=================================================================
```

### 3. Application Status Check
To verify configuration and database connectivity without running discovery:

```bash
python run.py
```

### 4. Running Automated Tests
```bash
pytest -v
```

---

## How to Add a New Discovery Adapter

1. Inherit from `BaseDiscoverySource` in `src/startup_agent/discovery/`:
```python
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult

class CustomSourceAdapter(BaseDiscoverySource):
    def discover(self) -> DiscoveryResult:
        # Extract companies and jobs
        return DiscoveryResult(companies=[...], jobs=[...])
```
2. Register the adapter class in `SOURCE_ADAPTER_REGISTRY` in [`src/startup_agent/discovery/pipeline.py`](file:///c:/Users/Administrator/Desktop/Outreach/startup-outreach-agent/src/startup_agent/discovery/pipeline.py).
3. Add a corresponding entry in [`config/sources.yaml`](file:///c:/Users/Administrator/Desktop/Outreach/startup-outreach-agent/config/sources.yaml) with `enabled: true`.

---

## Known Limitations & Source Policies

- **Y Combinator**: Queries the public frontend Algolia index. Does not bypass any access controls; if Algolia credentials rotate, the adapter dynamically extracts the new public key from the directory landing page.
- **TopStartups.io**: HTML scraping via BeautifulSoup. Subject to markup changes on `topstartups.io`.
- **Direct ATS (Greenhouse / Ashby / Lever)**: Uses public JSON endpoints. Custom or SSO-protected boards are not crawled.
- **LinkedIn**: Intentionally excluded in accordance with project safety guardrails and anti-scraping policies.
- **No Paid APIs**: All discovery uses free, public tiers and documented public endpoints.
