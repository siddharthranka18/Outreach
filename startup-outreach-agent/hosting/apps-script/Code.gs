const SUBJECT = 'Outreach Agent hosted Gmail test';
const BODY = 'This test was approved in Telegram and sent by Google Apps Script. Your resume is attached.';
const TEST_KEY = 'HOSTED_TEST';
const OFFSET_KEY = 'HOSTED_TEST_OFFSET';
const WEBHOOK_KEY = 'OUTREACH_TELEGRAM_WEBHOOK_SECRET';
const WEBHOOK_UPDATE_KEY = 'OUTREACH_TELEGRAM_LAST_UPDATE';
const UPGRADE_READY = 'OUTREACH_UPGRADES_READY_V1';
const FOLLOWUP_POLICY = 'OUTREACH_FOLLOWUP_POLICY_V1';
const UPGRADE_LABELS = {shadow_intern: 'Shadow Intern', micro_audit: 'Micro-Audit', technical_question: 'Tech Question'};
const TRACK = {mode: 8, thread: 9, sentAt: 10, count: 11, state: 12, soft: 13};

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
      handleTelegramUpdate(config, update, reviewEnabled);
      config.properties.setProperty(OFFSET_KEY, String(update.update_id + 1));
    }
    const test = JSON.parse(config.properties.getProperty(TEST_KEY) || 'null');
    console.log(`Saved test status: ${test?.status || 'no card created'}.`);
  } finally {
    lock.releaseLock();
  }
}

function handleTelegramUpdate(config, update, reviewEnabled, acknowledged = false) {
  const callback = update.callback_query;
  const data = callback?.data || '';
  if (data.startsWith('hosted-test:') || (reviewEnabled && /^hosted-(job|mail|bump):/.test(data))) {
    let feedback;
    try {
      if (data.startsWith('hosted-bump:')) {
        feedback = handleFollowupAction(config, callback);
      } else if (data.startsWith('hosted-mail:')) {
        feedback = handleHostedMail(config, callback);
      } else {
        feedback = data.startsWith('hosted-job:')
          ? handleHostedJobAction(config, callback) : handleTestApproval(config, callback);
      }
    } catch (_) {
      feedback = 'The action could not be completed. Check Apps Script Executions.';
    }
    console.log(feedback || 'Ignored a tap outside the configured private chat.');
    if (feedback) {
      try {
        if (!acknowledged) telegram(config, 'answerCallbackQuery', {callback_query_id: callback.id, text: feedback});
      } catch (_) {
        // The button acknowledgement can expire before the scheduled poll.
      }
      if (String(callback.from.id) === config.chatId) {
        telegram(config, 'sendMessage', {chat_id: config.chatId, text: feedback});
      }
    }
  } else if (reviewEnabled && update.message) {
    if (!handleFollowupEdit(config, update.message)) handleHostedMailEdit(config, update.message);
  }
}

function installHostedReviewWebhook() {
  const config = settings();
  hostedHistory();
  const url = config.properties.getProperty('OUTREACH_WEB_APP_URL') || '';
  if (!/^https:\/\/script\.google\.com\/macros\/s\/[\w-]+\/exec$/.test(url)) {
    throw new Error('Set OUTREACH_WEB_APP_URL to the existing web app /exec URL in Script Properties.');
  }
  const secret = config.properties.getProperty(WEBHOOK_KEY) || Utilities.getUuid() + Utilities.getUuid();
  config.properties.setProperty(WEBHOOK_KEY, secret);
  const probe = UrlFetchApp.fetch(`${url}?telegram_probe=1`, {
    method: 'post', followRedirects: false, muteHttpExceptions: true,
  });
  if (probe.getResponseCode() !== 200 || !probe.getContentText().includes('outreach-webhook-ready')) {
    throw new Error(`Webhook preflight failed (HTTP ${probe.getResponseCode()}). Deploy the updated web app version and try again.`);
  }
  telegram(config, 'setWebhook', {
    url: `${url}?telegram_hook=${secret}`, allowed_updates: ['message', 'callback_query'],
    max_connections: 1, drop_pending_updates: false,
  });
  for (const trigger of ScriptApp.getProjectTriggers()) {
    if (['pollHostedTest', 'pollHostedReview'].includes(trigger.getHandlerFunction())) {
      ScriptApp.deleteTrigger(trigger);
    }
  }
  console.log('Telegram webhook registered. Tap Skip on a card to verify delivery.');
}

function restoreHostedReviewPolling() {
  const config = settings();
  telegram(config, 'deleteWebhook', {drop_pending_updates: false});
  installHostedReviewTrigger();
}

function checkHostedReviewWebhook() {
  const info = telegram(settings(), 'getWebhookInfo', {});
  console.log(`Webhook active: ${Boolean(info.url)}. Pending Telegram updates: ${info.pending_update_count}.`);
  if (info.last_error_message) console.log(info.last_error_message.replace(/https?:\/\/\S+/g, '[URL]'));
}

function receiveTelegramWebhook(event) {
  const config = settings();
  const secret = config.properties.getProperty(WEBHOOK_KEY);
  const response = () => HtmlService.createHtmlOutput('OK');
  const raw = event.postData?.contents || '';
  if (!secret || event.parameter?.telegram_hook !== secret || raw.length > 100000) return response();
  const update = JSON.parse(raw);
  if (!Number.isSafeInteger(update?.update_id)) return response();
  const callback = update.callback_query;
  let acknowledged = false;
  if (callback?.message?.chat?.type === 'private' && String(callback.message.chat.id) === config.chatId &&
      String(callback.from?.id) === config.chatId) {
    try {
      telegram(config, 'answerCallbackQuery', {callback_query_id: callback.id, text: 'Received. Saving your action…'});
      acknowledged = true;
    } catch (_) {
      // Continue if Telegram has already expired the acknowledgement.
    }
  }
  const lock = LockService.getScriptLock();
  lock.waitLock(60000);
  try {
    const last = JSON.parse(config.properties.getProperty(WEBHOOK_UPDATE_KEY) || 'null');
    const now = Date.now();
    if (last && now - last.at < 6 * 86400000 && update.update_id <= last.id) return response();
    handleTelegramUpdate(config, update, true, acknowledged);
    config.properties.setProperty(WEBHOOK_UPDATE_KEY, JSON.stringify({id: update.update_id, at: now}));
  } finally {
    lock.releaseLock();
  }
  return response();
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

function hostedJobIdentity(url) {
  const match = /^https?:\/\/([^/?#]+)([^?#]*)(\?[^#]*)?(#.*)?$/i.exec(url || '');
  if (!match) return url;
  const [, authority, rawPath, query = '', fragment = ''] = match;
  const host = authority.toLowerCase().replace(/^www\./, '');
  const path = rawPath.replace(/\/+$/, '');
  if (/^#outreach-enquiry(?:-form)?$/.test(fragment)) return url;
  if (['boards.greenhouse.io', 'job-boards.greenhouse.io'].includes(host)) {
    const id = /^\/[^/]+\/jobs\/(\d+)(?:\/apply)?$/.exec(path)?.[1];
    if (id) return `greenhouse:${id}`;
  }
  if (['jobs.lever.co', 'jobs.eu.lever.co', 'jobs.ashbyhq.com'].includes(host)) {
    const posting = /^\/([^/]+)\/([a-f0-9-]{36})(?:\/apply|\/application)?$/i.exec(path);
    if (posting) return `${host}:${posting[1].toLowerCase()}:${posting[2].toLowerCase()}`;
  }
  if (host === 'wellfound.com') {
    const id = /^\/jobs\/(\d+)(?:-[^/]+)?$/.exec(path)?.[1];
    if (id) return `wellfound:${id}`;
  }
  const params = query.slice(1).split('&').filter(param => param &&
    !/^(?:utm_[^=]+|ref|source|fbclid|gclid|gh_src|lever-source)=/i.test(param)).sort();
  return `${host}${path}${params.length ? '?' + params.join('&') : ''}${fragment}`;
}

function handleHostedJobAction(config, callback) {
  const chat = callback.message?.chat;
  if (chat?.type !== 'private' || String(chat.id) !== config.chatId ||
      String(callback.from?.id) !== config.chatId) return null;
  const action = /^hosted-job:(skip|applied):([a-f0-9]{24})$/.exec(callback.data);
  if (!action) return 'Invalid job action.';
  const {sheet, rows} = hostedHistory();
  const original = rows.find(row => row[1] && jobKey(row[1]) === action[2]);
  if (!original) {
    return 'Job already handled or unavailable.';
  }
  const identity = hostedJobIdentity(original[1]);
  const matches = rows.flatMap((row, index) => hostedJobIdentity(row[1]) === identity ? [index] : []);
  if (matches.some(index => ['skipped', 'applied'].includes(rows[index][2]))) {
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
  if (batch.summary !== undefined && (typeof batch.summary !== 'string' || batch.summary.length > 3500)) {
    throw new Error('Invalid digest summary.');
  }
  if (!Number.isSafeInteger(batch.timestamp) || Math.abs(Date.now() / 1000 - batch.timestamp) > 600) {
    throw new Error('Invalid hosted request timestamp.');
  }
  if (batch.run_id === 'enquiry-history' && Array.isArray(batch.cards) && !batch.cards.length) return batch;
  if (
      !/^(?:local-)?\d{1,24}$/.test(batch.run_id || '') ||
      !Array.isArray(batch.cards) || batch.cards.length > 100 ||
      batch.cards.some(card => typeof card?.text !== 'string' || !card.text || card.text.length > 4000 ||
        typeof card.job_url !== 'string' || !/^https?:\/\/\S+$/i.test(card.job_url) ||
        (card.canonical_job_key !== undefined && (card.draft || !/^[a-f0-9]{24}$/.test(card.canonical_job_key))) ||
        (card.alias_urls !== undefined && (!Array.isArray(card.alias_urls) || card.alias_urls.length > 20 ||
          card.alias_urls.some(url => typeof url !== 'string' || !/^https?:\/\/\S+$/i.test(url)))) ||
        (card.draft && !validHostedDraft(card.draft)))) {
    throw new Error('Invalid hosted shortlist.');
  }
  return batch;
}

function validHostedDraft(draft) {
  return /^[a-z0-9._+%-]+@[a-z0-9.-]+\.[a-z]{2,}$/i.test(draft?.recipient || '') &&
    typeof draft.subject === 'string' && draft.subject.length > 0 && draft.subject.length <= 150 &&
    !/[\r\n]/.test(draft.subject) && typeof draft.body === 'string' &&
    draft.body.trim().length > 0 && draft.body.length <= 3000 &&
    typeof draft.source_url === 'string' && /^https:\/\/\S+$/.test(draft.source_url) &&
    (draft.outreach_mode === undefined || draft.outreach_mode === 'standard_enquiry' ||
      Object.hasOwn(UPGRADE_LABELS, draft.outreach_mode)) &&
    (draft.attach_resume === undefined || typeof draft.attach_resume === 'boolean') &&
    ((draft.attach_resume === false) === isUpgradeDraft(draft));
}

function isUpgradeDraft(draft) {
  return Object.hasOwn(UPGRADE_LABELS, draft?.outreach_mode);
}

function mailVersion(draft, resume) {
  if (draft.attach_resume === false) return jobKey(JSON.stringify([draft, 'no-pdf'])).slice(0, 16);
  return jobKey(JSON.stringify([draft, resume.hash, resume.blob.getName()])).slice(0, 16);
}

function sendHostedMailCard(config, url, draft, resume) {
  const key = jobKey(url);
  const version = mailVersion(draft, resume);
  const headline = isUpgradeDraft(draft) ? `[${UPGRADE_LABELS[draft.outreach_mode]} • No PDF]` : 'Cold internship enquiry';
  const attachment = resume ? `\nAttachment: ${resume.blob.getName()}` : '';
  const technical = /^https:\/\/\S+$/.test(draft.context_signals?.url || '')
    ? `\nTechnical source: ${draft.context_signals.url}` : '';
  telegram(config, 'sendMessage', {
    chat_id: config.chatId,
    text: `${headline}\nTo: ${draft.recipient}\nSubject: ${draft.subject}${attachment}\nHiring contact: ${draft.source_url}${technical}\n\n${draft.body}`,
    link_preview_options: {is_disabled: true},
    reply_markup: {inline_keyboard: [[
      {text: 'Edit', callback_data: `hosted-mail:e:${key}:${version}`},
      {text: 'Approve & Send', callback_data: `hosted-mail:s:${key}:${version}`},
      {text: 'Skip', callback_data: `hosted-job:skip:${key}`},
    ]]},
  });
}

function currentHostedMail(config, key, version) {
  const {sheet, rows} = hostedHistory();
  const index = rows.findIndex(row => row[1] && jobKey(row[1]) === key);
  if (index < 0) throw new Error('This email draft is unavailable.');
  const row = rows[index];
  if (row[2] !== 'open' || row[3] !== 'pending') throw new Error('This draft is no longer pending. Check Gmail Sent.');
  const draft = JSON.parse(row[4]);
  if (!validHostedDraft(draft)) throw new Error('This draft is invalid.');
  if (rows.some(other => ['sent', 'sending', 'uncertain', 'replied'].includes(other[3]) &&
      other[4] && JSON.parse(other[4]).recipient === draft.recipient)) {
    throw new Error('This inbox already has an outreach attempt. Check Gmail Sent.');
  }
  if (isUpgradeDraft(draft) && config.properties.getProperty(UPGRADE_READY) !== '1') {
    throw new Error('Outreach upgrades are disabled.');
  }
  const resume = draft.attach_resume === false ? null : resumeAttachment(config.fileId);
  if (mailVersion(draft, resume) !== version) throw new Error('The draft or resume changed. Use the latest card.');
  return {sheet, number: index + 2, url: row[1], draft, resume};
}

function handleHostedMail(config, callback) {
  const chat = callback.message?.chat;
  if (chat?.type !== 'private' || String(chat.id) !== config.chatId ||
      String(callback.from?.id) !== config.chatId) return null;
  const action = /^hosted-mail:([es]):([a-f0-9]{24}):([a-f0-9]{16})$/.exec(callback.data);
  if (!action) return 'Invalid email action.';
  const [, mode, key, version] = action;
  let pending;
  try {
    pending = currentHostedMail(config, key, version);
  } catch (error) {
    return error.message;
  }
  if (mode === 'e') {
    telegram(config, 'sendMessage', {
      chat_id: config.chatId,
      text: `Edit enquiry ${key}:${version}\nReply with the subject on the first line and the body below it.`,
      reply_markup: {force_reply: true, input_field_placeholder: 'Subject, then body'},
    });
    return 'Reply to the edit prompt.';
  }
  if (MailApp.getRemainingDailyQuota() < 1) return 'Google mail quota is exhausted. Try again later.';
  const status = pending.sheet.getRange(pending.number, 4);
  status.setValue('sending');
  SpreadsheetApp.flush();
  try {
    if (pending.draft.attach_resume === false) {
      const message = GmailApp.createDraft(pending.draft.recipient, pending.draft.subject, pending.draft.body).send();
      ensureTrackingColumns(pending.sheet);
      pending.sheet.getRange(pending.number, TRACK.mode, 1, 6).setValues([[
        pending.draft.outreach_mode, message.getThread().getId(), new Date().toISOString(),
        0, JSON.stringify({anchor: message.getId()}), false,
      ]]);
    } else {
      MailApp.sendEmail({
        to: pending.draft.recipient, subject: pending.draft.subject, body: pending.draft.body,
        attachments: [pending.resume.blob],
      });
    }
  } catch (_) {
    status.setValue('uncertain');
    SpreadsheetApp.flush();
    return 'Delivery uncertain. Check Gmail Sent before retrying.';
  }
  status.setValue('sent');
  SpreadsheetApp.flush();
  return 'Gmail accepted your internship enquiry.';
}

function handleHostedMailEdit(config, message) {
  if (message.chat?.type !== 'private' || String(message.chat.id) !== config.chatId ||
      String(message.from?.id) !== config.chatId || !message.reply_to_message?.from?.is_bot) return;
  const marker = /^Edit enquiry ([a-f0-9]{24}):([a-f0-9]{16})$/.exec(
    (message.reply_to_message.text || '').split('\n')[0],
  );
  if (!marker) return;
  try {
    const pending = currentHostedMail(config, marker[1], marker[2]);
    const [firstLine, ...lines] = (message.text || '').split('\n');
    const updated = {...pending.draft, subject: firstLine.trim(), body: lines.join('\n').trim()};
    if (!validHostedDraft(updated)) throw new Error('Reply with a subject up to 150 characters and a body up to 3,000.');
    pending.sheet.getRange(pending.number, 5).setValue(JSON.stringify(updated));
    SpreadsheetApp.flush();
    sendHostedMailCard(config, pending.url, updated, pending.resume);
  } catch (error) {
    telegram(config, 'sendMessage', {chat_id: config.chatId, text: error.message});
  }
}

function ensureTrackingColumns(sheet) {
  const missing = TRACK.soft - sheet.getMaxColumns();
  if (missing > 0) sheet.insertColumnsAfter(sheet.getMaxColumns(), missing);
  sheet.getRange(1, TRACK.mode, 1, 6).setValues([[
    'outreach_mode', 'gmail_thread_id', 'sent_at_iso', 'followup_count',
    'followup_state_json', 'soft_entry_eligible',
  ]]);
}

function validFollowupPolicy(policy) {
  return Boolean(policy && typeof policy.enabled === 'boolean' && typeof policy.soft_entry === 'boolean' &&
    Number.isInteger(policy.first_days) && policy.first_days >= 1 && policy.first_days <= 365 &&
    Number.isInteger(policy.second_days) && policy.second_days > policy.first_days && policy.second_days <= 366 &&
    Number.isInteger(policy.max_followups) && policy.max_followups >= 0 && policy.max_followups <= 2);
}

function currentFollowupPolicy(config) {
  if (config.properties.getProperty(UPGRADE_READY) !== '1') return null;
  const policy = JSON.parse(config.properties.getProperty(FOLLOWUP_POLICY) || 'null');
  return validFollowupPolicy(policy) && policy.enabled ? policy : null;
}

function installOutreachUpgrades() {
  const config = settings();
  GmailApp.getAliases(); // Request Gmail authorization before advertising support to the VM.
  const {sheet} = hostedHistory();
  ensureTrackingColumns(sheet);
  if (!ScriptApp.getProjectTriggers().some(trigger => trigger.getHandlerFunction() === 'checkAndQueueFollowUps')) {
    ScriptApp.newTrigger('checkAndQueueFollowUps').timeBased()
      .everyDays(1).atHour(11).inTimezone('Asia/Kolkata').create();
  }
  config.properties.setProperty(UPGRADE_READY, '1');
}

function disableOutreachUpgrades() {
  settings().properties.deleteProperty(UPGRADE_READY);
}

function followupState(sheet, number, state) {
  sheet.getRange(number, TRACK.state).setValue(JSON.stringify(state));
  SpreadsheetApp.flush();
}

function inspectFollowupThread(sheet, number, row, state) {
  const thread = state.anchor ? GmailApp.getMessageById(state.anchor)?.getThread()
    : GmailApp.getThreadById(row[TRACK.thread - 1]);
  if (!thread) return null;
  thread.refresh();
  const messages = thread.getMessages().filter(message => !message.isDraft());
  const expected = 1 + Number(row[TRACK.count - 1] || 0);
  if (!messages.length || messages.length < expected || (state.anchor && messages[0].getId() !== state.anchor)) return null;
  if (messages.length > expected) {
    if (messages.slice(expected).some(message => message.getFrom() !== messages[0].getFrom())) {
      sheet.getRange(number, 4).setValue('replied');
    }
    sheet.getRange(number, TRACK.soft).setValue(false);
    followupState(sheet, number, {...state, status: 'stopped'});
    return null;
  }
  return messages[messages.length - 1];
}

function sendFollowupCard(config, row, state, day) {
  const draft = JSON.parse(row[4]);
  const key = jobKey(row[1]);
  const token = jobKey(JSON.stringify([state.number, state.body])).slice(0, 16);
  telegram(config, 'sendMessage', {
    chat_id: config.chatId,
    text: `[Follow-Up #${state.number} • Day ${day}]\nTo: ${draft.recipient}\nThread: ${draft.subject}\n\n${state.body}`,
    link_preview_options: {is_disabled: true},
    reply_markup: {inline_keyboard: [[
      {text: 'Approve & Reply in Thread', callback_data: `hosted-bump:s:${key}:${token}`},
      {text: 'Edit', callback_data: `hosted-bump:e:${key}:${token}`},
      {text: 'Skip', callback_data: `hosted-bump:k:${key}:${token}`},
    ]]},
  });
}

function checkAndQueueFollowUps() {
  const config = settings();
  const policy = currentFollowupPolicy(config);
  if (!policy || !policy.max_followups) return 0;
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) return 0;
  try {
    const {sheet, rows} = hostedHistory();
    let sent = 0, checked = 0;
    const start = Number(config.properties.getProperty('OUTREACH_FOLLOWUP_CURSOR') || 0) % (rows.length || 1);
    let visited = 0;
    for (const row of [...rows.slice(start), ...rows.slice(0, start)]) {
      if (checked >= 30 || sent >= 8) break;
      const number = ((start + visited++) % rows.length) + 2;
      if (row[3] !== 'sent' || !row[TRACK.thread - 1] || !row[TRACK.sentAt - 1] ||
          !['shadow_intern', 'micro_audit'].includes(row[TRACK.mode - 1])) continue;
      try {
        const count = Number(row[TRACK.count - 1] || 0);
        const state = JSON.parse(row[TRACK.state - 1] || '{}');
        if (['sending', 'uncertain', 'stopped'].includes(state.status)) continue;
        const elapsed = (Date.now() - Date.parse(row[TRACK.sentAt - 1])) / 86400000;
        const day = count === 0 ? policy.first_days : policy.second_days;
        if (!Number.isFinite(elapsed) || elapsed < day) continue;
        if (count >= policy.max_followups && (count !== 2 || !policy.soft_entry)) continue;
        checked++;
        if (!inspectFollowupThread(sheet, number, row, state)) continue;
        if (count === 2) {
          sheet.getRange(number, TRACK.soft).setValue(true);
          continue;
        }
        if (state.status === 'pending' || (state.lastSent && Date.now() - Date.parse(state.lastSent) < 2 * 86400000)) continue;
        const body = count === 0
          ? 'Just checking back on my note. Would it be helpful if I took a small test task or wrote a short example for your team?'
          : 'I wanted to check once more in case a small software task would be useful. Happy to share a brief example if the timing works.';
        const pending = {...state, status: 'pending', number: count + 1, body};
        sendFollowupCard(config, row, pending, day);
        followupState(sheet, number, pending);
        sent++;
      } catch (_) {
        console.warn('Could not check one outreach thread.');
      }
    }
    config.properties.setProperty('OUTREACH_FOLLOWUP_CURSOR', String((start + visited) % (rows.length || 1)));
    return sent;
  } finally {
    lock.releaseLock();
  }
}

function currentFollowup(config, key, version) {
  const policy = currentFollowupPolicy(config);
  if (!policy) throw new Error('Threaded follow-ups are disabled.');
  const {sheet, rows} = hostedHistory();
  const index = rows.findIndex(row => row[1] && jobKey(row[1]) === key);
  const row = rows[index];
  if (!row || row[3] !== 'sent' || !row[TRACK.thread - 1]) throw new Error('This thread is no longer pending.');
  const state = JSON.parse(row[TRACK.state - 1] || '{}');
  if (state.status !== 'pending' || state.number !== Number(row[TRACK.count - 1] || 0) + 1 ||
      state.number > policy.max_followups || jobKey(JSON.stringify([state.number, state.body])).slice(0, 16) !== version) {
    throw new Error('This follow-up is no longer current.');
  }
  return {sheet, row, state, number: index + 2, day: state.number === 1 ? policy.first_days : policy.second_days};
}

function handleFollowupAction(config, callback) {
  const chat = callback.message?.chat;
  if (chat?.type !== 'private' || String(chat.id) !== config.chatId ||
      String(callback.from?.id) !== config.chatId) return null;
  const action = /^hosted-bump:([sek]):([a-f0-9]{24}):([a-f0-9]{16})$/.exec(callback.data);
  if (!action) return 'Invalid follow-up action.';
  const [, mode, key, version] = action;
  let current;
  try {
    current = currentFollowup(config, key, version);
  } catch (error) {
    return error.message;
  }
  const {sheet, row, state, number} = current;
  if (mode === 'k') {
    sheet.getRange(number, TRACK.soft).setValue(false);
    followupState(sheet, number, {...state, status: 'stopped'});
    return 'Follow-ups skipped for this thread.';
  }
  if (mode === 'e') {
    telegram(config, 'sendMessage', {
      chat_id: config.chatId,
      text: `Edit follow-up ${key}:${version}\nReply with the updated body.`,
      reply_markup: {force_reply: true, input_field_placeholder: 'Follow-up body'},
    });
    return 'Reply to the edit prompt.';
  }
  const last = inspectFollowupThread(sheet, number, row, state);
  if (!last) return 'The thread changed, so the follow-up was stopped.';
  const recipient = JSON.parse(row[4]).recipient.toLowerCase();
  // Reply-all includes the original recipient of our outbound message. Verify the
  // generated recipients before sending so a self-reply cannot be recorded as a bump.
  const reply = last.createDraftReplyAll(state.body);
  const replyMessage = reply.getMessage();
  const addresses = [replyMessage.getTo(), replyMessage.getCc(), replyMessage.getBcc()]
    .join(',').toLowerCase().match(/[a-z0-9._+%-]+@[a-z0-9.-]+\.[a-z]{2,}/g) || [];
  const sender = last.getFrom().toLowerCase().match(/[a-z0-9._+%-]+@[a-z0-9.-]+\.[a-z]{2,}/g) || [];
  if (!addresses.includes(recipient) || addresses.some(address => address !== recipient && !sender.includes(address)) ||
      !inspectFollowupThread(sheet, number, row, state)) {
    reply.deleteDraft();
    return 'The thread or recipients changed. No follow-up was sent.';
  }
  followupState(sheet, number, {...state, status: 'sending'});
  try {
    reply.send();
    sheet.getRange(number, TRACK.count).setValue(state.number);
    followupState(sheet, number, {anchor: state.anchor, lastSent: new Date().toISOString()});
    return 'Gmail accepted the reply in the original thread.';
  } catch (_) {
    followupState(sheet, number, {...state, status: 'uncertain'});
    return 'Follow-up delivery is uncertain. Check Gmail Sent.';
  }
}

function handleFollowupEdit(config, message) {
  const marker = /^Edit follow-up ([a-f0-9]{24}):([a-f0-9]{16})$/.exec(
    (message.reply_to_message?.text || '').split('\n')[0]);
  if (!marker) return false;
  if (message.chat?.type !== 'private' || String(message.chat.id) !== config.chatId ||
      String(message.from?.id) !== config.chatId || !message.reply_to_message?.from?.is_bot) return true;
  try {
    const {sheet, number, row, state, day} = currentFollowup(config, marker[1], marker[2]);
    const body = (message.text || '').trim();
    if (!body || body.length > 3000) throw new Error('Reply with a body up to 3,000 characters.');
    const updated = {...state, body};
    followupState(sheet, number, updated);
    sendFollowupCard(config, row, updated, day);
  } catch (error) {
    telegram(config, 'sendMessage', {chat_id: config.chatId, text: error.message});
  }
  return true;
}

function publishHostedCards(batch) {
  const config = settings();
  const {sheet, rows} = hostedHistory();
  sheet.getRange(1, 6).setValue('last_delivery_run');
  sheet.getRange(1, 7).setValue('canonical_job_key');
  const byUrl = new Map();
  const byKey = new Map();
  const activeEnquiries = new Set(batch.cards.filter(card => card.draft).map(card => card.job_url));
  const upgradesReady = config.properties?.getProperty(UPGRADE_READY) === '1';
  if (upgradesReady && validFollowupPolicy(batch.outreach_policy)) {
    config.properties.setProperty(FOLLOWUP_POLICY, JSON.stringify(batch.outreach_policy));
  }
  rows.forEach((row, index) => {
    if (/\/#outreach-enquiry(?:-technical)?$/.test(row[1] || '') && row[3] === 'pending' &&
        (row[2] === 'open' || row[2] === 'paused')) {
      const nextStatus = activeEnquiries.has(row[1]) ? 'open' : 'paused';
      if (row[2] !== nextStatus) {
        sheet.getRange(index + 2, 3).setValue(nextStatus);
        row[2] = nextStatus;
      }
    }
    const identity = hostedJobIdentity(row[1]);
    if (!byUrl.has(identity)) byUrl.set(identity, []);
    byUrl.get(identity).push({values: row, number: index + 2});
    if (row[6]) {
      if (!byKey.has(row[6])) byKey.set(row[6], []);
      byKey.get(row[6]).push({values: row, number: index + 2});
    }
  });
  SpreadsheetApp.flush();
  let sent = 0;
  let sentJobs = 0;
  let sentEnquiries = 0;
  let sentUpgrades = 0;
  let resume;
  const seen = new Set();
  for (const card of batch.cards) {
    const upgrade = isUpgradeDraft(card.draft);
    if (upgrade ? (!upgradesReady || sentUpgrades >= 5) : sent - sentUpgrades >= 30) continue;
    const identity = hostedJobIdentity(card.job_url);
    const keyIdentity = card.canonical_job_key && `canonical:${card.canonical_job_key}`;
    if (seen.has(identity) || (keyIdentity && seen.has(keyIdentity))) continue;
    seen.add(identity);
    if (keyIdentity) seen.add(keyIdentity);
    const matches = [...(byUrl.get(identity) || []), ...(byKey.get(card.canonical_job_key) || []),
      ...(card.alias_urls || []).flatMap(url => byUrl.get(hostedJobIdentity(url)) || [])];
    if (matches.some(row => ['skipped', 'applied'].includes(row.values[2]) ||
        String(row.values[5]) === batch.run_id)) continue;
    if (card.draft && (
      matches.some(row => row.values[3] && row.values[3] !== 'pending') ||
      rows.some(row => ['sent', 'sending', 'uncertain', 'replied'].includes(row[3]) &&
        row[4] && JSON.parse(row[4]).recipient === card.draft.recipient)
    )) continue;
    let rowNumber = matches[0]?.number;
    if (!rowNumber) {
      sheet.appendRow(['', card.job_url, 'open', card.draft ? 'pending' : '',
        card.draft ? JSON.stringify(card.draft) : '', '']);
      rowNumber = sheet.getLastRow();
    }
    if (sent) Utilities.sleep(1100);
    if (card.draft) {
      const saved = matches[0]?.values[4] ? JSON.parse(matches[0].values[4]) : null;
      const draft = saved?.recipient === card.draft.recipient ? {...saved, source_url: card.draft.source_url} : card.draft;
      if (!validHostedDraft(draft)) continue;
      if (draft.attach_resume !== false) resume = resume || resumeAttachment(config.fileId);
      if (saved && JSON.stringify(saved) !== JSON.stringify(draft)) {
        sheet.getRange(rowNumber, 5).setValue(JSON.stringify(draft));
        SpreadsheetApp.flush();
      }
      sendHostedMailCard(config, card.job_url, draft, draft.attach_resume === false ? null : resume);
      sheet.getRange(rowNumber, 6).setValue(batch.run_id);
      SpreadsheetApp.flush();
      sent++;
      sentEnquiries++;
      if (upgrade) sentUpgrades++;
      continue;
    }
    const key = jobKey(matches[0]?.values[1] || card.job_url);
    if (card.canonical_job_key) sheet.getRange(rowNumber, 7).setValue(card.canonical_job_key);
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
    sentJobs++;
  }
  if (sentEnquiries && !sentJobs && batch.cards.some(card => !card.draft)) {
    telegram(config, 'sendMessage', {
      chat_id: config.chatId,
      text: `Digest delivery: ${sentJobs} direct application cards, ${sentEnquiries} enquiry review cards.\n` +
        'Direct application listings were included in this run but none passed the saved-action checks for delivery. ' +
        'Your Skip/Applied history remains excluded; enquiries still need your approval before email is sent.',
    });
  }
  if (!sent && batch.summary) {
    const properties = PropertiesService.getScriptProperties();
    const recent = JSON.parse(properties.getProperty('OUTREACH_RECENT_HEARTBEATS') || '[]');
    const alreadyDelivered = rows.some(row => String(row[5]) === batch.run_id);
    if (!alreadyDelivered && !recent.includes(batch.run_id)) {
      telegram(config, 'sendMessage', {
        chat_id: config.chatId,
        text: 'Digest run finished — 0 cards delivered.\n' + batch.summary +
          '\nSaved Skip/Applied and email delivery actions are also checked before sending.',
      });
      properties.setProperty('OUTREACH_RECENT_HEARTBEATS', JSON.stringify([...recent, batch.run_id].slice(-32)));
    }
  }
  return sent;
}

function doPost(event) {
  if (event?.parameter?.telegram_probe === '1') return HtmlService.createHtmlOutput('outreach-webhook-ready');
  if (event?.parameter?.telegram_hook) return receiveTelegramWebhook(event);
  let result = {ok: false};
  try {
    const batch = verifiedShortlist(event);
    const lock = LockService.getScriptLock();
    lock.waitLock(30000);
    try {
      if (batch.run_id === 'enquiry-history') {
        const {rows} = hostedHistory();
        const entries = rows.filter(row => typeof row[1] === 'string' &&
          /\/#outreach-enquiry(?:-form|-technical)?$/.test(row[1])).map(row => ({
          url: row[1], status: row[2], delivery: row[3],
          draft: row[4] ? JSON.parse(row[4]) : null,
          sent_at_iso: row[TRACK.sentAt - 1] || '',
          soft_entry_eligible: row[TRACK.soft - 1] === true,
        }));
        result = {ok: true, entries,
          outreach_upgrades_ready: PropertiesService.getScriptProperties().getProperty(UPGRADE_READY) === '1'};
      } else {
        result = {ok: true, sent: publishHostedCards(batch)};
      }
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
