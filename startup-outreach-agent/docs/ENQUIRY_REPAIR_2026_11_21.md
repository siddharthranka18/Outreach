# Repair the November 20 night and November 21 morning enquiries

The Oracle VM was still on `4a3041f` for the morning run. The broader draft update `92a8ef5` has now been pulled onto the VM. The morning run prepared 26 direct application routes and six enquiry cards; Apps Script suppressed the direct routes using its stored-action checks and delivered six enquiries. The regular service runs `--hosted-daily`, not `--hosted-enquiries-only`.

The live enquiry history was read and privately backed up on the VM to `data/processed/pending-enquiry-review.json`. It contained eleven pending role/project-specific drafts, two already-sent employer emails, and one form entry. A prompt change cannot rewrite saved drafts because Apps Script deliberately preserves them.

To repair the eleven pending drafts:

1. In the existing Apps Script project, add a script file named `RefreshSoftwareEnquiries`.
2. Paste the complete contents of `hosting/apps-script/RefreshSoftwareEnquiries.gs` and save.
3. Select `refreshRecentSoftwareEnquiries` in the function menu and click Run. This editor function does not require redeploying the web app.
4. Check the execution log's confirmed count and review the new Telegram cards. Use the new cards' Edit / Approve & Send / Skip buttons.

The repair only targets the eleven verified company URLs. It requires open/paused plus pending status, blocks any recipient already sent/sending/uncertain, backs up original rows in `Enquiry revision backup`, and never calls MailApp. It saves the new wording before sending a card so old approval versions fail validation. A successful repair run will not resend those cards if Run is clicked twice; a failed Telegram delivery can be retried.

The revised email introduces Siddharth as a third-year CSE student, asks about suitable backend/full-stack/AI/software internships, briefly lists verified technologies, and includes the resume note, GitHub and LinkedIn. It names no projects. Existing Code.gs supplies the actual Drive PDF attachment after explicit approval.

For clearer future digest reporting, update the existing `Code.gs` from this repository and redeploy the existing web app as a new version. It adds a delivery breakdown when direct listings were submitted but only enquiries were delivered. It does not restore skipped/applied jobs or invent direct openings to fill a quota.

Apps Script editing could not be completed automatically: Computer Use stopped because it could not establish the current browser URL reliably. No revised cards have been sent until the editor repair function runs successfully.
