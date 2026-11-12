# Hosted Gmail self-test

This pilot uses a Google Apps Script time trigger to process a Telegram approval and email a PDF from Drive to the Google account running the script. The trigger checks Telegram every five minutes.

1. Use your existing outreach bot. If the local listener is running, let it finish handling any recent taps, then stop it with **Ctrl+C**. If you have pending actions, run `python run.py --telegram-poll` first and wait for their confirmations. During the hosted test, use only the new **Gmail self-test** card. Apps Script consumes updates for the bot during this time and only acts on that test card.
2. Upload your personal resume PDF to Google Drive under your sending Gmail account. Keep its sharing set to **Restricted**. Copy the file ID between `/d/` and the next slash in its Drive link.
3. In [Google Apps Script](https://script.google.com/), create a new project under that Gmail account. Replace the editor contents with [Code.gs](Code.gs) and save.
4. Open **Project Settings → Script Properties** and add:

   | Property | Value |
   | --- | --- |
   | `TELEGRAM_BOT_TOKEN` | Your existing outreach bot token from the local `.env` |
   | `TELEGRAM_CHAT_ID` | Your existing private Telegram chat ID from the local `.env` |
   | `RESUME_FILE_ID` | The ID of your private PDF in Drive |

5. In the editor, select and run `sendHostedTestCard`. When Google prompts for authorization, choose the Gmail account that owns the resume and review the requested permissions.
6. Select and run `installHostedTestTrigger` once. Then open Telegram and tap **Approve & Send Test**. Allow roughly five minutes for the trigger to run. Check Gmail for the test email and open the attachment to verify it.
7. After the test, open **Triggers** in Apps Script and delete the `pollHostedTest` trigger. Once its current execution has finished, you can restart the local listener.

The test sends one email to the Google account running the script. The card identifies the recipient and attachment. Repeat taps reuse the saved result. If delivery is uncertain, check Gmail Sent before clearing the `HOSTED_TEST` property to try again.

If a step fails, open **Executions** in Apps Script to see whether the trigger ran and what error was reported.
