# Scheduled discovery and Telegram job review

The existing Apps Script project owns the private Sheet and Telegram bot. GitHub Actions runs discovery, ranks a fresh shortlist, and sends signed job cards to the Apps Script web app. The web app checks the Sheet for skipped or applied jobs before posting.

## Apps Script

1. Stop the local Telegram listener after recent taps are confirmed.
2. Replace the Apps Script editor contents with [Code.gs](Code.gs) and save. Keep the existing Script Properties and imported Sheet.
3. Generate a sync secret in Windows PowerShell with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Add it as `OUTREACH_SYNC_SECRET` under **Project Settings → Script Properties**. Keep the value private.
4. Run `installHostedReviewTrigger` from the editor. Confirm **Triggers** shows `pollHostedReview`. It checks for taps about every five minutes.
5. Select **Deploy → New deployment → Web app**. Choose **Execute as Me** and **Who has access → Anyone** so the GitHub runner can reach it. The endpoint checks a signed request using the sync secret before it reads the Sheet or sends cards. Leave the Sheet and Drive files restricted.
6. Copy the deployed web app URL ending in `/exec`. For later code updates, update the existing deployment to a new version so that URL stays the same.

## GitHub

1. Put the workflow on the repository's default branch. It lives at `.github/workflows/outreach-daily.yml`.
2. In the repository, go to **Settings → Secrets and variables → Actions → Secrets**. Create `OUTREACH_WEB_APP_URL` with the `/exec` URL and `OUTREACH_SYNC_SECRET` with the same secret used in Apps Script.
3. Under **Variables**, create `OUTREACH_HOSTED_ENABLED` with value `true`.
4. Go to **Actions → Outreach daily discovery → Run workflow**. Check the workflow log and Telegram. Use a hosted card to test a Skip or Mark Applied action you want to keep, then wait for the bot confirmation and check the Sheet.

The schedule runs daily at **9:15 AM and 6:15 PM IST**. GitHub can delay scheduled runs. The discovery and delivery step starts only within 30 minutes of its scheduled time. Manual runs can start at any time. A run posts up to 30 cards, with job cards before cold enquiries. Unhandled jobs can reappear on the next run while they match.

Cold enquiries use reviewed entries in `config/hiring_contacts.yaml` with `accepts_enquiries: true`. The daily run checks that the employer still publishes the email, the employer fits the size limit, and there is no matching opening in that run. The bot stores the draft in the private Sheet and shows **Edit**, **Approve & Send**, and **Skip**. Reply to the edit prompt with the subject first and the body below it. **Approve & Send** sends the reviewed draft with the private Drive resume. An existing send or uncertain delivery to the same inbox prevents another cold enquiry.

After replacing the script, update the existing web app deployment to a new version. Keep the existing `pollHostedReview` trigger. Old local job and email buttons require the local listener, so use only new hosted cards while the hosted trigger is active.
