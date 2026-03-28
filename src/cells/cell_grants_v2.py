#!/usr/bin/env python3
"""
CELL-GRANTS v2: Direct sam.gov API search + LLM fit evaluation.
Search = database query. Evaluation = LLM call. Never use LLM to search.
"""

import json, os, sys, time, requests, hashlib
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_cell import HoneycombCell

CELL_CONFIG = {
    "name": "CELL-GRANTS",
    "tier": 0,
    "cycle_interval_seconds": 3600,  # 1 hour
    "cell_dir": "/root/.automaton/cells/grants",
    "training_data_dir": "/root/.automaton/training_data/cell_grants",
}

SAM_SEARCH_URL = "https://sam.gov/api/prod/sgs/v1/search/"
NAICS_CODES = ["541715", "541519"]
KEYWORDS = [
    "autonomous agent", "artificial intelligence", "AI agent",
    "cybersecurity", "privacy", "wireless power", "energy",
    "machine learning", "IoT security", "PII", "HIPAA",
    "agentic AI", "autonomous systems",
]

ENERGENAI_PROFILE = """ENERGENAI LLC builds autonomous AI agent systems.
Core capabilities: persistent autonomous operation (40K+ cycles), multi-model inference,
privacy-preserving AI, self-monitoring agents, federal registration (UEI: LBZFEH87W746).
NAICS: 541715, 541519. Patent: 63/749,552 (wireless power mesh).
Products: PII scrubber, IoT privacy shield, autonomous agent platform (TIAMAT)."""

SEEN_FILE = os.path.join(CELL_CONFIG["cell_dir"], "seen_solicitations.json")
REPORT_FILE = os.path.join(CELL_CONFIG["cell_dir"], "report.json")
LOG_FILE = os.path.join(CELL_CONFIG["cell_dir"], "cell.log")
FINDINGS_FILE = os.path.join(CELL_CONFIG["cell_dir"], "findings.jsonl")

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [CELL-GRANTS] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except: pass

def load_seen():
    try:
        if os.path.exists(SEEN_FILE):
            return json.load(open(SEEN_FILE))
    except: pass
    return {}

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f)

def search_sam(query, page=0, size=25):
    """Direct sam.gov search — returns real solicitation data."""
    try:
        params = {
            "index": "opp",
            "q": query,
            "page": page,
            "size": size,
            "sort": "-modifiedDate",
            "mode": "search",
            "is_active": "true",
        }
        resp = requests.get(SAM_SEARCH_URL, params=params, timeout=15,
                          headers={"Accept": "application/hal+json", "User-Agent": "ENERGENAI-GrantScanner/1.0"})
        if resp.status_code != 200:
            log(f"SAM API returned {resp.status_code}")
            return []

        data = resp.json()
        results = data.get("_embedded", {}).get("results", [])
        return results
    except Exception as e:
        log(f"SAM API error: {e}")
        return []

def parse_opportunity(opp):
    """Extract key fields from SAM opportunity."""
    title = opp.get("title", "Unknown")
    sol_number = opp.get("solicitationNumber", "")
    opp_type = opp.get("type", {}).get("value", "Unknown")
    posted = (opp.get("publishDate") or "")[:10]
    deadline = (opp.get("responseDate") or "")[:10]
    modified = (opp.get("modifiedDate") or "")[:10]
    is_active = opp.get("isActive", False)

    # Extract agency from org hierarchy
    orgs = opp.get("organizationHierarchy", [])
    agency = orgs[0].get("name", "Unknown") if orgs and orgs[0] else "Unknown"

    # Extract description
    descs = opp.get("descriptions", [])
    description = descs[0].get("content", "")[:500] if descs else ""
    # Strip HTML tags
    import re
    description = re.sub(r"<[^>]+>", " ", description).strip()

    # SAM.gov link
    url = f"https://sam.gov/opp/{sol_number}/view" if sol_number else ""

    return {
        "title": title,
        "solicitation_number": sol_number,
        "type": opp_type,
        "agency": agency,
        "posted": posted,
        "deadline": deadline,
        "modified": modified,
        "active": is_active,
        "description": description[:300],
        "url": url,
    }

def evaluate_fit(opportunity):
    """Score opportunity fit against ENERGENAI profile. Simple keyword matching (no LLM cost)."""
    text = (opportunity["title"] + " " + opportunity["description"]).lower()

    score = 0
    matches = []

    # NAICS match (highest signal)
    for naics in NAICS_CODES:
        if naics in text:
            score += 3
            matches.append(f"NAICS {naics}")

    # Keyword matches
    for kw in KEYWORDS:
        if kw.lower() in text:
            score += 1
            matches.append(kw)

    # Type bonus
    if opportunity["type"] in ("Sources Sought", "RFI", "Presolicitation"):
        score += 1  # Lower barrier to entry

    # Active bonus
    if opportunity["active"]:
        score += 1

    # Deadline check
    if opportunity["deadline"]:
        try:
            dl = datetime.strptime(opportunity["deadline"], "%Y-%m-%d")
            days_left = (dl - datetime.now()).days
            if days_left > 7:
                score += 1  # Still time to respond
            if days_left < 0:
                score -= 5  # Expired
        except: pass

    return min(score, 10), matches

def run_cycle(cycle_num):
    seen = load_seen()
    findings = []
    total_results = 0

    # Rotate through keyword groups
    keyword_groups = [
        "autonomous AI agent systems",
        "cybersecurity privacy artificial intelligence",
        "SBIR STTR AI autonomous",
        "IoT security privacy PII",
        "machine learning agent infrastructure",
        "agentic AI autonomous operations",
    ]
    query = keyword_groups[cycle_num % len(keyword_groups)]

    log(f"Searching sam.gov: '{query}'")
    results = search_sam(query)
    total_results = len(results)
    log(f"Got {total_results} results")

    for opp in results:
        parsed = parse_opportunity(opp)

        # Skip already seen
        opp_hash = hashlib.md5(parsed["solicitation_number"].encode()).hexdigest()[:12]
        if opp_hash in seen:
            continue

        score, matches = evaluate_fit(parsed)

        if score >= 3:  # Worth reporting
            finding = {
                **parsed,
                "score": score,
                "matches": matches,
                "found_at": datetime.now(timezone.utc).isoformat(),
                "cycle": cycle_num,
            }
            findings.append(finding)

            # Log finding
            with open(FINDINGS_FILE, "a") as f:
                f.write(json.dumps(finding) + "\n")

            log(f"MATCH ({score}/10): {parsed['title'][:60]} — {', '.join(matches[:3])}")

        seen[opp_hash] = {"title": parsed["title"][:80], "date": parsed["posted"]}

    save_seen(seen)

    # Write report
    report = {
        "cell": "grants",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "last_cycle": cycle_num,
        "status": "running",
        "summary": f"Cycle {cycle_num}: {total_results} results, {len(findings)} new matches",
        "query": query,
        "findings": findings[-5:],
        "escalations": [f for f in findings if f["score"] >= 7],
    }
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)

    # Training data
    td_file = os.path.join(CELL_CONFIG["training_data_dir"], "training.jsonl")
    os.makedirs(CELL_CONFIG["training_data_dir"], exist_ok=True)
    with open(td_file, "a") as f:
        f.write(json.dumps({
            "input": f"Search: {query}",
            "output": f"Found {total_results} results, {len(findings)} matches (scores: {[fi['score'] for fi in findings]})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }) + "\n")

    return total_results, len(findings)

def main():
    os.makedirs(CELL_CONFIG["cell_dir"], exist_ok=True)
    os.makedirs(CELL_CONFIG["training_data_dir"], exist_ok=True)

    test_mode = "--test" in sys.argv
    log(f"CELL-GRANTS v2 starting (interval: {CELL_CONFIG['cycle_interval_seconds']}s, direct sam.gov API)")

    cycle = 0
    while True:
        cycle += 1
        try:
            total, matches = run_cycle(cycle)
            log(f"Cycle {cycle}: {total} results, {matches} new matches")
        except Exception as e:
            log(f"Cycle {cycle} error: {e}")

        if test_mode:
            break

        time.sleep(CELL_CONFIG["cycle_interval_seconds"])

if __name__ == "__main__":
    main()
