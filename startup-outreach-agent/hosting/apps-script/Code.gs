const SUBJECT = 'Outreach Agent hosted Gmail test';
const BODY = 'This test was approved in Telegram and sent by Google Apps Script. Your resume is attached.';
const TEST_KEY = 'HOSTED_TEST';
const OFFSET_KEY = 'HOSTED_TEST_OFFSET';

function settings() {
  const properties = PropertiesService.getScriptProperties();
  const token = properties.getProperty('TELEGRAM_BOT_TOKEN');
  const chatId = properties.getProperty('TELEGRAM_CHAT_ID');
  const fileId = properties.getProperty('RESUME_FILE_ID');
  if (!/^\d+:[\w-]+$/.test(token || '') || !/^[1-9]\d*$/.test(chatId || '') || !fileId) {
    throw new Error('Set TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, and RESUME_FILE_ID in Script Properties.');
  }
  return {properties, token, chatId, fileId};
}

function telegram(config, method, payload) {
  let response;
  try {
    response = UrlFetchApp.fetch(`https://api.telegram.org/bot${config.token}/${method}`, {
      method: 'post', contentType: 'application/json', payload: JSON.stringify(payload),
      muteHttpExceptions: true,
    });
  } catch (_) {
    throw new Error(`Telegram ${method} could not be reached.`);
  }
  const result = JSON.parse(response.getContentText());
  if (!result.ok) throw new Error(`Telegram ${method} failed (HTTP ${response.getResponseCode()}).`);
  return result.result;
}

function resumeAttachment(fileId) {
  const file = DriveApp.getFileById(fileId);
  if (file.getMimeType() !== 'application/pdf' || file.getSize() > 10 * 1024 * 1024) {
    throw new Error('The Drive file must be a PDF no larger than 10 MB.');
  }
  const blob = file.getBlob().setName(file.getName());
  const hash = Utilities.base64Encode(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, blob.getBytes()));
  return {blob, hash};
}

function sendHostedTestCard() {
  const config = settings();
  const lock = LockService.getScriptLock();
  lock.waitLock(5000);
  try {
    const recipient = Session.getEffectiveUser().getEmail();
    if (!recipient) throw new Error('Could not determine the Google account running the script.');
    const resume = resumeAttachment(config.fileId);
    if (MailApp.getRemainingDailyQuota() < 1) throw new Error('Google mail quota is exhausted.');
    const existing = JSON.parse(config.properties.getProperty(TEST_KEY) || 'null');
    if (existing && existing.status !== 'pending') {
      throw new Error(`The existing test is ${existing.status}. Check Gmail before resetting it.`);
    }
    const test = {
      id: Utilities.getUuid(), recipient, fileId: config.fileId,
      filename: resume.blob.getName(), hash: resume.hash,
      subject: SUBJECT, body: BODY, status: 'pending',
    };
    config.properties.setProperty(TEST_KEY, JSON.stringify(test));
    telegram(config, 'sendMessage', {
      chat_id: config.chatId,
      text: `Gmail self-test\nTo: ${recipient}\nSubject: ${test.subject}\nAttachment: ${test.filename}\n\n${test.body}`,
      reply_markup: {inline_keyboard: [[{
        text: 'Approve & Send Test', callback_data: `hosted-test:${test.id}`,
      }]]},
    });
  } finally {
    lock.releaseLock();
  }
}

function handleTestApproval(config, callback) {
  const chat = callback.message && callback.message.chat;
  if (!chat || chat.type !== 'private' || String(chat.id) !== config.chatId ||
      !callback.from || String(callback.from.id) !== config.chatId) return null;
  const test = JSON.parse(config.properties.getProperty(TEST_KEY) || 'null');
  if (!test || callback.data !== `hosted-test:${test.id}`) return 'This test card is out of date.';
  if (test.status !== 'pending') return `Test status: ${test.status}. Check Gmail.`;
  if (test.recipient !== Session.getEffectiveUser().getEmail()) return 'Google account changed. Open a fresh card.';
  if (MailApp.getRemainingDailyQuota() < 1) return 'Google mail quota is exhausted.';
  const resume = resumeAttachment(test.fileId);
  if (resume.hash !== test.hash || resume.blob.getName() !== test.filename) return 'Resume changed. Open a fresh card.';

  test.status = 'sending';
  config.properties.setProperty(TEST_KEY, JSON.stringify(test));
  try {
    MailApp.sendEmail({to: test.recipient, subject: test.subject, body: test.body, attachments: [resume.blob]});
    test.status = 'sent';
  } catch (_) {
    test.status = 'uncertain';
  }
  config.properties.setProperty(TEST_KEY, JSON.stringify(test));
  return test.status === 'sent' ? 'Gmail accepted the test email.' : 'Delivery uncertain. Check Gmail Sent.';
}

function pollHostedTest() {
  pollTelegram(false);
}

function pollHostedReview() {
  pollTelegram(true);
}

function pollTelegram(reviewEnabled) {
  const config = settings();
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) {
    console.log('Another poll or card creation is already running.');
    return;
  }
  try {
    const updates = telegram(config, 'getUpdates', {
      offset: Number(config.properties.getProperty(OFFSET_KEY) || '0'),
      timeout: 0, allowed_updates: ['message', 'callback_query'],
    });
    console.log(`Telegram returned ${updates.length} update(s), including ${updates.filter(
      update => (update.callback_query?.data || '').startsWith('hosted-test:'),
    ).length} hosted test tap(s).`);
    for (const update of updates) {
      const callback = update.callback_query;
      const data = callback?.data || '';
      if (data.startsWith('hosted-test:') || (reviewEnabled && data.startsWith('hosted-job:'))) {
        let feedback;
        try {
          feedback = data.startsWith('hosted-job:')
            ? handleHostedJobAction(config, callback) : handleTestApproval(config, callback);
        } catch (_) {
          feedback = 'The action could not be completed. Check Apps Script Executions.';
        }
        console.log(feedback || 'Ignored a tap outside the configured private chat.');
        if (feedback) {
          try {
            telegram(config, 'answerCallbackQuery', {callback_query_id: callback.id, text: feedback});
          } catch (_) {
            // The button acknowledgement can expire before the scheduled poll.
          }
          if (String(callback.from.id) === config.chatId) {
            telegram(config, 'sendMessage', {chat_id: config.chatId, text: feedback});
          }
        }
      }
      config.properties.setProperty(OFFSET_KEY, String(update.update_id + 1));
    }
    const test = JSON.parse(config.properties.getProperty(TEST_KEY) || 'null');
    console.log(`Saved test status: ${test?.status || 'no card created'}.`);
  } finally {
    lock.releaseLock();
  }
}

function installHostedTestTrigger() {
  settings();
  if (!ScriptApp.getProjectTriggers().some(trigger => trigger.getHandlerFunction() === 'pollHostedTest')) {
    ScriptApp.newTrigger('pollHostedTest').timeBased().everyMinutes(5).create();
  }
}

function installHostedReviewTrigger() {
  settings();
  hostedHistory();
  for (const trigger of ScriptApp.getProjectTriggers()) {
    if (trigger.getHandlerFunction() === 'pollHostedTest') ScriptApp.deleteTrigger(trigger);
  }
  if (!ScriptApp.getProjectTriggers().some(trigger => trigger.getHandlerFunction() === 'pollHostedReview')) {
    ScriptApp.newTrigger('pollHostedReview').timeBased().everyMinutes(5).create();
  }
}

function hostedHistory() {
  const id = PropertiesService.getScriptProperties().getProperty('OUTREACH_SHEET_ID');
  const sheet = id && SpreadsheetApp.openById(id).getSheetByName('Imported Outreach History');
  if (!sheet) throw new Error('Import your local outreach history before enabling hosted review.');
  const [header, ...rows] = sheet.getDataRange().getValues();
  if (header.slice(0, 5).join('|') !== 'local_job_id|job_url|job_status|gmail_status|draft_json') {
    throw new Error('Unexpected outreach history columns.');
  }
  return {sheet, rows};
}

function hexDigest(bytes) {
  return bytes.map(byte => (byte & 255).toString(16).padStart(2, '0')).join('');
}

function jobKey(url) {
  return hexDigest(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, url)).slice(0, 24);
}

function handleHostedJobAction(config, callback) {
  const chat = callback.message?.chat;
  if (chat?.type !== 'private' || String(chat.id) !== config.chatId ||
      String(callback.from?.id) !== config.chatId) return null;
  const action = /^hosted-job:(skip|applied):([a-f0-9]{24})$/.exec(callback.data);
  if (!action) return 'Invalid job action.';
  const {sheet, rows} = hostedHistory();
  const matches = rows.flatMap((row, index) => row[1] && jobKey(row[1]) === action[2] ? [index] : []);
  if (!matches.length || matches.some(index => ['skipped', 'applied'].includes(rows[index][2]))) {
    return 'Job already handled or unavailable.';
  }
  const status = action[1] === 'skip' ? 'skipped' : 'applied';
  for (const index of matches) sheet.getRange(index + 2, 3).setValue(status);
  SpreadsheetApp.flush();
  return status === 'skipped' ? 'Skipped. This job will stay out of future digests.' :
    'Marked applied. This job will stay out of future digests.';
}

function verifiedShortlist(event) {
  const secret = PropertiesService.getScriptProperties().getProperty('OUTREACH_SYNC_SECRET') || '';
  const raw = event?.postData?.contents || '';
  if (secret.length < 32 || raw.length > 250000) throw new Error('Invalid hosted request.');
  const {payload, signature} = JSON.parse(raw);
  if (typeof payload !== 'string' || !/^[a-f0-9]{64}$/.test(signature || '')) {
    throw new Error('Invalid hosted request.');
  }
  const expected = hexDigest(Utilities.computeHmacSha256Signature(payload, secret));
  let mismatch = 0;
  for (let index = 0; index < expected.length; index++) {
    mismatch |= expected.charCodeAt(index) ^ signature.charCodeAt(index);
  }
  if (mismatch) throw new Error('Invalid hosted request signature.');
  const batch = JSON.parse(payload);
  if (!Number.isSafeInteger(batch.timestamp) || Math.abs(Date.now() / 1000 - batch.timestamp) > 600 ||
      !/^(?:local-)?\d{1,24}$/.test(batch.run_id || '') ||
      !Array.isArray(batch.cards) || batch.cards.length > 100 ||
      batch.cards.some(card => typeof card?.text !== 'string' || !card.text || card.text.length > 4000 ||
        typeof card.job_url !== 'string' || !/^https?:\/\/\S+$/i.test(card.job_url))) {
    throw new Error('Invalid hosted shortlist.');
  }
  return batch;
}

function publishHostedCards(batch) {
  const config = settings();
  const {sheet, rows} = hostedHistory();
  sheet.getRange(1, 6).setValue('last_delivery_run');
  const byUrl = new Map();
  rows.forEach((row, index) => {
    if (!byUrl.has(row[1])) byUrl.set(row[1], []);
    byUrl.get(row[1]).push({values: row, number: index + 2});
  });
  let sent = 0;
  const seen = new Set();
  for (const card of batch.cards) {
    if (seen.has(card.job_url)) continue;
    seen.add(card.job_url);
    const matches = byUrl.get(card.job_url) || [];
    if (matches.some(row => ['skipped', 'applied'].includes(row.values[2]) ||
        String(row.values[5]) === batch.run_id)) continue;
    if (sent >= 30) break;
    let rowNumber = matches[0]?.number;
    if (!rowNumber) {
      sheet.appendRow(['', card.job_url, 'open', '', '', '']);
      rowNumber = sheet.getLastRow();
    }
    if (sent) Utilities.sleep(1100);
    const key = jobKey(card.job_url);
    telegram(config, 'sendMessage', {
      chat_id: config.chatId,
      text: card.text,
      link_preview_options: {is_disabled: true},
      reply_markup: {inline_keyboard: [[
        {text: 'Skip', callback_data: `hosted-job:skip:${key}`},
        {text: 'Mark Applied', callback_data: `hosted-job:applied:${key}`},
      ]]},
    });
    sheet.getRange(rowNumber, 6).setValue(batch.run_id);
    SpreadsheetApp.flush();
    sent++;
  }
  return sent;
}

function doPost(event) {
  let result = {ok: false};
  try {
    const batch = verifiedShortlist(event);
    const lock = LockService.getScriptLock();
    lock.waitLock(30000);
    try {
      result = {ok: true, sent: publishHostedCards(batch)};
    } finally {
      lock.releaseLock();
    }
  } catch (_) {
    console.error('Hosted delivery failed. Check the deployment, sync secret, and Sheet configuration.');
  }
  return ContentService.createTextOutput(JSON.stringify(result)).setMimeType(ContentService.MimeType.JSON);
}

function importOutreachHistory() {
  const properties = PropertiesService.getScriptProperties();
  const sheetId = properties.getProperty('OUTREACH_SHEET_ID');
  const fileId = properties.getProperty('OUTREACH_EXPORT_FILE_ID');
  if (!sheetId || !fileId) throw new Error('Set OUTREACH_SHEET_ID and OUTREACH_EXPORT_FILE_ID in Script Properties.');
  const exported = JSON.parse(DriveApp.getFileById(fileId).getBlob().getDataAsString('UTF-8'));
  if (exported.schema_version !== 1 || !Array.isArray(exported.jobs)) {
    throw new Error('Unsupported outreach export format.');
  }
  const header = ['local_job_id', 'job_url', 'job_status', 'gmail_status', 'draft_json'];
  const rows = exported.jobs.map(job => {
    if (!Number.isSafeInteger(job.local_job_id) || !/^https?:\/\//i.test(job.job_url) ||
        !/^[a-z_]+$/.test(job.job_status)) {
      throw new Error('An export row has an invalid job ID, URL, or status.');
    }
    const gmailStatus = job.draft?.gmail_status || '';
    if (gmailStatus && !/^[a-z_]+$/.test(gmailStatus)) throw new Error('Invalid Gmail delivery status.');
    const draft = job.draft ? JSON.stringify(job.draft) : '';
    if (draft.length > 50000) throw new Error('A saved draft exceeds the Google Sheets cell limit.');
    return [job.local_job_id, job.job_url, job.job_status, gmailStatus, draft];
  });
  if (new Set(rows.map(row => row[0])).size !== rows.length) throw new Error('Duplicate job IDs in export.');
  const lock = LockService.getScriptLock();
  lock.waitLock(5000);
  try {
    const workbook = SpreadsheetApp.openById(sheetId);
    const sheet = workbook.getSheetByName('Imported Outreach History') || workbook.insertSheet('Imported Outreach History');
    const lastRow = sheet.getLastRow();
    if (!lastRow) {
      sheet.getRange(1, 1, 1, header.length).setValues([header]);
    } else if (sheet.getRange(1, 1, 1, header.length).getValues()[0].join('|') !== header.join('|')) {
      throw new Error('The history sheet already has a different layout.');
    }
    const existing = new Set(lastRow > 1
      ? sheet.getRange(2, 1, lastRow - 1, 1).getValues().map(row => Number(row[0]))
      : []);
    const additions = rows.filter(row => !existing.has(row[0]));
    if (additions.length) {
      const firstRow = sheet.getLastRow() + 1;
      const lastRequiredRow = firstRow + additions.length - 1;
      if (lastRequiredRow > sheet.getMaxRows()) {
        sheet.insertRowsAfter(sheet.getMaxRows(), lastRequiredRow - sheet.getMaxRows());
      }
      sheet.getRange(firstRow, 1, additions.length, header.length).setValues(additions);
    }
    SpreadsheetApp.flush();
    console.log(`Imported ${additions.length} records. ${rows.length - additions.length} already existed.`);
  } finally {
    lock.releaseLock();
  }
}
