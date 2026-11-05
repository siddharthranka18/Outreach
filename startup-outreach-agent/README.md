# Startup Job Outreach Agent

A modular, personal automation system designed to discover early-stage startups and identify software development internships or potential internship opportunities.

---

## Current Status: Prompt 4.2 (Final Matching Edge Cases Before Email Generation)

The matching engine includes targeted enhancements for edge cases:
- **Ambiguous Engineering Titles**: Roles like `GTM Engineer` and `Sales Engineer` are no longer classified as core SWE purely because the title contains "Engineer". The classifier inspects the actual job description for substantive software development responsibilities (`shipping code`, `production systems`, `backend services`, `APIs`), classifying as `OTHER_UNKNOWN` / `UNRELATED` if evidence is insufficient or purely sales/marketing, while preserving genuinely technical opportunities (such as Pogo's GTM Engineer).
- **Degree-Specific Eligibility**:
  - `PhD Required` / `Master's Required` in description: Evaluated against candidate's verified undergraduate education (B.Tech in progress) -> `Ineligible`.
  - `PhD Preferred` / `Master's Preferred`: -> `Potentially Eligible` with a warning flag.
  - `PhD in Title` with missing ATS description (e.g. Figma PhD Intern): Flagged as `Insufficient Information` with clear explanation rather than assuming student eligibility.
  - `Bachelor's / Undergrad Accepted`: Verified as directly matching.
  - Missing degree requirements: Never assumed or invented.
- **Tightly Coupled Project Proof Evidence**: Project evidence scoring eliminates overcounting on generic words ("AI", "API", "backend", "software"). Evidence is tied to verified technical implementations:
  - *SehatSaathi*: Specific RAG, vector databases (Qdrant), LLMs, AI agents, and FastAPI.
  - *Notification Engine*: Distributed queues (BullMQ, Kafka, RabbitMQ), event streaming, Redis brokers, and background workers.
  - *Smart Airport Ride Pooling*: Geospatial indexing (2dsphere), concurrency/locking, ride pooling dispatch algorithms, and high-throughput databases.
  - *Lipi Data Systems*: Verified internship responsibilities (React Native mobile, MVC REST route architecture, GPS telemetry).
- **Automated Tests**: 37 unit and integration tests passing with 100% test suite success.

> **Note:** Telegram alerts, Gmail draft creation, and automated outreach remain intentionally deferred to subsequent prompts.

---

## Architecture Flow

```
Candidate Profile (config/candidate_profile.yaml)
                     │
                     ▼
             OpportunityRanker
                     │
         Retrieves Stored Jobs from DB
                     │
                     ▼
          JobClassifier (Rule-Based)
   ├── OpportunityType (Internship vs FT vs Senior)
   └── JobCategory (AI/ML, Backend, Full Stack, Unrelated)
                     │
                     ▼
          EligibilityFilter (Decoupled)
   ├── Student Status & Experience Level
   └── Work Authorization & Geographic Constraints
                     │
                     ▼
       OpportunityScorer (Strict 0–100 pts)
   ├── Role Alignment (0–25 pts)
   ├── Technical Skills Overlap (0–40 pts, Scaled)
   ├── Project Proof-of-Work Evidence (0–25 pts)
   └── Experience / Seniority Fit (0–10 pts)
                     │
                     ▼
     Ranked Opportunities Leaderboard (--match)
```

---

## Directory Structure

```
startup-outreach-agent/
├── alembic/                 # Alembic migrations
├── config/
│   ├── candidate_profile.yaml # Configurable candidate profile
│   └── sources.yaml         # Configured discovery sources
├── data/
│   ├── raw/                 # Ingestion caches (gitignored)
│   └── processed/           # SQLite databases (gitignored)
├── docs/                    # Technical documentation
├── logs/                    # Runtime logs (gitignored)
├── src/
│   └── startup_agent/
│       ├── __init__.py
│       ├── main.py          # Application CLI entry point
│       ├── config/
│       │   ├── __init__.py
│       │   └── settings.py  # Settings and configuration loader
│       ├── database/
│       │   ├── engine.py    # SQLite engine with FK enforcement
│       │   ├── session.py   # Sessionmaker & transactional context
│       │   ├── models.py    # SQLAlchemy 2.x models
│       │   └── repositories.py # CompanyRepository & JobRepository
│       ├── discovery/
│       │   ├── base.py      # BaseDiscoverySource & DiscoveryResult
│       │   ├── y_combinator.py # YC Algolia directory adapter
│       │   ├── top_startups.py # TopStartups.io scraper adapter
│       │   ├── direct_ats.py   # Greenhouse, Ashby, Lever adapter
│       │   └── pipeline.py     # DiscoveryPipeline orchestrator
│       ├── matching/
│       │   ├── __init__.py
│       │   ├── profile.py       # Candidate profile dataclass and loader
│       │   ├── resume_extractor.py # PDF resume extractor & merger
│       │   ├── classifier.py    # Rule-based job category classifier
│       │   ├── eligibility.py   # Internship eligibility filter
│       │   ├── scorer.py        # Explainable 0-100 scoring engine
│       │   └── ranker.py        # Database job opportunity ranker
│       ├── models/
│       │   ├── company.py   # Company domain dataclass
│       │   └── job.py       # Job domain dataclass
│       └── utils/
│           ├── http_client.py   # Resilient HTTPX client
│           ├── logging_config.py# Logger
│           └── normalizers.py   # URL and name normalizers
├── tests/
│   ├── conftest.py          # Isolated in-memory SQLite fixtures
│   ├── test_company.py      # Company domain model tests
│   ├── test_config.py       # Configuration and YAML tests
│   ├── test_discovery.py   # Discovery adapter & pipeline tests
│   ├── test_main.py         # CLI and bootstrap tests
│   ├── test_matching.py     # Classification, scoring, and ranking tests
│   ├── test_normalizers.py  # Normalization & URL stripping tests
│   └── test_persistence.py  # Persistence, FKs, & deduplication tests
├── requirements.txt         # Core dependencies
├── README.md                # Project documentation
└── run.py                   # Root execution script
```

---

## Setup & CLI Execution

### 1. Install Dependencies
```bash
cd startup-outreach-agent
pip install -r requirements.txt
alembic upgrade head
```

### 2. Discover Opportunities
```bash
python run.py --discover
```

### 3. Match and Rank Opportunities
Score and rank all opportunities currently in the database against your candidate profile:
```bash
python run.py --match
```

Example output:
```text
================================================================================
       OPPORTUNITY MATCHING & RANKING REPORT: SIDDHARTH RANKA       
================================================================================
 Candidate Profile : Siddharth Ranka (B.Tech CSE, BML Munjal University)
 Expected Grad     : Jun 2028 | Status: Current Student
 Target Roles      : Software Development Intern, Backend Intern, AI/ML Intern, Full Stack Intern, Data Engineering Intern, General Software Engineering
 Verified Skills   : 37 technical signals loaded
================================================================================

Top 20 Evaluated Opportunities:

#1  [ 68.0/100] GTM Engineer @ Pogo
    Type & Status : [Regular Full-Time] | [Potentially Eligible]
    Category      : General Software Engineering | Location: United States/Canada
    Score Detail  : Role: 15.0/25 | Skills: 28.0/40 | Projects: 20.0/25 | Exp: 5.0/10 (Completeness: Adequate)
    Skills Match  : Llm, Rag
    Proof Points  : SehatSaathi (FastAPI, Hybrid RAG, Qdrant), Notification Engine (BullMQ, Redis, Node.js), Lipi Data Systems Internship (REST APIs, MVC)
    Work Auth     : On-site/hybrid role located in 'United States/Canada'. Does not assume visa sponsorship.
    Apply URL     : https://jobs.ashbyhq.com/joinpogo/f1ce7a4b-ad61-48d7-afc7-0088da404b81
    Website       : https://www.joinpogo.com
--------------------------------------------------------------------------------
#2  [ 58.0/100] Full Stack Engineer @ Pogo
    Type & Status : [Regular Full-Time] | [Potentially Eligible]
    Category      : General Software Engineering | Location: United States/Canada
    Score Detail  : Role: 15.0/25 | Skills: 15.0/40 | Projects: 25.0/25 | Exp: 3.0/10 (Completeness: Adequate)
    Skills Match  : Llm
    Proof Points  : SehatSaathi (FastAPI, Hybrid RAG, Qdrant), Notification Engine (BullMQ, Redis, Node.js), Lipi Data Systems Internship (REST APIs, MVC), Smart Airport Ride Pooling (Fullstack Architecture)
    Work Auth     : On-site/hybrid role located in 'United States/Canada'. Does not assume visa sponsorship.
    Notes/Warnings: Position specifies 2-4 years experience; student applicant will need strong justification.
    Apply URL     : https://jobs.ashbyhq.com/joinpogo/e6338078-0adc-4ab3-9f72-9e433a9a40bf
    Website       : https://www.joinpogo.com
--------------------------------------------------------------------------------
#3  [ 35.0/100] PhD Intern, AI Applied Scientist (2027) @ Figma
    Type & Status : [Internship] | [Insufficient Information]
    Category      : AI/ML Intern | Location: San Francisco, CA • New York, NY
    Score Detail  : Role: 25.0/25 | Skills: 0.0/40 | Projects: 0.0/25 | Exp: 10.0/10 (Completeness: Missing)
    Work Auth     : On-site/hybrid role located in 'San Francisco, CA • New York, NY'. Does not assume visa sponsorship.
    Notes/Warnings: Role title specifies PhD Intern, but job description is unavailable in ATS.; Insufficient job description information for reliable technical matching.
    Apply URL     : https://boards.greenhouse.io/figma/jobs/6207801004?gh_jid=6207801004
    Website       : https://www.figma.com
```

### 4. Run Automated Tests
```bash
pytest -v
```
*(37 passed in ~2s)*
