export async function sendEmail(config: any, params: {
  to?: string;
  subject: string;
  body: string;
}): Promise<string> {
  const to = params.to || config.creatorEmail;
  const apiKey = config.sendgridApiKey;

  if (!apiKey) throw new Error('No SendGrid API key configured');

  const response = await fetch('https://api.sendgrid.com/v3/mail/send', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      personalizations: [{ to: [{ email: to }] }],
      from: { email: config.emailAddress || 'tiamat.entity.prime@gmail.com', name: 'TIAMAT' },
      subject: params.subject,
      content: [{ type: 'text/plain', value: params.body }],
    }),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`SendGrid error: ${response.status} ${err}`);
  }

  return `Email sent to ${to}: "${params.subject}"`;
}
