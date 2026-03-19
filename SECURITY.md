# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability in TIAMAT, **do not open a public issue.**

Email: tiamat@tiamat.live
Subject line: [SECURITY] Brief description

We will acknowledge receipt within 48 hours and provide a fix timeline within 7 days.

## Scope

The following are in scope:
- Authentication/authorization bypasses in the API
- Payment verification bypass (USDC/ETH amount checking)
- Agent safety constraint bypass (ACL, forbidden patterns)
- Prompt injection that causes harmful actions
- Credential exposure in public-facing responses
- Rate limit bypass

The following are out of scope:
- Denial of service (we're a 1-CPU VPS, we know)
- Social engineering attacks on the operator
- Issues in third-party dependencies (report to them directly)
- Cosmetic issues in the frontend

## Responsible Disclosure

- We ask for 90 days before public disclosure
- We will credit you in the fix commit (unless you prefer anonymity)
- We do not offer bug bounties at this time (we have $0 revenue)

## Known Hardening

- All API keys, wallet keys, and credentials are excluded from git via .gitignore and pre-push hooks
- The agent's write access is restricted to specific directories via ACLs
- Shell command injection is blocked via FORBIDDEN_COMMAND_PATTERNS
- Payment verification checks actual USDC/ETH amounts, not just transaction success
- Git history was scrubbed after a credential leak incident (March 2026)
