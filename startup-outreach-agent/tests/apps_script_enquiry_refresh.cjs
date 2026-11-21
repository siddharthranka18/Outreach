const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const original = {recipient: 'jobs@lab0.ai', subject: 'Full Stack enquiry',
  body: 'My KarigarFlow project', source_url: 'https://lab0.ai/careers'};
const rows = [
  ['', 'https://lab0.ai/#outreach-enquiry', 'paused', 'pending', JSON.stringify(original), '202611201815'],
  ['', 'https://stance.health/#outreach-enquiry', 'open', 'sent', JSON.stringify(original), '202611201815'],
  ['', 'https://revion.inc/#outreach-enquiry', 'skipped', 'pending', JSON.stringify(original), '202611210915'],
];
const backups = [], cards = [];
let backup;
const workbook = {getSheetByName: () => backup, insertSheet: () =>
  (backup = {appendRow: row => backups.push(row)})};
const sheet = {getParent: () => workbook, getRange: (row, col) =>
  ({setValue: value => {rows[row - 2][col - 1] = value;}})};
const context = {console, SpreadsheetApp: {flush() {}},
  Utilities: {sleep() {}}, LockService: {getScriptLock: () => ({waitLock() {}, releaseLock() {}})},
  MailApp: {sendEmail() {throw new Error('Employer mail must never be sent by the repair');}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('hosting/apps-script/Code.gs', 'utf8'), context);
vm.runInContext(fs.readFileSync('hosting/apps-script/RefreshSoftwareEnquiries.gs', 'utf8'), context);
context.settings = () => ({fileId: 'fixture-resume'});
context.hostedHistory = () => ({sheet, rows});
context.resumeAttachment = () => ({hash: 'fixture-hash', blob: {getName: () => 'resume.pdf'}});
context.sendHostedMailCard = (_, url, draft, resume) => cards.push({url, draft, resume});
context.jobKey = text => crypto.createHash('sha256').update(text).digest('hex').slice(0, 24);
const oldVersion = context.mailVersion(original, context.resumeAttachment());
// A sent record for the same recipient protects all pending duplicates.
assert.equal(context.refreshRecentSoftwareEnquiries(), 0);
rows[1][4] = JSON.stringify({...original, recipient: 'jobs@stance.health'});
assert.equal(context.refreshRecentSoftwareEnquiries(), 1);
assert.equal(cards.length, 1);
assert.equal(cards[0].draft.subject, 'Software internship enquiry');
assert.match(cards[0].draft.body, /backend, full-stack, AI-related/);
assert.match(cards[0].draft.body, /Node.js.*FastAPI/);
assert.match(cards[0].draft.body, /github.com\/siddharthranka18/);
assert.match(cards[0].draft.body, /linkedin.com\/in\/siddharth-ranka\//);
assert.match(cards[0].draft.body, /attached my resume/);
assert.doesNotMatch(cards[0].draft.body, /KarigarFlow|project/i);
assert.equal(cards[0].resume.blob.getName(), 'resume.pdf');
assert.equal(rows[0][2], 'open');
assert.equal(backups.length, 2); // header plus original draft
assert.equal(backups[1][5], JSON.stringify(original));
assert.notEqual(context.mailVersion(cards[0].draft, context.resumeAttachment()), oldVersion);
assert.throws(() => context.currentHostedMail({}, context.jobKey(rows[0][1]), oldVersion), /changed/);
assert.equal(context.refreshRecentSoftwareEnquiries(), 0); // no repeated cards
assert.equal(cards.length, 1);
assert.equal(rows[1][3], 'sent');
assert.equal(rows[2][2], 'skipped');
console.log('Pending draft repair, backup, duplicate protection, old approvals and replay tests passed.');
