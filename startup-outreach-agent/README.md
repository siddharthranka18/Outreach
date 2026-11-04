# Startup Job Outreach Agent

A modular, personal automation system designed to discover early-stage startups and identify software development internships or potential internship opportunities.

---

## Current Status: Prompt 4 (Resume-Based Job Matching & Ranking)

The application includes:
- **Configurable Candidate Profile**: Located at `config/candidate_profile.yaml` with verified education, skills, projects (SehatSaathi, Notification Engine, Smart Airport Ride Pooling), and internship experience (Lipi Data Systems).
- **Resume Management & Safe Supplementation**: `ResumeExtractor` parses local PDF resumes with `pypdf`, extracting technical signals without overwriting verified manual configuration.
- **Rule-Based Job Classification**: `JobClassifier` categorizes postings into `Software Development Intern`, `Backend Intern`, `AI/ML Intern`, `Full Stack Intern`, `Data Engineering Intern`, `General Software Engineering`, or `Unrelated or Unsuitable`.
- **Internship Eligibility Engine**: `EligibilityFilter` categorizes candidates into `Eligible`, `Potentially Eligible`, `Ineligible`, or `Insufficient Information` based on student status, experience caps, and location.
- **Explainable Match Scoring**: `OpportunityScorer` computes a deterministic 0–100 relevance score across Category Alignment (25%), Technical Skills Overlap (30%), Project Proof-of-Work (20%), Eligibility (15%), Location (10%), and Company Scale (+5% bonus). No LLM hallucinations or pseudo-probabilities.
- **Opportunity Ranker**: `OpportunityRanker` queries stored database jobs, evaluates compatibility, and ranks opportunities with transparent reasoning, matching/missing skills, and warnings.
- **Automated Tests**: 32 unit and integration tests passing deterministically.

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
                     │
                     ▼
           EligibilityFilter (Student/Intern/Exp)
                     │
                     ▼
          OpportunityScorer (0–100 pts)
    ├── Category Alignment (25 pts)
    ├── Technical Skills Overlap (30 pts)
    ├── Project Alignment (20 pts)
    ├── Eligibility (15 pts)
    ├── Location & Work Arrangement (10 pts)
    └── Startup Scale Bonus (up to +5 pts)
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
==============================================================================
       OPPORTUNITY MATCHING & RANKING REPORT: SIDDHARTH RANKA       
==============================================================================
 Target Education : B.Tech in Computer Science and Engineering
 Institution      : BML Munjal University (Expected Jun 2028)
 Verified Skills  : 37 technical signals loaded
==============================================================================

Top Ranked Opportunities:

#1  [ 83.0/100] Full Stack Engineer @ Pogo [Potentially Eligible]
    Category      : General Software Engineering
    Location      : United States/Canada
    Skills Match  : Llm
    Profile Proof : SehatSaathi (FastAPI, Hybrid RAG, Vector DB), Notification Engine (BullMQ, Redis, Node.js), Lipi Data Systems Internship (REST APIs, MVC), Smart Airport Ride Pooling (Fullstack Architecture)
    Apply URL     : https://jobs.ashbyhq.com/joinpogo/e6338078-0adc-4ab3-9f72-9e433a9a40bf
    Website       : https://www.joinpogo.com
    Notes/Warnings: On-site/hybrid location: 'United States/Canada'. May require work authorization or relocation.
------------------------------------------------------------------------------
#2  [ 78.0/100] GTM Engineer @ Pogo [Potentially Eligible]
    Category      : General Software Engineering
    Location      : United States/Canada
    Skills Match  : Llm, Rag
    Profile Proof : SehatSaathi (FastAPI, Hybrid RAG, Vector DB), Notification Engine (BullMQ, Redis, Node.js)
    Apply URL     : https://jobs.ashbyhq.com/joinpogo/f1ce7a4b-ad61-48d7-afc7-0088da404b81
    Website       : https://www.joinpogo.com
------------------------------------------------------------------------------
#3  [ 63.0/100] PhD Intern, AI Applied Scientist (2027) @ Figma [Potentially Eligible]
    Category      : AI/ML Intern
    Location      : San Francisco, CA • New York, NY
    Profile Proof : SehatSaathi (FastAPI, Hybrid RAG, Vector DB)
    Apply URL     : https://boards.greenhouse.io/figma/jobs/6207801004
    Website       : https://www.figma.com
```

### 4. Run Automated Tests
```bash
pytest -v
```
*(32 passed in ~10s)*
