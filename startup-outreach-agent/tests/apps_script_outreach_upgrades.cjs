const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {console, SpreadsheetApp: {flush() {}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('hosting/apps-script/Code.gs', 'utf8'), context);
context.jobKey = input => crypto.createHash('sha256').update(input).digest('hex').slice(0, 24);
const old = {recipient: 'jobs@studio.example', subject: 'Internship enquiry',
  body: 'My resume is attached.', source_url: 'https://studio.example/careers'};
const upgraded = {...old, body: 'Can I send a short demo?', outreach_mode: 'shadow_intern', attach_resume: false};
assert.equal(context.validHostedDraft(old), true);
assert.equal(context.validHostedDraft({...old, attach_resume: false}), false);
assert.equal(context.validHostedDraft(upgraded), true);
const pdf = {hash: 'example', blob: {getName: () => 'resume.pdf'}};
assert.equal(context.mailVersion(old, pdf),
  context.jobKey(JSON.stringify([old, 'example', 'resume.pdf'])).slice(0, 16));
assert.notEqual(context.mailVersion(upgraded, null), context.mailVersion(old, pdf));
const cards = [];
context.telegram = (_, method, payload) => cards.push(payload);
context.sendHostedMailCard({chatId: '1'}, 'https://studio.example/#outreach-enquiry', upgraded, null);
assert.match(cards[0].text, /Shadow Intern • No PDF/);
assert.doesNotMatch(cards[0].text, /Attachment:/);
const row = ['', 'https://studio.example/#outreach-enquiry', 'open', 'sent', JSON.stringify(upgraded),
  '', '', 'shadow_intern', 'thread-id', '2026-01-01', 0, '', false];
const sheet = {getRange: (_, column) => ({setValue: value => {row[column - 1] = value;}})};
let replies = [];
const firstMessage = {getFrom: () => 'owner@example.com', getId: () => 'anchor', isDraft: () => false};
const thread = {refresh() {}, getMessages: () => [firstMessage, ...replies]};
context.GmailApp = {getMessageById: () => ({getThread: () => thread})};
const state = {anchor: 'anchor', number: 1, status: 'pending', body: 'Quick follow-up.'};
assert.equal(context.inspectFollowupThread(sheet, 2, row, state), firstMessage);
replies = [{getFrom: () => 'jobs@studio.example', isDraft: () => false}];
assert.equal(context.inspectFollowupThread(sheet, 2, row, state), null);
assert.equal(row[3], 'replied');
assert.equal(JSON.parse(row[11]).status, 'stopped');
