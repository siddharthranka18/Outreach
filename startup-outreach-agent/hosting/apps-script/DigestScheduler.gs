// Install from the Apps Script editor after setting OUTREACH_GITHUB_TOKEN.
function installDigestScheduler() {
  if (!PropertiesService.getScriptProperties().getProperty('OUTREACH_GITHUB_TOKEN')) {
    throw new Error('Set OUTREACH_GITHUB_TOKEN in Script properties first.');
  }
  if (!ScriptApp.getProjectTriggers().some(trigger => trigger.getHandlerFunction() === 'dispatchScheduledDigest')) {
    ScriptApp.newTrigger('dispatchScheduledDigest').timeBased().everyMinutes(5).create();
  }
}

function dispatchScheduledDigest() {
  const now = new Date();
  const time = Utilities.formatDate(now, 'Asia/Kolkata', 'HHmm');
  const slot = time >= '0915' && time <= '1100' ? '0915'
    : time >= '1815' && time <= '2000' ? '1815' : '';
  if (!slot) return;
  const day = Utilities.formatDate(now, 'Asia/Kolkata', 'yyyyMMdd');
  const properties = PropertiesService.getScriptProperties();
  const lock = LockService.getUserLock();
  if (!lock.tryLock(1000)) return;
  try {
    const deliveryId = day + slot;
    if (properties.getProperty('OUTREACH_LAST_DISPATCH_SLOT') === deliveryId) return;
    const token = properties.getProperty('OUTREACH_GITHUB_TOKEN');
    if (!token) throw new Error('Missing OUTREACH_GITHUB_TOKEN.');
    const response = UrlFetchApp.fetch(
      'https://api.github.com/repos/siddharthranka18/Outreach/actions/workflows/outreach-daily.yml/dispatches',
      {
        method: 'post',
        contentType: 'application/json',
        headers: {Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json'},
        payload: JSON.stringify({ref: 'main', inputs: {scheduled_dispatch: true}}),
        muteHttpExceptions: true,
      },
    );
    const status = response.getResponseCode();
    if (status !== 204 && status !== 200) throw new Error('Digest dispatch failed with HTTP ' + status);
    properties.setProperty('OUTREACH_LAST_DISPATCH_SLOT', deliveryId);
    console.log('GitHub accepted digest dispatch for ' + deliveryId);
  } finally {
    lock.releaseLock();
  }
}
