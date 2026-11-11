# Startup Job Outreach Agent

A Python application that finds small-startup internships and junior roles, ranks them against a candidate profile, and lets you review applications and email drafts from Telegram.

- [startup-outreach-agent/](startup-outreach-agent/) contains the application, configuration, migrations, and tests.
- [plan/](plan/) contains the original [project plan](plan/startup-job-outreach-agent.md) and architecture notes.

## Run locally

From the repository root, open PowerShell and run:

```powershell
cd startup-outreach-agent
python -m pip install -r requirements.txt
python -m alembic upgrade head
python run.py --discover
python run.py --match
python run.py --digest-preview
```

Discovery reads the enabled sources in [sources.yaml](startup-outreach-agent/config/sources.yaml). Matching uses the [candidate profile](startup-outreach-agent/config/candidate_profile.yaml), including the 100-employee ceiling. Reviewed company sizes and hiring addresses live in the application's `config/` directory.

## Telegram and email

Put local credentials in `startup-outreach-agent/.env`. Use `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` for your private Telegram chat. Use `GEMINI_API_KEY` for AI draft generation, and set `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, and `OUTREACH_RESUME_PATH` for employer emails. Point the resume setting to a local PDF using a filesystem path.

| Command | What it does |
| --- | --- |
| `python run.py --telegram-review` | Posts eligible job cards with Skip and Mark Applied. |
| `python run.py --telegram-poll` | Processes Telegram buttons and draft edits while the command is running. |
| `python run.py --email-preview` | Previews one draft from the local template. |
| `python run.py --email-save` | Generates one Gemini draft or reuses the saved version, and prints its job ID. |
| `python run.py --telegram-email-card-preview JOB_ID` | Shows a preview card in Telegram. |
| `python run.py --telegram-email-approve JOB_ID` | Posts a live review card for a saved draft with a published recipient. |

On a live review card, **Edit** opens a reply prompt. Put the subject on the first line and the body below it. **Approve & Send** sends the reviewed email through Gmail with the configured resume PDF.

Run the tests from `startup-outreach-agent/` with `python -m pytest -q`.
