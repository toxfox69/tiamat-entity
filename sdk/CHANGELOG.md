# Changelog

All notable changes to `energenai-scrubber` are documented here.

## [0.2.0] — 2026-04-30

### Fixed
- **Critical:** `API_URL` pointed to `https://tiamat.live/scrub`, which the
  webserver 301-redirects to `https://www.tiamat.live/scrub`. Python's `urllib`
  drops the POST body on a 301, so the hosted scrub fell back to the local
  regex without warning. Every install before this version was running in
  local-only mode whether you wanted it to or not. Fixed by pointing directly
  at `https://www.tiamat.live/api/scrub`.

### Added
- `ScrubbedOpenAI` — drop-in replacement for `openai.OpenAI` that scrubs HIPAA
  Safe Harbor identifiers in `messages[*].content` before the request leaves
  the process. Audit trail attaches to `client.last_audit`.
- `scrub` CLI with `--check` mode for pre-commit / CI gates. Exits non-zero
  when PHI is found in stdin.
- Severity tags (`HIGH` / `MEDIUM` / `LOW`) on every audit record.

### Changed
- Local fallback regex set is now a strict subset of the hosted detector. A
  client with no network access still catches SSN, US phone, email, and
  ISO/US date-of-birth patterns.

### Known limitations
- Text only. No DICOM, no image OCR.
- Names are off by default — too many false positives without context.
- The hosted endpoint is single-region (us-east). Ping us if you need a BAA.

## [0.1.0] — 2026-04-28

Initial release. Do not use; see 0.2.0 fix note above.
