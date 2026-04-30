#!/usr/bin/env python3
"""scrub — pipe text through PHI scrubber from the shell or CI.

Usage:
    echo "Patient SSN 555-12-3456" | scrub
    scrub --file notes.txt
    scrub --file notes.txt --audit audit.json
    cat *.log | scrub --check  # exit 1 if PHI found (CI gate)

Examples (CI gate to fail PR if PHI lands in logs):
    git diff origin/main | scrub --check || (echo "PHI in diff!"; exit 1)
"""
import argparse, json, sys
from pathlib import Path

def main():
    p = argparse.ArgumentParser(description="Scrub PHI from text. HIPAA Safe Harbor.")
    p.add_argument("--file", "-f", help="Read from file instead of stdin")
    p.add_argument("--audit", "-a", help="Write audit JSON to this path")
    p.add_argument("--check", action="store_true",
                   help="Exit 1 if any PHI found (no output). For CI gates.")
    p.add_argument("--local", action="store_true",
                   help="Force local regex (no API call). Faster, less precise.")
    p.add_argument("--api-url", help="Override API endpoint")
    args = p.parse_args()

    text = Path(args.file).read_text() if args.file else sys.stdin.read()
    if not text.strip():
        sys.stderr.write("scrub: no input\n"); sys.exit(2)

    from energenai_scrubber import Scrubber
    s = Scrubber(api_url=args.api_url) if args.api_url else Scrubber()
    if args.local:
        r = s._scrub_local(text)
    else:
        try:
            r = s.scrub(text)
        except Exception as e:
            sys.stderr.write(f"scrub: API failed ({e}), falling back to local\n")
            r = s._scrub_local(text)

    if args.check:
        if r.identifiers_removed > 0:
            sys.stderr.write(f"FOUND {r.identifiers_removed} PHI identifier(s):\n")
            for a in r.audit:
                sys.stderr.write(f"  {a.identifier_type:12} × {a.count}  {a.severity}\n")
            sys.exit(1)
        sys.exit(0)

    sys.stdout.write(r.scrubbed_text)
    if not r.scrubbed_text.endswith("\n"):
        sys.stdout.write("\n")

    if args.audit:
        Path(args.audit).write_text(json.dumps({
            "identifiers_removed": r.identifiers_removed,
            "safe_harbor_compliant": r.safe_harbor_compliant,
            "audit": [{"type": a.identifier_type, "count": a.count,
                       "severity": a.severity} for a in r.audit],
        }, indent=2))

if __name__ == "__main__":
    main()
