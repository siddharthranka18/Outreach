# Outreach platform architecture and workflow

Verified snapshot dated 19 November 2026. This reference describes the checked-in Python implementation, the local Apps Script implementation, and the Oracle VM units inspected on this date. Runtime secrets are omitted.

## 1. Purpose and current deployment

The platform helps Siddharth Ranka find technical internships and early-career opportunities at small companies, review opportunities on Telegram, and approve cold enquiry emails with a resume attachment.

The main operational path is:

1. An Oracle Cloud Ubuntu VM starts a Python discovery run twice a day.
2. Source adapters fetch company and job records.
3. The application normalizes and stores records in SQLite.
4. Company-size and candidate-eligibility filters determine which jobs can enter the shortlist.
5. Deterministic scoring orders those jobs against the candidate profile.
6. A separate careers-research pass looks for public hiring inboxes for potential enquiries.
7. Gemini creates a limited number of enquiry drafts.
8. Python sends a signed batch to the existing Google Apps Script web app.
9. Apps Script checks the private Google Sheet for previous actions and sends eligible Telegram cards.
10. Telegram webhook callbacks update saved actions, accept draft edits, and send an approved email through Google MailApp with the Drive resume attached.

The product target is 25–30 or more applications or outreach attempts per day. The implementation has no guaranteed daily supply of qualifying opportunities. A run may finish with zero delivered cards.

## 2. Architecture diagram

```mermaid
flowchart TD
    Timer["Oracle VM systemd timer<br/>09:15 and 18:15 Asia/Kolkata"] --> Runner["Python run.py --hosted-daily"]
    Sources["Boards, directories, official career pages<br/>and public ATS APIs"] --> Discovery["Discovery adapters"]
    Runner --> Discovery
    Discovery --> Store[("VM SQLite database")]
    Store --> Rules["Company-size gate<br/>Role, experience, degree and location checks"]
    Profile["candidate_profile.yaml"] --> Rules
    Rules --> Rank["Deterministic match scoring"]
    Rank --> JobCards["Application cards"]
    Gallery["Startups Gallery India<br/>and reviewed companies"] --> Careers["Live careers and hiring-email checks"]
    Careers --> Drafts["Gemini enquiry drafts"]
    Profile --> Drafts
    JobCards --> Signed["HMAC-signed HTTPS batch"]
    Drafts --> Signed
    Signed --> Apps["Google Apps Script /exec endpoint"]
    Apps <--> Sheet[("Private Google Sheet<br/>actions, drafts and delivery status")]
    Apps --> Telegram["Existing Telegram bot"]
    Telegram --> Hook["Authenticated webhook route"]
    Hook --> Sheet
    Hook --> Mail["MailApp.sendEmail after approval"]
    Resume["Personal resume PDF in Google Drive"] --> Mail
```

The Python discovery process runs on the VM. Telegram interaction handling runs in Apps Script, so buttons can be used from the phone between discovery runs.

## 3. Source inventory

### 3.1 Sources enabled in sources.yaml

There are ten configured entries, with nine enabled. Source-level success means the adapter completed. It can return zero eligible records.

| Source | Fetching method | Scope and important limits |
| --- | --- | --- |
| Reviewed Startup Careers | HTML selectors on official employer pages | LivingAI, Curvvtech and MAGDOX. MAGDOX was added on 19 November. Titles, locations and descriptions are reviewed adapter records, and live selectors verify that a listing is still present. |
| Venomics AI Careers | Official careers HTML | Checks for the machine-learning internship programme. Location is unlisted and the route explicitly asks for location confirmation. |
| Himalayas | Free public JSON search API | Searches country IN for Intern employment and Entry-level seniority, up to three pages per query. Requires a reviewed employer slug or matching reviewed company name. Checks expiry, country and timezone metadata. |
| Hasjob | Public Atom feed at https://hasjob.co/feed | Technical early-career titles published in the last 30 days. Extracts employer website and listing text. Missing employee counts can prevent these jobs from passing matching. |
| Andhra Startup Map Fresher Jobs | Public HTML at https://www.andhrastartupmap.in/jobs | Parses fresher technical listings and employer/application links. Imported listings still pass the platform's own gates. |
| Y Combinator | Public directory search data and employer hiring pages | Discovers hiring companies through the site's search integration, with company-size filtering and region cohorts. Fetches company job pages. Public-page rate limits can cause retries or partial results. Default query limit is 75 companies per region query before deduplication. |
| TopStartups.io | Public jobs-page HTML at https://topstartups.io/jobs/ | Extracts companies and jobs. Coverage depends on the page content the adapter receives. |
| Wellfound India | Public HTML, beginning at https://wellfound.com/location/india | Up to five pages per run. Source adapter filters published employee bands and early-career metadata. Access failures and page changes can reduce coverage. |
| Direct Career Pages & ATS | Public per-employer JSON APIs | Boards in company_sizes.yaml plus boards derived from other discovered job links. Supports Greenhouse, Lever, Ashby and Recruitee. |

The Reviewed Startup Careers description in sources.yaml still mentions LivingAI and Curvvtech. Its implementation also includes MAGDOX.

### 3.2 Implemented source currently disabled

Remotive has an adapter and configuration entry, with enabled set to false. It was trialled and returned zero qualifying listings among reviewed employers.

Its adapter fetches https://remotive.com/api/remote-jobs once per discovery call. It accepts technical internship/fresher titles with explicit Worldwide/Anywhere or India location text, requires a reviewed employer name, retains the Remotive application URL, and adds source attribution. Broad APAC or unspecified Remote text is excluded by that adapter.

### 3.3 Company discovery and research outside the primary source registry

| Source | Current use |
| --- | --- |
| Startups Gallery | Called during hosted enquiry research. Reads the India directory and up to ten linked company profiles. Extracts the displayed employee band, employer website, careers link and supported ATS URLs. |
| bharat.digital funding CSV | A separate --funding-leads command reads the openly licensed funding CSV, filters the last 30 days, selected technical categories, and pre-seed/seed/angel/Series A. Prints leads and references for review. The Oracle timer currently runs --hosted-daily only, so it does not execute this standalone funding command. |
| Reviewed accelerator/portfolio references | Company-size configuration includes references such as Antler and Blume. These are curated evidence entries, rather than general-purpose portfolio crawlers. |
| Entrackr | Manual funding research source. Discovered employers require website, size and careers verification before configuration. |
| Remote Rocketship and Working Nomads | Manual research sources. Their job feeds are absent from the enabled adapters. |
| Google site searches | Manual ATS-board discovery. Verified boards can be added to company_sizes.yaml for recurring API checks. |

QuickHyre, Internshala, SimplifyJobs, Adzuna, Jooble, The Muse, USAJOBS, Apify, RapidAPI, Reddit and Scrapling are absent from the active source adapters. Prior discussion and research did not activate these integrations.

### 3.4 Current employer evidence and board configuration

The following is generated from company_sizes.yaml. These entries support company-size checks and, when an ATS URL exists, automatic board fetching. An entry does not imply that a suitable opening currently exists.

| Company | Domain | Published size | Configured careers or board use |
| --- | --- | --- | --- |
| TrueFoundry | truefoundry.com | 51-200 | https://www.truefoundry.com/careers |
| MAGDOX | magdox.io | 2-10 | https://magdox.io/careers/ |
| Altimate AI | altimate.ai | 11-50 | https://jobs.ashbyhq.com/altimate |
| Composio | composio.dev | 11-50 | https://jobs.ashbyhq.com/composio |
| Airbound | airbound.com | 51-200 | https://www.airbound.com/careers |
| Stance Health | stance.health | 11-50 | https://www.stance.health/careers |
| Atomicwork | atomicwork.com | 51-200 | https://www.atomicwork.com/company/careers |
| WizCommerce | wizcommerce.com | 51-200 | https://wizcommerce.com/careers/ |
| livingai.in | livingai.in | 11-50 | Size evidence for discovered listings |
| curvvtech.com | curvvtech.com | 2-10 | Size evidence for discovered listings |
| Enterpret | enterpret.com | 11-50 | https://job-boards.greenhouse.io/enterpret |
| Drivetrain | drivetrain.ai | 51-200 | https://jobs.lever.co/drivetrain |
| Karya | karya.in | 51-200 | https://job-boards.greenhouse.io/karya |
| Merkle Science | merklescience.com | 51-200 | https://jobs.lever.co/merklescience |
| JobTwine | jobtwine.com | 11-50 | https://jobs.lever.co/jobtwine |
| Meraki Labs | merakilabs.com | 2-10 | https://jobs.ashbyhq.com/Meraki-Labs |
| hevodata.com | hevodata.com | 201-500 | Size evidence for discovered listings |
| nestack.com | nestack.com | 11-50 | Size evidence for discovered listings |
| diligencevault.com | diligencevault.com | 51-200 | Himalayas employer lookup |
| Venomics AI | venomics.ai | 2-10 | https://venomics.ai/careers.html |

Each YAML entry includes its evidence source URL and, where available, the date it was checked. Hevo Data's 201–500 band exceeds the configured size cap and therefore fails the small-company gate.

## 4. Discovery, normalization and storage

The discovery pipeline resolves enabled adapters, isolates source exceptions, collects company/job objects, hydrates known company sizes and expands supported public ATS boards exposed by discovered links.

ATS board expansion requires a confirmed eligible company size. It deduplicates platform/board-token pairs, fetches the board's current jobs, and adds the results to persistence.

Supported public endpoints include:

- Greenhouse: https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
- Lever: https://api.lever.co/v0/postings/{board}?mode=json
- Ashby: https://api.ashbyhq.com/posting-api/job-board/{board}
- Recruitee: https://{board}.recruitee.com/api/offers

SQLite tables are companies, jobs and email_drafts. The default database is data/processed/outreach.db. Alembic manages schema migrations.

Company identity uses normalized websites and names. Job upserts attempt source-specific ID, normalized URL, then title/location matching within a company. Existing skipped/applied local statuses are preserved during rediscovery.

URL normalization removes common tracking parameters and trailing slashes. LivingAI's role anchors are preserved because multiple roles share one careers-page URL.

The database retains historical records. General discovery does not uniformly mark every missing posting closed. Freshness checks vary by source. Re-fetching a source alone is insufficient evidence that every previously stored job remains open.

## 5. Company-size gate

Current profile settings are:

```yaml
strict_fresher_only: true
max_required_experience_years: 2
small_startup_max_employees: 200
allow_unknown_company_size: false
```

| Published value | Gate result |
| --- | --- |
| 2–10, 11–50, 51–200 | Eligible within the 200-person cap |
| Exact count of 90 or 125 | Eligible |
| 201–500 | Ineligible |
| Missing size | Unknown and excluded |
| 100+ | Unknown because no upper bound is established |
| 101–500 | Unknown because the range crosses the cap |

Size evidence can come from the source record, curated evidence file, or previously stored company information. The size filter measures headcount. It does not independently establish funding stage, validate corporate ownership, or prove that a company is a startup. Published counts may become stale.

## 6. Fresher, technical-role and degree conditions

The classifier and eligibility filter are deterministic Python rules.

### 6.1 Role families

Primary families include software development, backend, full stack and AI/ML. Secondary families include frontend, data engineering and data science. General software engineering is also classified.

Excluded title patterns cover sales, marketing, HR/recruitment, legal, accounting/finance, customer support, design, video/content work and mechanical/electrical/civil/hardware disciplines.

Ambiguous GTM, sales-engineering and solutions-engineering titles require software responsibilities in a sufficiently detailed description. At least two recognized software indicators are required for this evidence check.

### 6.2 Early-career classification

- Seniority expressions such as senior, lead, staff, principal, manager, director, architect and substantial stated experience take precedence.
- Intern, internship, student, trainee and apprentice markers can identify internships.
- Co-op and student-placement markers identify student placements.
- Graduate, new grad, campus hire, entry-level, fresher, associate and junior markers identify graduate/entry-level roles.
- Unknown opportunities and ordinary full-time positions fail the strict fresher rule.
- Seniority classification uses title and experience metadata; ordinary description wording is handled by subsequent checks.

The experience filter examines explicit year ranges and single-year requirements in the text. A stated minimum above two years fails. A two-year minimum can produce a warning. A range such as 0–3 years is evaluated by its minimum, so it may pass this particular experience check. This is regex extraction rather than a full interpretation of every sentence.

### 6.3 Degree requirements

Mandatory PhD or Master's requirements generally reject the undergraduate candidate. A PhD-targeted title without detailed requirements is rejected. A Master's-targeted title without details is insufficient information. Degree preferences can produce warnings. Specific matching patterns determine the result, so unusual wording can be missed.

### 6.4 Location and work authorization

India-based internships and student placements can be fully eligible. The general eligibility filter recognizes a fixed list of India locations and remote keywords. It flags recognized US/Canada-only remote patterns and international on-site/hybrid roles.

The Himalayas adapter additionally requires country metadata explicitly permitting India or an empty country restriction list representing worldwide availability. Its timezone filter accepts unrestricted listings or explicit UTC+5:30/UTC+05:30.

The Remotive adapter has its own stricter location-text checks, but it is disabled.

A global comprehensive country/visa rule has not been implemented across all sources. For example, an EU restriction in unfamiliar wording can evade the general remote check. A job classified as eligible still requires reading the actual employer requirements.

### 6.5 Which classifications actually reach Telegram

Routes normally require EligibilityStatus.ELIGIBLE and a stored open job with an application URL.

Potentially Eligible and Insufficient Information routes are excluded from the normal job digest. The specific exception is the Venomics careers internship with missing location, displayed as Confirm location.

Graduate/entry-level full-time roles currently receive Potentially Eligible because the candidate is expected to graduate in June 2028. Consequently, even a well-matched junior role can be absent from Telegram. Searching entry-level listings expands discovery but does not automatically override this routing rule.

Descriptions shorter than 80 characters generally prevent full eligibility. Unsupported technical roles and recruiter listings explicitly saying they hire for a client are also filtered by the routing checks.

## 7. Match scoring

The score orders eligible candidates and is bounded between 0 and 100.

| Component | Maximum | Main evidence |
| --- | --- | --- |
| Role-family alignment | 25 | Technical domain |
| Skills | 40 | Candidate overlap with detected posting technologies |
| Project evidence | 25 | Recognized project/architecture patterns |
| Experience fit | 10 | Internship/student/entry-level classification and requirements |

Role alignment awards 25 to primary families, 18 to secondary families, 15 to general SWE and 5 to other technical matches. Skill scoring uses detected posting technologies rather than every word in a description. A single detected technology caps the skill component at 15 points, two cap it at 28, and three or more allow 40. Project evidence includes patterns for RAG, queues, geospatial/concurrency, mobile/MVC and LangChain tooling.

No universal high minimum score is set for hosted delivery. Eligibility and saved actions can exclude a high-scoring role; eligible lower-scoring roles can still appear.

Matching and ranking do not invoke Gemini. The ranker uses hand-written patterns and profile facts, and parts of the project scoring refer to named projects directly in code.

## 8. Candidate facts and project selection

The current profile describes a third-year B.Tech CSE student graduating June 2028 and includes the Lipi Data Systems software-development internship.

| Application context | Draft evidence |
| --- | --- |
| AI/LLM/RAG | SehatSaathi |
| Backend | Smart Airport Ride Pooling Backend or Notification Engine, selected using supported role and technology evidence |
| Full stack | KarigarFlow |
| Mobile | crossTune |
| Other compatible evidence | AI Shopping Assistant |

Internship experience is added when the posting explicitly asks for prior internship evidence. Personal facts come from candidate_profile.yaml.

The NYC 311 analytics report discussed on 18 November is currently outside the YAML project list. Application messages written in chat are separate from the production drafting configuration. Short YC introduction messages are also currently written manually; the digest does not automatically supply a company summary and YC introduction.

## 9. Cold-enquiry research and drafting

Hosted delivery combines existing discovered employers, reviewed company records and the bounded Startups Gallery India sample. It prioritizes reviewed companies and examines up to 20 size-eligible careers candidates per call.

For each candidate it checks an official HTTPS careers page, follows a bounded sequence of employer-domain redirects, and validates that target network addresses are public. Linked supported ATS boards may supply additional job records.

Cold-email eligibility requires:

1. A known company name, website, careers URL and acceptable employee count.
2. A reachable employer careers page.
3. No detected early-career technical role on the inspected page or associated board.
4. A publicly published hiring address on the employer's domain.
5. No matching application route that takes priority for this company.
6. No previous Skip/Mark Applied for the enquiry and no sent/sending/uncertain outreach for its recipient.

The code accepts recognized hiring inboxes such as careers/jobs/hiring/recruitment/talent. A named email needs nearby hiring context or a reviewed contact. Reviewed contacts must still be found on the current page. General business inboxes are not automatically considered hiring contacts.

Enquiry delivery is email-only. Companies with only a careers form do not produce enquiry cards.

Limitations include heuristic detection of live openings, bounded page exploration, and source failures. There is no guaranteed exhaustive search of every job on an employer's website. An early-career technical role can suppress an enquiry even if it is not a strong candidate match.

Gemini uses the configured model gemini-3.1-flash-lite. The draft prompt supplies company context and selected candidate evidence, asks for concise subject/body JSON, and treats source text as factual input rather than instructions.

Up to five new enquiry drafts are generated per run. Existing Sheet drafts, including edits, are reused. Missing Gemini credentials leave the new-draft budget at zero. A generation/quota error stops new generation for the rest of that digest; saved drafts can still be reused. Requests have a 25-second timeout and no automatic quota retry.

The draft subject is limited to 150 characters and the generated body to 120 words. Apps Script validates the full submitted draft again.

## 10. Hosted batch, actions and duplicate suppression

Python sends an HMAC-SHA256-signed JSON payload over HTTPS using OUTREACH_SYNC_SECRET. The receiver validates the signature, a timestamp within ten minutes, run identity, card count, URLs and draft shapes.

At most 100 cards are included in a batch. Ordering leaves the first 20 positions for job cards, then enquiries, then remaining jobs. Apps Script sends at most 30 review cards per delivery call.

The private Sheet named Imported Outreach History stores:

- local_job_id
- job_url
- job_status
- gmail_status
- draft_json
- last_delivery_run

Hosted job actions live primarily in this Sheet. The VM's SQLite shortlist can therefore include jobs already handled in Telegram. Apps Script is the final suppression gate.

| Stored state | Delivery behaviour |
| --- | --- |
| Open and no action | Can repeat in later digests |
| Skipped | Suppressed |
| Applied | Suppressed |
| Same delivery run ID already recorded | Suppressed for that run |
| Email sent, sending or uncertain | Blocked from automatic resend |
| Enquiry pending and currently unavailable | Can be paused and later reopened when rediscovered |

The current local Apps Script file includes stable posting identities for common Greenhouse host variants, Lever/Ashby URL variants and Wellfound IDs, plus tracking-parameter normalization. Old callback hashes remain resolvable against saved original URLs.

Cross-platform copies with unrelated URLs can still evade equivalence matching. The Apps Script copy must be deployed through Manage deployments for web requests to use it. The repository alone cannot prove which script version is live in the Google account.

## 11. Telegram webhook and Gmail approval

The bot uses the existing Apps Script web app with a secret-bearing telegram_hook query parameter. The installer registers the webhook with Telegram and removes the former five-minute polling triggers after successful setup. Registration includes a preflight request.

Only the configured private chat/user can perform hosted actions. A webhook update is acknowledged promptly, then processed with locks and update-ID deduplication. A fallback function can restore polling.

Application cards show role, company, location, match score, source label where configured, and application URL, with Skip and Mark Applied. Applying on YC/Wellfound/ATS sites remains a user action. Mark Applied records the action in the platform.

Enquiry cards show recipient, subject, body, hiring-contact source URL and resume filename, with Edit, Approve & Send and Skip.

Edit prompts request the subject on the first line and body below it. The reply is validated, saved and shown as a fresh version. Approval validates the current draft, recipient history and resume fingerprint. Stale draft/resume versions are rejected.

The resume is a personal PDF in Google Drive, referenced by RESUME_FILE_ID. It must be a PDF no larger than 10 MB. MailApp attaches its blob when sending. The hosted sender uses the Google account that owns/runs the script.

Delivery is recorded as sending before the mail request, then sent or uncertain. Uncertain delivery requires checking Gmail Sent before attempting another send. This avoids blind retries after ambiguous delivery.

## 12. Oracle VM scheduler and runtime

Live units inspected on 19 November 2026:

- Ubuntu 24.04 on an x86_64 Oracle VM.
- Working directory /home/ubuntu/Outreach/startup-outreach-agent.
- Persistent SQLite storage on the VM.
- A Python virtual environment at .venv.
- outreach-digest.service runs as ubuntu with Type=oneshot and TimeoutStartSec=20min.
- The service executes .venv/bin/python run.py --hosted-daily.
- outreach-digest.timer has 09:15 and 18:15 Asia/Kolkata calendar entries with AccuracySec=1s.
- These correspond to 03:45 and 12:45 UTC.
- The timer has no Persistent=true setting, so runs missed while the VM is off are not automatically caught up.
- No retry policy or failure-notification unit is defined in the inspected service.

Closing SSH, the browser or the laptop leaves the cloud VM running. The VM must remain available at scheduled times.

The scheduled morning run on 19 November started at 09:15 IST and finished around 09:21 with zero cards. After the verified lead expansion, a manual service run finished at 10:25 IST and confirmed two delivered cards.

The VM Git HEAD was c6cbb69 at inspection, with three deployed modified files containing the lead/diagnostic changes also committed on GitHub as f965871. Deployment currently involves updating files explicitly. A push from the laptop does not automatically update the VM checkout or its virtual environment.

## 13. GitHub and alternative scheduler state

GitHub Actions remains in the repository as a manual/alternative execution path. It includes multiple morning/evening cron entries and a workflow_dispatch entry. The OUTREACH_HOSTED_ENABLED repository variable controls whether its job runs.

Late GitHub cron events now use the active IST delivery window rather than the original event's intended slot. Scheduled requests use a common date/window delivery ID. Manual dispatch can also select enquiry-only or validation-only execution.

DigestScheduler.gs provides an Apps Script time-trigger alternative that dispatches the GitHub workflow using a repository-scoped GitHub token. It records accepted dispatches once per slot. It depends on GitHub execution after request acceptance.

The VM is the intended primary scheduler. GitHub variable values and whether the optional Apps Script dispatcher trigger was removed were not independently verified for this document. Keeping multiple schedulers enabled can lead to extra delivery attempts, especially since the current VM service does not set OUTREACH_DELIVERY_SLOT.

## 14. Configuration and secrets

| Location | Important settings |
| --- | --- |
| config/sources.yaml | Enabled/disabled adapter registry |
| config/company_sizes.yaml | Employer domain, size, evidence, optional ATS/careers URL |
| config/hiring_contacts.yaml | Reviewed published hiring contacts |
| config/candidate_profile.yaml | Candidate facts, projects, preferences |
| VM .env | OUTREACH_WEB_APP_URL, OUTREACH_SYNC_SECRET, GEMINI_API_KEY |
| Apps Script properties | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, RESUME_FILE_ID, OUTREACH_SHEET_ID, OUTREACH_SYNC_SECRET, OUTREACH_WEB_APP_URL |
| Optional dispatcher property | OUTREACH_GITHUB_TOKEN |
| GitHub Actions settings | Hosted URL, sync secret and Gemini secret; OUTREACH_HOSTED_ENABLED variable |

The deployed hosted path uses Google MailApp and the Drive resume. Local SMTP commands use separate Gmail credentials and a local resume path. These are parallel entry points with different storage/attachment handling.

Secret values must stay out of Markdown, Git commits and shared screenshots. Changes to the sync secret must be applied to both sender and receiver.

## 15. Operating commands

Run these inside the VM's project directory:

```bash
# See the next automatic run
systemctl list-timers --all outreach-digest.timer

# Inspect the exact installed service and timer
systemctl cat outreach-digest.service outreach-digest.timer

# Inspect recent delivery and errors
sudo journalctl -u outreach-digest.service -n 80 --no-pager

# Explicitly send a live test digest
sudo systemctl start outreach-digest.service

# Review a shortlist without sending Telegram cards
.venv/bin/python run.py --digest-preview

# Apply database migrations after an appropriate code update
.venv/bin/python -m alembic upgrade head
```

For a code/source update, synchronize the intended committed files to the VM, install any changed dependencies, apply migrations, and verify the affected path. Updating config or Python discovery does not require an Apps Script redeployment. Changing Code.gs does require deploying a new web app version for its HTTP endpoint.

## 16. Known gaps and limits relevant to daily volume

1. A successful run can deliver zero cards. No completion heartbeat is currently sent when that happens.
2. Source listings can be duplicated, stale, senior, international or already handled. Raw counts are larger than the usable shortlist.
3. Unknown-size companies are excluded. Researching and adding evidence can unlock listings already present in SQLite.
4. Junior/fresher full-time discovery is broader than actual Telegram routing because graduate roles currently receive Potentially Eligible.
5. Research coverage is bounded. Startups Gallery inspects ten profiles and enquiry research examines twenty eligible employers per call.
6. Published hiring contacts are sparse and require current website evidence. Some employers offer only forms.
7. The cold-enquiry pipeline has produced zero drafts in recent verified runs.
8. Website selector changes and rate limits can cause partial source results. The HTTP helper retries some network and transient-status failures, while the discovery pipeline isolates source failures.
9. The SQLite freshness policy does not uniformly expire jobs missing from new fetches.
10. Country/visa interpretation and graduation-year matching are incomplete across all adapters.
11. There is no deployed automatic updater, independent service monitor, automatic retry chain or zero-card alert on the Oracle service.
12. Feed data and public pages can be used without subscription costs, while Gemini/Google/Oracle usage remains subject to the actual accounts' free allowances and availability.
13. Human approval is required for sending each enquiry. Application form submission remains manual.
14. The profile does not currently contain a general company-name blacklist such as Canva. The employee-count gate is the principal mechanism excluding large employers.

## 17. Implementation map

All paths below are relative to the repository root.

| Area | Main files |
| --- | --- |
| CLI and orchestration | startup-outreach-agent/src/startup_agent/main.py |
| Discovery orchestration and ATS expansion | startup-outreach-agent/src/startup_agent/discovery/pipeline.py |
| Source adapters | startup-outreach-agent/src/startup_agent/discovery/ |
| Size gate | startup-outreach-agent/src/startup_agent/matching/startup_filter.py |
| Classification and eligibility | startup-outreach-agent/src/startup_agent/matching/classifier.py and eligibility.py |
| Ranking and scoring | startup-outreach-agent/src/startup_agent/matching/ranker.py and scorer.py |
| Profile and preferences | startup-outreach-agent/config/candidate_profile.yaml |
| Persistence and upserts | startup-outreach-agent/src/startup_agent/database/ |
| Job routes and card text | startup-outreach-agent/src/startup_agent/routing.py and digest.py |
| Gemini drafting | startup-outreach-agent/src/startup_agent/email_drafts.py |
| Hosted careers research and delivery | startup-outreach-agent/src/startup_agent/hosted_delivery.py |
| Telegram webhook, history and MailApp | startup-outreach-agent/hosting/apps-script/Code.gs |
| Optional GitHub dispatch timer | startup-outreach-agent/hosting/apps-script/DigestScheduler.gs |
| GitHub workflow | .github/workflows/outreach-daily.yml |
| Original planning material | plan/ |

The original plan captures earlier intentions. The implementation and the inspected deployment determine the behaviour described in this snapshot.
