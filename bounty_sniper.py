#!/usr/bin/env python3
"""
bounty_sniper.py — Filter scored bounties and claim the top one.

Reads /root/.automaton/bounty_radar.json (produced by bounty_radar.py).
Filters, ranks, and optionally claims the highest-scored open bounty.

Usage:
  python bounty_sniper.py list                     # Show top 10 open bounties
  python bounty_sniper.py list --min-score 7       # Only score ≥ 7
  python bounty_sniper.py list --min-value 300     # Only ≥ $300
  python bounty_sniper.py list --lang python        # Language filter
  python bounty_sniper.py claim                    # Claim #1 bounty
  python bounty_sniper.py claim --min-score 6      # Claim top bounty ≥ score 6
  python bounty_sniper.py claim --url <issue_url>  # Claim a specific issue URL
  python bounty_sniper.py scan-and-claim           # Run fresh radar scan then claim top
"""

import argparse
import json
import os
import sys
from pathlib import Path

RADAR_FILE = Path("/root/.automaton/bounty_radar.json")


# ── Load & Filter ────────────────────────────────────────────────────────────

def load_bounties() -> list[dict]:
    if not RADAR_FILE.exists():
        sys.exit(
            f"❌  Radar file not found: {RADAR_FILE}\n"
            "   Run bounty_radar.py first:  python bounty_radar.py"
        )
    with open(RADAR_FILE) as f:
        data = json.load(f)

    scan_time = data.get("scan_time", "unknown")
    all_bounties = data.get("bounties", [])
    print(f"📡  Loaded {len(all_bounties)} bounties (scan: {scan_time})")
    return all_bounties


def filter_bounties(
    bounties: list[dict],
    min_score: float = 5.0,
    min_value: float = 0.0,
    lang: str | None = None,
    platform: str | None = None,
) -> list[dict]:
    results = []
    for b in bounties:
        if b.get("status") != "open":
            continue
        if b.get("score", 0) < min_score:
            continue
        if b.get("value_usd", 0) < min_value:
            continue
        if lang and b.get("language", "").lower() != lang.lower():
            continue
        if platform and b.get("platform", "").lower() != platform.lower():
            continue
        results.append(b)

    # Sort: score desc, then value desc
    results.sort(key=lambda x: (-x.get("score", 0), -x.get("value_usd", 0)))
    return results


# ── Display ──────────────────────────────────────────────────────────────────

def print_bounty_table(bounties: list[dict], limit: int = 10):
    if not bounties:
        print("No bounties match the filters.")
        return

    top = bounties[:limit]
    print(f"\n{'#':<4} {'Score':>5}  {'Value':>7}  {'Time':>6}  {'Lang':<12}  {'Platform':<10}  Title")
    print("─" * 100)
    for i, b in enumerate(top, 1):
        score    = b.get("score", 0)
        value    = b.get("value_usd", 0)
        mins     = b.get("estimate_minutes", 0)
        lang     = b.get("language", "?")[:12]
        platform = b.get("platform", "?")[:10]
        title    = b.get("title", "")[:55]
        print(f"{i:<4} {score:>5.1f}  ${value:>6.0f}  ~{mins:>3}m  {lang:<12}  {platform:<10}  {title}")
        print(f"     {'':5}  {'':7}  {'':6}  {'':12}  {'':10}  {b.get('issue_url', '')}")
        print()


# ── Claim ────────────────────────────────────────────────────────────────────

def claim_bounty(issue_url: str, dry_run: bool = False):
    """Delegate to bounty_hunter.py claim workflow."""
    # Verify bounty_hunter is importable from same directory
    hunter_path = Path(__file__).parent / "bounty_hunter.py"
    if not hunter_path.exists():
        sys.exit(f"❌  bounty_hunter.py not found at {hunter_path}")

    if not os.getenv("GITHUB_TOKEN"):
        sys.exit("❌  Set GITHUB_TOKEN env var first.\n   export GITHUB_TOKEN=ghp_...")

    if dry_run:
        print(f"[dry-run] Would claim: {issue_url}")
        return

    print(f"\n🎯  Claiming: {issue_url}\n")

    # Import and call directly to avoid subprocess overhead
    sys.path.insert(0, str(Path(__file__).parent))
    from bounty_hunter import cmd_claim  # noqa: PLC0415

    args = argparse.Namespace(issue_url=issue_url)
    cmd_claim(args)


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_list(args):
    bounties = load_bounties()
    filtered = filter_bounties(
        bounties,
        min_score=args.min_score,
        min_value=args.min_value,
        lang=args.lang,
        platform=args.platform,
    )
    print(f"✅  {len(filtered)} bounties pass filters (showing top {args.top})\n")
    print_bounty_table(filtered, limit=args.top)


def cmd_claim(args):
    if args.url:
        # Claim a specific URL directly
        claim_bounty(args.url, dry_run=args.dry_run)
        return

    bounties = load_bounties()
    filtered = filter_bounties(
        bounties,
        min_score=args.min_score,
        min_value=args.min_value,
        lang=args.lang,
        platform=args.platform,
    )

    if not filtered:
        print("❌  No bounties match filters. Try lowering --min-score or --min-value.")
        sys.exit(1)

    top = filtered[0]
    print(f"\n🏆  Top bounty selected:")
    print(f"    Title:    {top['title']}")
    print(f"    Score:    {top['score']}")
    print(f"    Value:    ${top['value_usd']:.0f}")
    print(f"    Lang:     {top['language']}")
    print(f"    Est time: ~{top['estimate_minutes']}min")
    print(f"    URL:      {top['issue_url']}")

    if not args.yes and not args.dry_run:
        ans = input("\nClaim this bounty? [y/N] ").strip().lower()
        if ans != "y":
            print("Aborted.")
            sys.exit(0)

    claim_bounty(top["issue_url"], dry_run=args.dry_run)


def cmd_scan_and_claim(args):
    """Run a fresh scan, then claim the top result."""
    print("🔍  Running fresh bounty scan...\n")
    import subprocess
    scanner = Path(__file__).parent / "bounty_radar.py"
    rc = subprocess.run([sys.executable, str(scanner)], check=False).returncode
    if rc != 0:
        print(f"⚠️  Scanner exited with code {rc} — proceeding with existing data")
    cmd_claim(args)


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Filter scored bounties and claim the top one",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Shared filter args
    filter_args = argparse.ArgumentParser(add_help=False)
    filter_args.add_argument("--min-score", type=float, default=5.0,
                             help="Minimum score (default 5.0)")
    filter_args.add_argument("--min-value", type=float, default=0.0,
                             help="Minimum USD value (default 0)")
    filter_args.add_argument("--lang", default=None,
                             help="Filter by language (python, typescript, rust, ...)")
    filter_args.add_argument("--platform", default=None,
                             help="Filter by platform (github, algora, sci, gitcoin)")

    sub = parser.add_subparsers(dest="cmd")

    # list
    p_list = sub.add_parser("list", parents=[filter_args],
                             help="Show top open bounties by score")
    p_list.add_argument("--top", type=int, default=10, help="How many to show (default 10)")

    # claim
    p_claim = sub.add_parser("claim", parents=[filter_args],
                              help="Claim the top-scoring open bounty")
    p_claim.add_argument("--url", default=None,
                         help="Claim a specific issue URL instead of auto-selecting")
    p_claim.add_argument("--yes", "-y", action="store_true",
                         help="Skip confirmation prompt")
    p_claim.add_argument("--dry-run", action="store_true",
                         help="Print what would be claimed without acting")

    # scan-and-claim
    p_sac = sub.add_parser("scan-and-claim", parents=[filter_args],
                            help="Run fresh bounty_radar scan then claim top result")
    p_sac.add_argument("--yes", "-y", action="store_true")
    p_sac.add_argument("--dry-run", action="store_true")
    p_sac.add_argument("--url", default=None)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "list":           cmd_list,
        "claim":          cmd_claim,
        "scan-and-claim": cmd_scan_and_claim,
    }
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
