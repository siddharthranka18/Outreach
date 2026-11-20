# Free-source expansion: validation and deployment

Implemented locally on 20 November 2026. These changes are committed locally; this document does not claim that the VM or Apps Script is already running them.

## Changes

The normal adapter/persistence/ranking/routing path now includes public Consider portfolio searches, HN hiring posts, Remote OK, Jobicy and Working Nomads. Direct ATS detection and board expansion now recognize Workable, Breezy, Teamtailor, BambooHR and optional Personio. New sources/platforms have individual sources.yaml flags. Funding CSV matching is included in hosted daily enquiry research by default. No second timer is needed.

Five employer pages can supply a currently published hiring contact. Research rotates through eligible companies instead of repeatedly examining only the first twenty. HN email hints remain unverified until current employer hiring context supports them, and are redacted from job descriptions to prevent the existing routing inbox parser from accepting them prematurely. Generic hello/contact addresses remain off; the optional setting only permits a complete published 2-20 staff range.

A signed summary supports one Telegram completion heartbeat for a zero-delivery run. All-source discovery failure also attempts a signed failure summary before returning failure. Existing HMAC validation, timestamp checking, Skip/Applied suppression and per-email approval remain.

The candidate profile, classifier, eligibility filter and size filter were not changed. There is no promise of 25-30 eligible attempts per day.

## Verification

The full suite passed: **100 tests**, using `python -m pytest -q`. Tests use saved source fixtures and isolated SQLite databases, never live network access. Node, when installed, runs an offline Apps Script contract test covering signed summaries, modified signatures, stale timestamps and heartbeat replay suppression; this test ran successfully here. No production message or email was sent for this validation.

The actual preview CLI was exercised against saved fixtures with:

```bash
PYTHONIOENCODING=utf-8 python -m pytest -s -q tests/test_new_source_preview.py
```

Funnel from that combined fixture run (synthetic opportunities, not live supply):

| Source | Fetched | Stored normalized | Size known | Size eligible | Role/fresher eligible | Routed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Peak XV | 3 | 1 | 1 | 1 | 0 | 0 |
| Lightspeed | 3 | 0 | 0 | 0 | 0 | 0 |
| Bessemer | 3 | 0 | 0 | 0 | 0 | 0 |
| HN hiring | 3 | 1 | 1 | 1 | 1 | 1 |
| Remote OK | 1 | 1 | 1 | 1 | 0 | 0 |
| Jobicy | 1 | 1 | 1 | 1 | 0 | 0 |
| Working Nomads | 1 | 1 | 1 | 1 | 0 | 0 |
| Workable | 1 | 1 | 1 | 1 | 0 | 0 |
| Breezy | 1 | 1 | 1 | 1 | 0 | 0 |
| Teamtailor | 1 | 1 | 1 | 1 | 0 | 0 |
| BambooHR | 1 | 0 | 0 | 0 | 0 | 0 |

Later copies of the same employer/title/location collapse through existing upserts; this explains the zero stored rows for Lightspeed, Bessemer and BambooHR in this deliberately overlapping fixture set. Six stored internship descriptions are deliberately too short to pass existing eligibility; the short junior full-time specification also remains excluded. HN supplies the one detailed eligible application card. Its post email is not exposed as a verified contact.

Other tests independently cover each ATS parser, optional Personio XML, location restrictions, open-ended/cross-cap/unknown size evidence, unsafe URLs, redirect limits, generic-inbox restrictions and employer-page contact evidence.

## Live protocol checks and unresolved boards

Manual read-only probes were separate from unit tests:

- Peak XV, Lightspeed and Bessemer public pages and their actual Consider UI POST returned successful responses using the page's temporary CSRF token/session cookie. A one-page probe fetched 74, 75 and 65 listings respectively across 25 company groups each, with zero technical early-career listings explicitly located in India after the adapter filter. This is not a full daily discovery or Telegram delivery test.
- Consider's inspected protocol is `POST <board>/api-boards/search-jobs`, with board identity from window.serverInitialData, query.locations, meta.size/sequence and grouped=true. It is public but unofficial. Three pages per board are configured; at most five are allowed by code. Full size bands are retained, and company metadata survives even when none of its jobs qualify.
- Getro pages at https://jobs.accel.com/jobs, https://jobs.generalcatalyst.com/jobs and https://jobs.blume.vc/jobs returned 403. Their boards remain disabled. No keyless public endpoint was verified or invented. Do not enable them until a public search protocol is inspected and implemented; the current adapter refuses Getro.
- https://jobs.nexusvp.com/jobs failed to connect. Its Consider configuration remains disabled until the page and its UI search are verified.
- Workable widget JSON was verified at the Devsinc employer account; duplicate location rows are deduplicated. This employer was used solely to verify the protocol, not added as an eligible target.
- Breezy's JSON feed and a posting page's JobPosting JSON-LD were verified at Talleco. No company-size assumption was made from that probe.
- BambooHR list/detail JSON was verified at flyio. The rich detail fields differ from the sparse list fields. No employer was added from that probe alone.
- Teamtailor's public `jobs.rss` returned valid RSS. [Teamtailor documents this public feed](https://support.teamtailor.com/en/articles/11171756-rss-feed-how-to-guide); its JSON API requires an employer key, so this implementation uses RSS.
- Personio's own XML feed responded successfully, but the platform flag remains off. Verify any intended employer's `https://<board>.jobs.personio.de/xml` before opting in.
- Remote OK, Jobicy, Working Nomads and Algolia HN returned their current public JSON shapes. Remote OK and Jobicy's credit/original-URL requirements are preserved in the cards.

Funding CSV companies with no verified employer domain and size remain research leads. Matching only reviewed names is intentional; a funding announcement does not establish size or an email recipient. Portfolio suggestion export writes a separate YAML file for review and never auto-merges company_sizes.yaml.

## Deployment

1. Publish the six local commits to the intended Git remote, then synchronize that commit to `~/Outreach` on the Oracle VM. Use a fast-forward update and preserve the VM's private .env, SQLite database and runtime files. An update to this laptop alone does not update the VM.
2. In `~/Outreach/startup-outreach-agent`, activate/use the existing environment. There are no new Python dependencies and no schema changes in this update. The normal `.venv/bin/python -m pip install -r requirements.txt` and `.venv/bin/python -m alembic upgrade head` checks are sufficient; no new migration was added. Node is only needed for the optional offline Apps Script test.
3. In the existing Google Apps Script project, replace **Code.gs** with this repository's `hosting/apps-script/Code.gs`. Save, then **Deploy > Manage deployments > Edit (pencil) > Version: New version > Deploy**. Keep the same existing web-app deployment and /exec URL. Editing the editor code without deploying a new version does not update the endpoint.
4. Existing OUTREACH_SYNC_SECRET, Telegram settings, resume ID and Gemini key stay in their existing private locations. No new API key or Script Property is required. Heartbeat state is created automatically. Do not recreate the Telegram webhook or import history merely for this update. DigestScheduler.gs and the systemd timer do not need changes.
5. On the VM, run `.venv/bin/python run.py --digest-preview` to inspect stored inventory without sending cards. It does not fetch new sources by itself; the normal --hosted-daily path runs discovery before publication. The saved-fixture preview above is an offline way to verify every new source without altering the VM database.
6. At the next scheduled run, inspect `sudo journalctl -u outreach-digest.service -n 100 --no-pager` for fetch/funnel counts and the confirmed delivery result. To deliberately send a live run immediately, `sudo systemctl start outreach-digest.service` invokes the existing daily path. This command sends Telegram cards/heartbeat; it was not invoked during these local implementation tests.

No approval is needed to keep the existing gates. A separate HN-only evidence type, generic-inbox opt-in, or broader eligibility would be a user decision; none is enabled here. A zero-card heartbeat only proves that a run reached Apps Script. It cannot detect a stopped VM, missed timer, or an unreachable delivery service; an independent monitor is outside this update.
