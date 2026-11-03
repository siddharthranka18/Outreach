# Startup Job Outreach Agent

A personal automation system that discovers startups, finds tech roles matching my profile, locates the right contact email, drafts personalized outreach, and lets me review everything from my phone. If no email can be found, it sends me the direct careers/job link instead.

**Goal:** Cut the manual work of finding startups, careers pages and emails, while keeping every email personal and human-approved.

---

## 1. Problem

- Applying through career pages alone gets lost in ATS/shared inboxes.
- Cold emailing works better at startups, but mass or generic emails get ignored (or land in spam).
- Finding startups, careers pages and verified emails by hand takes hours every day.

## 2. Solution in one line

An always-running pipeline that **finds → filters → finds contacts → drafts → asks me to approve from my phone → tracks and follows up**.

---

## 3. Core principles

1. **Human in the loop.** The system drafts; I approve and send. No bulk auto-sending.
2. **Quality over volume.** Only the top matches move forward. Daily send cap (15-20 max).
3. **Never a dead end.** Every company ends as an *email draft*, an *apply link*, or a *watchlist* entry.
4. **Free first.** Built on free tiers; upgrade only if needed.
5. **Respect rules.** Check robots.txt, rate-limit requests, no LinkedIn scraping, verify emails before sending.

---

## 4. High-level architecture

```
Discovery → Enrichment → Scoring → Contact finding → Routing → Draft generation → Review queue → Tracking / follow-ups
                                                                                         ↑
                                                                              Telegram (phone control)
```

### 4.1 Discovery
Sources of startups and roles (structured sources first):

- Hacker News "Who is hiring" via the free Algolia API
- YC Work at a Startup / company directory
- Funding news RSS (Entrackr, Inc42, YourStory for India; TechCrunch globally). Newly funded often means hiring soon
- Product Hunt API, GitHub org search (small technical teams)
- Manually added companies (e.g. `/add_company paarautonomy.com`)

### 4.2 Enrichment (careers page and roles)
Prefer public ATS JSON endpoints over HTML scraping:

| ATS | Endpoint pattern |
|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs` |
| Lever | `api.lever.co/v0/postings/{company}` |
| Ashby, Workable, Recruitee, Teamtailor | Similar public endpoints |

Fallback for custom careers pages: try common paths (`/careers`, `/jobs`, `/join-us`), footer links, sitemap, then Playwright for JS-heavy pages. Use `asyncio` + `httpx` with per-domain rate limiting.

### 4.3 Scoring
Defined once in a config file:

- Role keywords (e.g. robotics, ML, backend, computer vision)
- Seniority (intern, fresher, junior)
- Location / remote preference
- Exclusions ("senior", "10+ years")

Phase 1: keyword scoring. Phase 2: embeddings or LLM classification against my resume. Extra weights: funding recency, team size, tech-stack overlap. Only the top ~10-20% proceed.

### 4.4 Contact finding (cheapest first)
1. Email listed in the job post or careers page
2. Team / About page scraping for founder and engineering names
3. Hunter / Apollo API on shortlisted companies only (limited free credits)
4. Pattern inference (`first@`, `first.last@`) + verification (NeverBounce / ZeroBounce / Hunter verifier)
5. Public commit emails from the company's GitHub repos

Only verified or high-confidence addresses are used. Generic inboxes (info@, careers@) are labeled low priority.

### 4.5 Routing logic

```
Company has a matching role?
 ├── Yes
 │    ├── Email found & verified → draft email → review queue
 │    └── No email found → send me the direct careers/job link
 └── No matching role
      ├── Email found → low-priority "speculative outreach" list
      └── Nothing found → watchlist (re-check weekly)
```

Best case: do **both**. Apply on the careers page, then email the founder/hiring lead mentioning the application.

### 4.6 Draft generation
Inputs: company product page, job description, my project list. An LLM picks my most relevant project and writes a short (under ~120 words), specific email as structured JSON (`subject`, `body`, `why_this_company`) that is validated before use. Emails are plain text, with a clear, small ask.

### 4.7 Review queue (phone)
Drafts are saved as Gmail drafts (Gmail API `drafts.create`) or shown in Telegram. I review, tweak, and send. Roughly 30 seconds per email.

### 4.8 Tracking and follow-ups
- Daily job diffing to catch new postings
- One follow-up draft queued after 5 days of silence
- Sequence stops automatically when a reply arrives (Gmail API check)
- Status tracking per company/role

---

## 5. Phone control

### Telegram bot (primary)

**Alerts**

```
🔗 Apply directly (no email found)
Paar Autonomy: Robotics Software Intern
Match: 84%
Matched on: Python, ROS, computer vision
Apply: https://example.com/careers/robotics-intern

[Open link] [Mark applied] [Skip] [Keep watching]
```

```
✉️ Draft ready
Company: Example Robotics, Role: ML Intern, Match: 91%
To: founder@example.com (verified)

[View draft] [Approve] [Skip] [Snooze]
```

**Commands**

| Command | Action |
|---|---|
| `/status` | Pipeline health and last run |
| `/stats` | Roles found, drafts, sent, replies |
| `/pause` / `/resume` | Stop or restart the pipeline |
| `/run_now` | Trigger a run immediately |
| `/add_company <domain>` | Add a startup manually |
| `/digest` | Get the daily summary now |

**Daily digest (e.g. 9 AM):** "14 new roles, 5 shortlisted, 3 drafts ready, 1 reply."

### Optional: web dashboard
FastAPI + a small frontend (or Streamlit) opened in the phone browser, behind a login or Tailscale. Lists companies, scores, drafts, and statuses with approve/edit/send actions. Build only if Telegram isn't enough.

---

## 6. Hosting (free options)

| Option | Always-on? | Notes |
|---|---|---|
| **GitHub Actions** (cron) | No, scheduled only | Free; ideal for discovery, enrichment, scoring, drafting. Can *send* Telegram alerts but can't hold a live bot |
| **Home laptop / old PC** | Yes, if left on | Free; subject to power and WiFi cuts |
| **Oracle Cloud Always Free** | Yes | Free VM, but signup can be fiddly and idle accounts may be reclaimed |
| **Render / Fly.io / Railway / Koyeb** | Varies | Free tiers change often; check current terms |
| **Cheap VPS** (Hetzner, Contabo, DigitalOcean) | Yes | About $4-6/month; the most reliable paid option |

**Free hybrid plan (chosen):**
- GitHub Actions runs the pipeline every few hours
- Data stored in Supabase/Neon free Postgres (or SQLite committed back to the repo)
- Telegram receives alerts
- Button taps are handled by a workflow that polls for pending Telegram updates every 5-10 minutes (small delay, free)
- If instant response is needed later, run the bot on a home machine or free VM and keep Actions for heavy jobs

---

## 7. Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| HTTP / async | `httpx`, `asyncio` |
| Browser fallback | Playwright |
| Data models | Pydantic |
| DB / ORM | SQLAlchemy + SQLite (Postgres via Supabase/Neon when hosted) |
| Scheduling | GitHub Actions cron (APScheduler if self-hosted) |
| LLM | Free-tier LLM API (Gemini/Groq or similar) or Claude API; keyword scoring first |
| Email | Gmail API (drafts, reply detection) |
| Alerts / control | Telegram bot (`python-telegram-bot` or `aiogram`) |
| Config / secrets | `config.yaml` for preferences, `.env` / GitHub Secrets for keys |

---

## 8. Data model

**companies:** `id`, `name`, `website`, `domain`, `source`, `funding_info`, `careers_url`, `ats_type`, `first_seen`, `last_checked`

**jobs:** `id`, `company_id`, `title`, `url`, `description`, `location`, `match_score`, `matched_keywords`, `status` (new / seen / applied / skipped / closed), `first_seen`

**contacts:** `id`, `company_id`, `name`, `role`, `email`, `email_status` (verified / guessed / none), `source`

**outreach:** `id`, `company_id`, `job_id`, `contact_id`, `route` (email / apply-link / watchlist), `draft_subject`, `draft_body`, `status` (drafted / approved / sent / followed-up / replied / closed), `sent_at`, `follow_up_due`

**events:** `id`, `entity`, `type`, `timestamp`, `details` (audit log of runs, errors, taps)

Dedupe by `job.url` so I never get the same role twice.

---

## 9. Suggested project structure

```
startup-outreach-agent/
├── config.yaml              # roles, seniority, location, exclusions, caps
├── .env.example             # API keys template (never commit real keys)
├── requirements.txt
├── README.md
├── src/
│   ├── db/                  # models, session, migrations
│   ├── discovery/           # hn.py, yc.py, funding_rss.py, producthunt.py
│   ├── ats/                 # greenhouse.py, lever.py, ashby.py, generic_careers.py
│   ├── scoring/             # keyword.py, llm_scorer.py
│   ├── contacts/            # page_scraper.py, hunter.py, patterns.py, verifier.py, github_emails.py
│   ├── routing/             # decide_route.py
│   ├── drafting/            # prompts.py, generator.py, gmail_drafts.py
│   ├── bot/                 # telegram_bot.py, handlers.py
│   ├── tracking/            # followups.py, reply_checker.py
│   └── main.py              # pipeline entry point
├── tests/
└── .github/workflows/
    ├── pipeline.yml         # scheduled run
    └── bot_poll.yml         # poll Telegram taps
```

---

## 10. Build order

| Phase | Deliverable |
|---|---|
| 1 | DB schema, HN + Greenhouse/Lever/Ashby ingestion, keyword role matcher; print results in terminal |
| 2 | Careers-page finder, email-or-link routing, dedupe |
| 3 | Telegram daily digest with links (no buttons yet) |
| 4 | Move to GitHub Actions so it runs without me |
| 5 | Telegram buttons (Approve / Skip / Mark applied) via polling |
| 6 | Contact finder with verification |
| 7 | LLM scoring and draft generation, Gmail drafts |
| 8 | Follow-ups, reply detection, stats, error alerts |

**Rule:** don't move on until the current phase reliably works. Phase 1 alone is already useful.

---

## 11. Safety and quality guardrails

- **Daily send cap** enforced in code (15-20 max)
- **Human approval** before any email is sent
- **Verify emails** before use; avoid bounces that hurt sender reputation
- **Plain-text emails**, minimal links, no tracking pixels
- **Rate limits and robots.txt** respected when scraping
- **No LinkedIn scraping** (violates terms, risks account bans)
- **Secrets** only in `.env` / GitHub Secrets, never in code
- **Error alerts** to Telegram when a job fails
- **Link check** (HTTP 200, role still open) before sending a job link
- **Backups** of the database
- **Label confidence**: roles parsed from custom pages are marked "check manually"

---

## 12. Email principles (to actually get replies)

- Send to the founder, CTO, or engineering/product lead, not info@ or HR
- Under ~120 words, with a specific reason for *this* company
- Include proof of work (project, GitHub, demo) that can be checked in 30 seconds
- One small ask (e.g. a short chat, or a quick look at my work)
- Follow up once after 4-5 days
- Where possible, warm up first (follow/comment on the founder's posts), contribute to open source, and ask for referrals

---

## 13. Open decisions

1. Target roles and location (e.g. robotics/ML intern, India or remote)
2. Python comfort level (decides how much code to write per phase)
3. Hosting: free hybrid (Actions) vs. home machine vs. cheap VPS later
4. LLM choice for scoring and drafting (free tier vs. Claude API)
5. Whether to add the web dashboard, or stay Telegram-only

---

## 14. Why build instead of buying

Existing tools (Otter, AutoApply, Aura Pulse, Job Beast, dm-the-boss, PitchMeAI and others) cover parts of this, but this project gives:

- Full customization of sources, scoring, and send limits
- The email-**or**-career-link fallback
- Phone control via Telegram
- Zero cost on free tiers
- A portfolio project that can itself be linked in cold emails

---

## 15. Success metrics

- New matching roles surfaced per week
- % of shortlisted companies with a verified contact or apply link
- Time spent per day on outreach (target: under 20 minutes)
- Reply rate and interview conversions
- Bounce rate (keep very low)
