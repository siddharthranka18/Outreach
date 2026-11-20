# Daily digest improvements from the November 20 roadmap

New cold-enquiry drafts now ask broadly about software/CSE internships across backend, full-stack and AI work. Gemini receives the verified skills and education instead of a single inferred role or project. The application adds a general subject, resume attachment note, and the configured GitHub/LinkedIn links below the signature. Direct applications remain role-specific. Existing saved Telegram edits are reused; the new wording applies to newly generated enquiries. Resume attachment and individual Approve & Send remain in the existing Apps Script flow; no Code.gs update is needed.

This implements the missing parts of `further_instructions_to_improve.md`. It preserves the June 2028 student profile, strict fresher classification, two-year experience ceiling, 200-employee application gate, unknown-size exclusion, existing action history and individual email approval. The new document explicitly authorizes the inbox/HN policy changes below; they are not accidental relaxations.

## Implemented

| Requested improvement | Implementation |
| --- | --- |
| Broader small-company inboxes | `allow_generic_small_inboxes: true`; hello/contact/founders/team/apply/internships/engineering only when the entire published employee range is within 2-50. Existing hiring inboxes remain valid under the normal company gate. Named emails still need hiring context except under the explicit HN policy. |
| HN hiring contacts as separate evidence | Current top-level comments in a monthly whoishiring thread can qualify without an employer-page duplicate. The address must match the employer domain and the company size must be known and eligible. A checked timestamp expires after two days and a posting expires after 45 days. Replies, other-domain addresses and arbitrary HN links fail validation. Email text remains redacted from normal job descriptions so the exception stays confined to this path. |
| Larger research/drafting capacity | Eighty eligible employers per run, configurable up to 100; sixty rotating Gallery profiles, configurable up to 100; fifteen new Gemini drafts. Existing edited drafts are reused. A fifteen-minute research request budget prevents uncontrolled growth; the employer cursor advances only for visited employers. |
| Junior roles into internship pitches | An explicit 0-1-year/no-experience junior/fresher/entry-level engineering role at a confirmed <=50-person company can supply context for an internship/part-time enquiry when the existing scorer returns Potentially Eligible. It does not become a direct application card. Overseas restrictions, mandatory advanced degrees, insufficient information and higher experience requirements remain blockers. |
| More employer evidence | Feed adapters use SQLite employer identities/sizes plus YAML; portfolio/YC company seeding is processed before the feeds; slow per-company YC job pages run after the quick feeds with a four-minute request budget so newly learned identities are available in the same run. Himalayas and re-enabled Remotive use stored employer evidence rather than requiring a hand-entered slug. Funding CSV resolution also uses the SQLite reservoir. Reviewed domain-size evidence is backfilled onto old stored companies even when they are not rediscovered in the current run. |
| Persistent ATS harvester | Observed company/job/careers links are saved in `companies.ats_boards`. Future runs poll the retained boards without YAML edits. Company size must pass before a board is tracked/polled. Polling rotates at most eighty known boards per run, with up to forty immediate expansions from discovered jobs. The code does not fabricate 300 board tokens to meet a numerical goal. |
| Freshteam / Personio | Freshteam parses public JobPosting JSON-LD on observed employer boards and up to thirty linked postings. Personio XML is enabled for observed, size-eligible company boards after a protocol check. Existing country/degree/role gates still determine which jobs reach Telegram. |
| More Consider boards | Bain, Courtside, Sequoia US and First Round join Peak XV, Lightspeed and Bessemer. Their public UI searches were verified. Five pages of ten company groups per India/Worldwide query by default, maximum eight pages and two queries. A board gets a two-minute request budget; a later-page error preserves earlier results and is shown as a partial failure. |
| Free community feeds | SimplifyJobs Summer2027 public JSON and We Work Remotely programming RSS. Active/visible listings, explicit India/worldwide eligibility, technical early-career titles and known employer evidence required. Remote alone is not worldwide permission. Missing descriptions need real ATS enrichment; no generated requirements are substituted. |
| Indian public boards | Cutshort uses public job JSON-LD, employer website and exact size labels from its own SSR configuration. Recruitment-on-behalf-of-client records are rejected. Weekday reads the public India-filtered fresher SSR list, employer domains and published sizes; anonymous Partner Network entries are excluded. |
| Funding research | Inc42 and YourStory RSS, recent early-stage technical funding articles, bounded article fetches and observed outbound employer domains. Existing size evidence is reused. Unknown-size companies are stored for research but remain ineligible for outreach. |
| Weekly YC seed | Recent Winter/Summer/Fall 2024-2026 cohorts, including non-hiring companies up to 100 staff in India/Fully Remote cohorts. W24-style labels are translated into the actual YC facet names such as Winter 2024. Pagination is eight pages of 100 per region query, and successful persisted seeds run no more than once per seven days. |
| Freshness | Three successful complete ATS snapshots missing a posting close it; failed or partial polls do not increment absence. Unhandled jobs not re-seen for thirty days also close. An advert that remains live is not closed solely because its publication date is old. Skipped/applied states remain intact. |
| Scheduler hygiene | GitHub cron removed; workflow remains available for explicit manual use. Oracle runs use stable date+0915/1815 slot identities when no explicit delivery-slot override exists. Discovery/research requests have time budgets. The larger workload requires increasing the old twenty-minute systemd timeout. |
| Diagnostics | `source_counts.json` now includes stored, size-known, size-eligible, role-eligible and routed counters after preview/delivery diagnostics, alongside last-fetch counts and failures. These are unique stored inventory counts, not claims of new daily opportunities. |

The existing Apps Script thirty-card limit is unchanged. Python reserves up to fifteen positions for jobs and fifteen for enquiries. **This update does not require another Code.gs deployment.**

## Sources that remain unavailable or optional

| Source | Result / decision |
| --- | --- |
| Nexus | Connection still failed. Configured, disabled. |
| Threshold | Public page exists but its state/search protocol differs from the verified CNAME boards; disabled until the actual request can be verified. |
| Khosla | Public job request returned 403. No bypass. |
| Greylock / a16z | No compatible public Consider search was established. Not represented as working adapters. |
| Peerlist | Public job request returned 403, despite its permissive robots file. Configured, disabled. |
| Cuvette / Unstop | Connection failure / HTTP 403. Disabled entries use the paid-only parser guardrails if a public integration later becomes available. |
| Internshala | Its robots file disallows the job/internship detail paths needed to verify descriptions and employer evidence. No detail crawler was added. |
| Entrackr / CEO Dekho | The proposed feed URLs returned 404. Configured, disabled. |
| Growth List India | No verified free RSS integration. No paid dataset was purchased. |
| Job Opportunities API | Optional adapter implemented, disabled. The official documentation now requires an account key for job/company rows. `JOA_API_KEY` is needed to opt in; the adapter fetches one twenty-record India page and does not walk metered pagination. No key was created or used. |

The optional student-board JSON-LD path requires a positive published stipend, >=80 characters of description, at least two matching profile skills, and rejects unpaid/training/campus-ambassador/commission listings. No blocked student board was enabled just to increase raw counts.

Official protocol references: [JOA key requirement](https://jobopportunitiesapi.org/docs/api/keyless), [JOA authentication](https://jobopportunitiesapi.org/docs/api/authentication), [SimplifyJobs listing schema](https://github.com/SimplifyJobs/Summer2027-Internships/blob/dev/CONTRIBUTING.md), [Teamtailor public RSS](https://support.teamtailor.com/en/articles/11171756-rss-feed-how-to-guide).

## Verification

The local suite passes **127 tests**. The initial VM run passed **122 tests with one Node-dependent test skipped** (that test passed locally); the final evidence-lookup, source-ordering and handled-company budget tests were added afterward. Fixture tests cover each new parser, HN provenance/expiry, expanded inbox boundaries, junior-role pitches, SQLite evidence reuse, persistent boards, missing-poll closure, old-but-live adverts, and the weekly seed query/checkpoint. The Alembic test upgrades an existing database, preserves a company row, and downgrades successfully. Existing tests remain required.

A read-only live probe is available with:

```bash
PYTHONPATH=src .venv/bin/python scripts/probe_daily_sources.py
```

It uses an isolated SQLite database, a small sample of each enabled source and no Telegram/Gemini calls. Its report is written to ignored `data/processed/daily_source_probe.json`. A first sample, before the smaller ten-group Consider page size was introduced, observed:

| Source | Fetched | Stored qualifying-title records | Direct eligible/routed |
| --- | ---: | ---: | ---: |
| SimplifyJobs | 17,632 | 0 | 0 |
| WWR | 25 | 0 | 0 |
| Weekday | 20 | 1 | 0 |
| Cutshort (small detail sample) | 1 | 0 | 0 |
| Inc42 / YourStory | 24 / 20 RSS items | 0 job records (company research only) | 0 |
| Courtside / First Round | 11 / 20 job records | 0 qualifying job records | 0 |
| Other Consider sample requests | Timed out at the probe's ten-second timeout | Failure isolated | 0 |

These results are not a production digest or evidence of 25-30 daily eligible attempts. They expose the continuing scarcity of verified small-company India internships. Larger company seeding, recurring board polling and approved cold-contact research address the reservoir; the target remains a goal, not a guarantee.

## Rollout

1. Back up the production SQLite database while the digest service is inactive.
2. Synchronize the committed code and run `.venv/bin/python -m alembic upgrade head`. Revision `61d8c09ea421` adds `companies.ats_boards` and `jobs.missing_ats_polls`; do not run the new model against the old schema.
3. No new runtime dependency or API key is needed for enabled sources. Existing Gemini and hosted settings remain private and unchanged.
4. Increase `outreach-digest.service` TimeoutStartSec to 45min for the bounded larger workload. Enable `Persistent=true` on the timer so a missed tick can be caught after the machine returns. Preserve 09:15 and 18:15 Asia/Kolkata schedules.
5. Run a stored `--digest-preview` first; this sends nothing. Then the roadmap's explicit live smoke test can invoke the existing service once and inspect the journal. Email drafts still need approval.
6. Confirm VM service exit status, schema version, next timer and source/delivery counters. A completion heartbeat cannot detect a VM that never starts or an unreachable Telegram/Google service; an independent monitor would be separate work.

Historical validation in NEW_SOURCES_VALIDATION.md describes the previous rollout. CURRENT_ARCHITECTURE.md and this document describe the new policy and code.

## Completed live validation

The Oracle smoke run on 20 November completed with exit status 0. Discovery ran from 17:42 UTC, and Telegram confirmed delivery at 18:06 UTC. The weekly seed fetched 102 company records. Consider boards completed with Sequoia 23, First Round 9, Bain 28, Courtside 4, Peak XV 50, Lightspeed 50 and Bessemer 39 company records (overlap is possible; these are not job counts). The run prepared five enquiry drafts and 26 application routes. Apps Script confirmed **five review cards delivered** after its saved-action checks; this does not mean employer emails were sent.

The database was backed up before migration. The VM has schema 61d8c09ea421, a 45-minute service timeout, an active persistent timer and the existing 09:15/18:15 IST schedule. The final follow-up applies reviewed sizes to old stored records, resolves known employers by exact domain when available, moves quick feeds before expensive YC job-page fetches, and excludes handled enquiry companies before web research. These changes require no new schema or Code.gs version. A second live digest is unnecessary to validate this follow-up; offline tests and a stored preview cover it.
