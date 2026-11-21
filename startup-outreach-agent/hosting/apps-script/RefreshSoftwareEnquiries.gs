// One-time repair requested on 21 November 2026. Add as another Apps Script file
// alongside Code.gs and run refreshRecentSoftwareEnquiries from the editor.
// This only publishes review cards. It never sends an employer email.
function refreshRecentSoftwareEnquiries() {
  const targets = new Map([
    ['lab0.ai', 'Lab0'], ['xpaycheckout.com', 'xPay'],
    ['superkalam.com', 'SuperKalam'], ['apollofirst.xyz', 'Apollo'],
    ['enerjazz.tech', 'Enerjazz'], ['revion.inc', 'Revion'],
    ['ramain.ai', 'RamAIn'], ['legalos.ai', 'LegalOS'],
    ['protectt.ai', 'Protectt.ai'], ['moring.ai', 'Moring AI'],
    ['waybill.to', 'Waybill'],
  ].map(([domain, name]) => [`https://${domain}/#outreach-enquiry`, name]));
  const revision = 'software-enquiry-20261121';
  const config = settings();
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const {sheet, rows} = hostedHistory();
    const workbook = sheet.getParent();
    let backup = workbook.getSheetByName('Enquiry revision backup');
    const blocked = new Set(rows.filter(row => ['sent', 'sending', 'uncertain'].includes(row[3]))
      .map(row => row[4] && JSON.parse(row[4]).recipient.toLowerCase()).filter(Boolean));
    const seen = new Set();
    let resume;
    let sent = 0;
    for (let index = 0; index < rows.length; index++) {
      const row = rows[index];
      const company = targets.get(row[1]);
      if (!company || !['open', 'paused'].includes(row[2]) || row[3] !== 'pending' ||
          !row[4] || row[5] === revision || seen.has(row[1])) continue;
      const old = JSON.parse(row[4]);
      if (!validHostedDraft(old) || blocked.has(old.recipient.toLowerCase())) continue;
      seen.add(row[1]);
      if (!backup) {
        backup = workbook.insertSheet('Enquiry revision backup');
        backup.appendRow(['revision', 'row', 'job_url', 'job_status', 'gmail_status', 'draft_json', 'last_delivery_run']);
      }
      if (old.software_enquiry_revision !== revision) {
        backup.appendRow([revision, index + 2, row[1], row[2], row[3], row[4], String(row[5] || '')]);
      }
      const draft = {...old,
        subject: 'Software internship enquiry',
        body: `Hi ${company} team,\n\nI'm Siddharth Ranka, a third-year B.Tech Computer Science and Engineering student at BML Munjal University. I'm looking for a software internship and am open to backend, full-stack, AI-related or other suitable engineering work.\n\nI have hands-on experience with Python, Node.js, Express.js and FastAPI for backend APIs, React for web development, MySQL and MongoDB, and LLM/RAG tools including LangChain and Qdrant. Would your team have a suitable internship opportunity? I'm based in India and would also be happy to discuss remote work where available.\n\nI've attached my resume for your consideration.\n\nThanks,\nSiddharth Ranka\nGitHub: https://github.com/siddharthranka18\nLinkedIn: https://www.linkedin.com/in/siddharth-ranka/`,
        software_enquiry_revision: revision,
      };
      if (!validHostedDraft(draft)) throw new Error('Invalid revised draft.');
      resume = resume || resumeAttachment(config.fileId);
      // Persist before publishing so old approval buttons fail the version check.
      sheet.getRange(index + 2, 5).setValue(JSON.stringify(draft));
      sheet.getRange(index + 2, 3).setValue('open');
      SpreadsheetApp.flush();
      if (sent) Utilities.sleep(1100);
      sendHostedMailCard(config, row[1], draft, resume);
      sheet.getRange(index + 2, 6).setValue(revision);
      SpreadsheetApp.flush();
      sent++;
    }
    console.log(`Revised ${sent} pending enquiries and sent ${sent} Telegram review cards. No employer emails were sent.`);
    return sent;
  } finally {
    lock.releaseLock();
  }
}
