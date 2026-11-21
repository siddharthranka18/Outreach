// Offline Apps Script contract tests. No real credentials or network calls.
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const properties = new Map([['OUTREACH_SYNC_SECRET', 'fixture-only-secret-0000000000000000000000']]);
const calls = [];
let rows = [];
const sheet = {getRange: () => ({setValue() {}})};
const context = {
  PropertiesService: {getScriptProperties: () => ({getProperty: key => properties.get(key),
    setProperty: (key, value) => properties.set(key, value)})},
  Utilities: {computeHmacSha256Signature: (payload, secret) => Array.from(crypto.createHmac('sha256', secret).update(payload).digest())},
  SpreadsheetApp: {flush() {}},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('hosting/apps-script/Code.gs', 'utf8'), context);
context.settings = () => ({chatId: 'fixture-chat'});
context.hostedHistory = () => ({sheet, rows});
context.telegram = (config, method, payload) => calls.push(payload);
function envelope(batch) {
  const payload = JSON.stringify(batch);
  return {postData: {contents: JSON.stringify({payload, signature: crypto.createHmac('sha256', properties.get('OUTREACH_SYNC_SECRET')).update(payload).digest('hex')})}};
}
const batch = {timestamp: Math.floor(Date.now()/1000), run_id: 'local-123', cards: [], summary: 'source: 1 / 0 / 0'};
assert.equal(context.verifiedShortlist(envelope(batch)).summary, batch.summary);
assert.throws(() => context.verifiedShortlist(envelope({...batch, timestamp: batch.timestamp - 3600})), /timestamp/);
assert.throws(() => context.verifiedShortlist(envelope({...batch, summary: 'x'.repeat(3501)})), /summary/);
const bad = envelope(batch);
const parsed = JSON.parse(bad.postData.contents);
parsed.payload = parsed.payload.replace('source', 'tampered');
bad.postData.contents = JSON.stringify(parsed);
assert.throws(() => context.verifiedShortlist(bad), /signature/);
assert.equal(context.publishHostedCards(batch), 0);
assert.equal(context.publishHostedCards(batch), 0);
assert.equal(calls.length, 1);
context.publishHostedCards({...batch, run_id: 'local-124'});
context.publishHostedCards(batch);
assert.equal(calls.length, 2);
rows = [['','https://studio.example/job','open','','','local-125']];
context.publishHostedCards({...batch, run_id: 'local-125'});
assert.equal(calls.length, 2);
const oldUrl = 'https://old.example/software-intern';
const newUrl = 'https://new.example/software-intern';
const canonical = '123456789012345678901234';
const newCard = {job_url: newUrl, text: 'Software Intern', canonical_job_key: canonical};
rows = [['', oldUrl, 'applied', '', '', 'local-125']];
assert.equal(context.publishHostedCards({...batch, run_id: 'local-126', summary: undefined,
  cards: [{...newCard, alias_urls: [oldUrl]}]}), 0);
rows[0][6] = canonical;
assert.equal(context.publishHostedCards({...batch, run_id: 'local-126', summary: undefined, cards: [newCard]}), 0);
assert.equal(calls.length, 2);
console.log('Apps Script heartbeat, replay suppression, HMAC and timestamp tests passed.');
