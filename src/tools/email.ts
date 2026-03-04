const SIGNATURE = `
---
TIAMAT Autonomous Intelligence System
ENERGENAI LLC | UEI: LBZFEH87W746 | SAM: Active
Patent Pending: 63/749,552 (7G Wireless Power Mesh)
https://tiamat.live | tiamat@tiamat.live
`;

const FROM_EMAIL = process.env.TIAMAT_LIVE_EMAIL || 'tiamat@tiamat.live';
const FROM_NAME = 'TIAMAT | ENERGENAI LLC';
const GRANTS_EMAIL = process.env.GRANTS_EMAIL || 'grants@tiamat.live';

export async function sendEmail(config: any, params: {
  to?: string;
  subject: string;
  body: string;
  from_addr?: string;
  from_name?: string;
  cc?: string;
  reply_to?: string;
  append_signature?: boolean;
}): Promise<string> {
  const to = params.to || config.creatorEmail;
  const mailgunKey = process.env.MAILGUN_API_KEY;
  const mailgunDomain = process.env.MAILGUN_DOMAIN || 'tiamat.live';

  if (!mailgunKey) throw new Error('No Mailgun API key configured (MAILGUN_API_KEY)');

  const fromAddr = params.from_addr || FROM_EMAIL;
  const fromName = params.from_name || FROM_NAME;
  const appendSig = params.append_signature !== false;
  const fullBody = appendSig ? params.body + SIGNATURE : params.body;

  // Auto-CC grants inbox for .mil and .gov recipients
  const cc = params.cc || (to.includes('.mil') || to.includes('.gov') ? GRANTS_EMAIL : undefined);

  // Mailgun uses form-encoded params
  const formData = new URLSearchParams();
  formData.append('from', `${fromName} <${fromAddr}>`);
  formData.append('to', to);
  formData.append('subject', params.subject);
  formData.append('text', fullBody);
  if (cc) formData.append('cc', cc);
  if (params.reply_to) formData.append('h:Reply-To', params.reply_to);

  const response = await fetch(`https://api.mailgun.net/v3/${mailgunDomain}/messages`, {
    method: 'POST',
    headers: {
      'Authorization': 'Basic ' + Buffer.from(`api:${mailgunKey}`).toString('base64'),
    },
    body: formData,
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`Mailgun error: ${response.status} ${err}`);
  }

  // Log sent email
  try {
    const { appendFileSync, existsSync, mkdirSync, writeFileSync } = await import('fs');
    const logFile = '/root/.automaton/grants/EMAIL_LOG.md';
    const logDir = '/root/.automaton/grants';
    mkdirSync(logDir, { recursive: true });
    if (!existsSync(logFile)) {
      writeFileSync(logFile, '# TIAMAT Email Log\n\n| Timestamp | To | Subject | CC | Status |\n|-----------|----|---------|----|--------|\n');
    }
    const ts = new Date().toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
    appendFileSync(logFile, `| ${ts} | ${to} | ${params.subject.slice(0, 60)} | ${cc || '-'} | sent |\n`);
  } catch {}

  return `Email sent from ${fromAddr} to ${to}${cc ? ` (CC: ${cc})` : ''}: "${params.subject}"`;
}
