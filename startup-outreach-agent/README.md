# Startup Job Outreach Agent

A modular, personal automation system designed to discover early-stage startups and identify software development internships or potential internship opportunities.

---

## Current Status: Prompt 1 (Application Foundation)

This repository currently implements the architectural foundation:
- Modular configuration loader (`python-dotenv` + `PyYAML`).
- Extensible `Company` domain model using dataclasses.
- Abstract discovery interface (`BaseDiscoverySource`) for upcoming source adapters.
- Structured dual-target logging (console and `logs/app.log`).
- Application entry point (`run.py` and `startup_agent.main`).
- Test suite with pytest.

> **Note:** Scraping, web scraping adapters, LLM email generation, Telegram bot integration, and automated sending are intentionally deferred to future prompts.

---

## Directory Structure

```
startup-outreach-agent/
├── config/
│   └── sources.yaml         # Configured discovery sources (YC, TopStartups, ATS)
├── data/
│   ├── raw/                 # Raw ingestion caches (gitignored)
│   └── processed/           # Processed datasets and DB files (gitignored)
├── docs/                    # Technical documentation
├── logs/                    # Runtime log files (gitignored)
├── src/
│   └── startup_agent/
│       ├── __init__.py
│       ├── main.py          # Application initialization workflow
│       ├── config/
│       │   ├── __init__.py
│       │   └── settings.py  # Environment and YAML settings loader
│       ├── discovery/
│       │   ├── __init__.py
│       │   └── base.py      # Abstract base class for discovery adapters
│       ├── models/
│       │   ├── __init__.py
│       │   └── company.py   # Company dataclass model
│       ├── database/
│       │   └── __init__.py  # Persistence placeholder
│       └── utils/
│           ├── __init__.py
│           └── logging_config.py # Centralized logging configuration
├── tests/
│   ├── __init__.py
│   ├── test_config.py       # Configuration and YAML tests
│   ├── test_company.py      # Company model validation tests
│   └── test_main.py         # Initialization and discovery contract tests
├── .env.example             # Template for local environment variables
├── .gitignore               # Repository ignore rules
├── requirements.txt         # Core dependencies
├── README.md                # Project documentation
└── run.py                   # Root execution script
```

---

## Setup Instructions

### 1. Prerequisites
- Python 3.11+
- Git

### 2. Virtual Environment Setup

Navigate to the project directory:

```bash
cd startup-outreach-agent
```

Create and activate a virtual environment:

```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the example environment template:

```bash
# Windows (PowerShell)
Copy-Item .env.example .env

# Linux / macOS
cp .env.example .env
```

Review or modify `.env` as needed:
```env
APP_ENV=development
LOG_LEVEL=INFO
DATABASE_URL=sqlite:///data/processed/outreach.db
```

---

## Running the Application

To run the foundation bootstrap routine:

```bash
python run.py
```

Expected output confirms environment, log level, and configured sources:
```
============================================================
   STARTUP JOB OUTREACH AGENT - FOUNDATION READY
============================================================
 Environment   : development
 Log Level     : INFO
 Base Directory: .../startup-outreach-agent
 Configured Sources (3):
   [ENABLED ] Y Combinator           (directory)
   [ENABLED ] TopStartups.io         (curated_list)
   [ENABLED ] Direct Career Pages    (direct_ats)
============================================================
Foundation initialized successfully. Ready for Prompt 2.
```

---

## Running Tests

Execute the test suite with pytest from the project root:

```bash
pytest
```

For verbose output:

```bash
pytest -v
```

