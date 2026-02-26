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
  const apiKey = config.sendgridApiKey || process.env.SENDGRID_API_KEY;

  if (!apiKey) throw new Error('No SendGrid API key configured');

  const fromAddr = params.from_addr || FROM_EMAIL;
  const fromName = params.from_name || FROM_NAME;
  const appendSig = params.append_signature !== false;
  const fullBody = appendSig ? params.body + SIGNATURE : params.body;

  // Auto-CC grants inbox for .mil and .gov recipients
  const cc = params.cc || (to.includes('.mil') || to.includes('.gov') ? GRANTS_EMAIL : undefined);

  const personalizations: any = { to: [{ email: to }] };
  if (cc) personalizations.cc = [{ email: cc }];

  const payload: any = {
    personalizations: [personalizations],
    from: { email: fromAddr, name: fromName },
    subject: params.subject,
    content: [{ type: 'text/plain', value: fullBody }],
  };

  if (params.reply_to) {
    payload.reply_to = { email: params.reply_to };
  }

  const response = await fetch('https://api.sendgrid.com/v3/mail/send', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`SendGrid error: ${response.status} ${err}`);
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
