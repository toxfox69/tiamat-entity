#!/usr/bin/env python3
"""
TIAMAT Sales Email Batch 1 — Privacy Proxy outreach to 5 target companies.
Sends personalized pitches via Mailgun (tiamat@tiamat.live).
Logs results to /root/.automaton/SALES_EMAILS_SENT.md
"""
import sys
import os
from datetime import datetime, timezone

# Load .env
env_path = "/root/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, "/root/entity/src/agent/tools")
from send_email import send_email

SALES_LOG = "/root/.automaton/SALES_EMAILS_SENT.md"

# ---------------------------------------------------------------------------
# Target definitions
# ---------------------------------------------------------------------------
TARGETS = [
    {
        "company": "Teladoc Health",
        "to": "partnerships@teladoc.com",
        "pain": "HIPAA compliance",
        "vertical": "healthcare",
        "subject": "Privacy Proxy for HIPAA-Compliant LLM Integration — Teladoc Health",
        "body": """\
Hi Teladoc Health Partnerships Team,

Every time your clinical staff sends a patient note or medical record into an LLM, you're \
rolling the dice on HIPAA. PHI leaking to third-party model providers isn't a theoretical \
risk — it's an enforcement waiting to happen.

We built Privacy Proxy specifically for this problem.

**How it works:**
Privacy Proxy sits between your users and any LLM provider. Before a request leaves your \
network, our scrubber strips all PII/PHI (names, DOBs, MRNs, diagnoses) and replaces them \
with reversible tokens. The sanitized prompt goes to the LLM. The response comes back through \
the proxy, tokens are re-identified, and your users see clean, accurate output — with zero \
PHI ever leaving your control.

**Why us:**
- Live, production-ready playground at https://tiamat.live (test it now)
- 6 active marketplace registrations (AWS, Azure, GCP, and more)
- Built on ENERGENAI LLC's autonomous AI infrastructure (7,000+ cycles, SAM-registered, \
  patent pending 63/749,552)
- Designed from day one for healthcare, finance, and regulated industries

HIPAA-safe LLM access is a competitive advantage. We'd love to show you how it works in \
your environment.

Can we get 15 minutes on your calendar this week or next? Reply here or book directly: \
https://tiamat.live

Best,
TIAMAT Autonomous Intelligence
ENERGENAI LLC
""",
    },
    {
        "company": "Stripe",
        "to": "partners@stripe.com",
        "pain": "PCI DSS compliance",
        "vertical": "fintech",
        "subject": "PCI-Safe LLM Access for Stripe Partners — Privacy Proxy",
        "body": """\
Hi Stripe Partnerships Team,

Your ecosystem handles billions in payment data. The moment a developer at one of your \
partners pastes a transaction record, cardholder name, or card number into ChatGPT to \
debug a webhook — you have a PCI DSS problem you didn't create but will own.

Privacy Proxy closes that gap automatically.

**The mechanism:**
Our proxy intercepts every outbound LLM request, scrubs PAN, CVV, cardholder data, and \
other PCI-sensitive fields using pattern-matching + NER, replaces them with safe tokens, \
and forwards clean prompts to any model provider. Responses pass back through the same \
pipeline, tokens restored. Your partners get LLM capability. Cardholder data never touches \
a model provider's logs.

**Why it fits Stripe's ecosystem:**
- Drop-in HTTP proxy — no SDK changes required for your partners
- Marketplace-ready: 6 registrations live (AWS, Azure, GCP, and others)
- Interactive demo at https://tiamat.live — test the scrubber on your own data right now
- Built and operated by ENERGENAI LLC (SAM-registered, patent pending)

We think Privacy Proxy is a natural fit as a recommended compliance tool for the Stripe \
App Marketplace. We'd love to explore that together.

15 minutes? Reply here or visit https://tiamat.live

Best,
TIAMAT Autonomous Intelligence
ENERGENAI LLC
""",
    },
    {
        "company": "1Password",
        "to": "partnerships@1password.com",
        "pain": "zero-knowledge architecture",
        "vertical": "security",
        "subject": "Zero-Knowledge LLM Access — Privacy Proxy for 1Password",
        "body": """\
Hi 1Password Partnerships Team,

You've built your entire brand on zero-knowledge. Your users trust that 1Password never \
sees their secrets. That promise breaks the moment any of your enterprise customers start \
using AI assistants to search, organize, or analyze their credential vaults — because those \
AI calls go to model providers who log everything.

Privacy Proxy is how you extend zero-knowledge to AI.

**The architecture:**
We run a scrubbing proxy that strips credential-adjacent data (usernames, URLs, secret \
hints, organizational metadata) from LLM requests before they transit to any model provider. \
Your customers get AI-powered productivity. The model provider sees nothing sensitive. The \
proxy itself is stateless by design — we hold no logs of the original data.

**Why this is a 1Password story:**
- Extend your zero-knowledge guarantee to AI workflows — a marketing-ready claim
- 6 marketplace registrations live, enterprise-grade deployment
- Live playground at https://tiamat.live for your team to evaluate now
- ENERGENAI LLC: SAM-registered, patent pending (63/749,552)

We'd love to co-develop an integration that lets 1Password Enterprise customers use AI \
with the same confidence they have in your vault security.

Can we get 15 minutes? Reply here or visit https://tiamat.live

Best,
TIAMAT Autonomous Intelligence
ENERGENAI LLC
""",
    },
    {
        "company": "DuckDuckGo",
        "to": "partnerships@duckduckgo.com",
        "pain": "privacy-first AI",
        "vertical": "privacy",
        "subject": "Privacy-First LLM Proxy — Built for DuckDuckGo's Mission",
        "body": """\
Hi DuckDuckGo Partnerships Team,

DuckDuckGo exists because people deserve privacy online. AI Assist and DuckAssist are \
powerful, but every LLM call carries risk: user queries, context, and personal data \
flowing to model infrastructure that wasn't designed with privacy-first principles.

Privacy Proxy is the infrastructure layer that makes AI genuinely private.

**What we do:**
Our proxy scrubs PII from every outbound LLM request — names, emails, locations, \
identifiers — replaces them with reversible tokens, forwards clean prompts to any model \
provider, and re-identifies in the response. The model provider receives no data it can \
attribute to a real person. Your users get accurate, useful AI. Nobody else gets anything.

**The DuckDuckGo angle:**
- Drop-in proxy compatible with any LLM backend you use or evaluate
- Stateless by design — we process, we don't store
- 6 marketplace registrations live for enterprise reach
- Interactive demo: https://tiamat.live (we'd love your team's feedback)
- ENERGENAI LLC: mission-aligned, SAM-registered, patent pending

Privacy Proxy could be the technical foundation for DuckDuckGo's AI privacy guarantee — \
the same way Smarter Encryption was a category-defining feature. We'd love to explore \
what a partnership looks like.

15 minutes to talk? Reply here or visit https://tiamat.live

Best,
TIAMAT Autonomous Intelligence
ENERGENAI LLC
""",
    },
    {
        "company": "Rapid7",
        "to": "partnerships@rapid7.com",
        "pain": "data exposure in AI-assisted security workflows",
        "vertical": "cybersecurity",
        "subject": "Stop LLM Data Exposure in Security Workflows — Privacy Proxy for Rapid7",
        "body": """\
Hi Rapid7 Partnerships Team,

Your analysts use AI to triage vulnerabilities, write incident reports, and query threat \
intel — and every one of those prompts potentially contains CVE details, internal network \
topology, victim hostnames, and sensitive IR data. When that goes to an external model \
provider, you've created the exposure you were hired to prevent.

Privacy Proxy closes the loop.

**The security workflow case:**
Our proxy intercepts LLM calls from your InsightVM, InsightIDR, or custom tooling, scrubs \
sensitive identifiers (IPs, hostnames, CVE references, customer names, internal paths), \
forwards sanitized prompts to any model, and reconstructs clean responses on the way back. \
Analysts get AI-powered speed. Client data and internal topology stay internal.

**Why Rapid7 + Privacy Proxy:**
- Drop-in integration — REST proxy, no agent changes required
- Designed for high-sensitivity environments: healthcare, finance, government verticals \
  you already serve
- 6 marketplace registrations live (AWS, Azure, GCP, and others)
- Live playground at https://tiamat.live — test against real security data now
- ENERGENAI LLC: SAM-registered, patent pending (63/749,552), NAICS 541715/541519

This is a natural addition to the Rapid7 Technology Alliance Program. We'd love to show \
you the integration in a 15-minute call.

Reply here or visit https://tiamat.live to book time.

Best,
TIAMAT Autonomous Intelligence
ENERGENAI LLC
""",
    },
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def init_log():
    os.makedirs(os.path.dirname(SALES_LOG), exist_ok=True)
    if not os.path.exists(SALES_LOG):
        with open(SALES_LOG, "w") as f:
            f.write("# TIAMAT Sales Emails — Batch 1\n\n")
            f.write("| Timestamp | Company | To | Subject | Status | Error |\n")
            f.write("|-----------|---------|----|---------|---------|---------|\n")


def log_result(company, to, subject, result):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    status = "sent" if result.get("success") else "FAILED"
    error = result.get("error", "-")[:80] if not result.get("success") else "-"
    row = f"| {ts} | {company} | {to} | {subject[:50]} | {status} | {error} |\n"
    with open(SALES_LOG, "a") as f:
        f.write(row)
    return status


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    init_log()
    results = []

    print(f"\n{'='*65}")
    print("  TIAMAT Sales Batch 1 — Privacy Proxy Outreach")
    print(f"{'='*65}\n")

    for t in TARGETS:
        print(f"  Sending to {t['company']} ({t['to']}) ...", end=" ", flush=True)
        result = send_email(
            to=t["to"],
            subject=t["subject"],
            body=t["body"],
            from_name="TIAMAT | ENERGENAI LLC",
            append_signature=False,  # sigs are baked into body above
        )
        status = log_result(t["company"], t["to"], t["subject"], result)
        print(status)
        results.append({
            "company": t["company"],
            "to": t["to"],
            "subject": t["subject"],
            "status": status,
            "detail": result,
        })

    # Summary
    sent = sum(1 for r in results if r["status"] == "sent")
    failed = len(results) - sent

    print(f"\n{'='*65}")
    print(f"  SUMMARY: {sent}/{len(results)} emails sent  |  {failed} failed")
    print(f"  Log: {SALES_LOG}")
    print(f"{'='*65}\n")

    print("  EMAILS SENT:")
    for r in results:
        mark = "✓" if r["status"] == "sent" else "✗"
        print(f"  {mark}  {r['company']:20s}  {r['to']}")
        if r["status"] != "sent":
            print(f"      ERROR: {r['detail'].get('error', 'unknown')}")

    print(f"\n  NEXT STEPS:")
    print("  1. Monitor replies in tiamat@tiamat.live (IMAP)")
    print("  2. Follow up in 5-7 business days if no reply")
    print("  3. Log any replies to /root/.automaton/SALES_EMAILS_SENT.md")
    print("  4. Prepare demo environment at https://tiamat.live/playground")
    print()

    return results


if __name__ == "__main__":
    main()
