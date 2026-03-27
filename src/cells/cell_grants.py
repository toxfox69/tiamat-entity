#!/usr/bin/env python3
"""
CELL-GRANTS: Federal grant opportunity scanner.
Scans for grants matching ENERGENAI's NAICS codes.
Reports high-scoring opportunities to TIAMAT.
"""

import json
import os
import requests
from datetime import datetime, timezone

# Add parent to path for base_cell import
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_cell import HoneycombCell

CELL_CONFIG = {
    "name": "CELL-GRANTS",
    "tier": 0,
    "cycle_interval_seconds": 21600,  # 6 hours
    "sandbox_paths": ["/root/.automaton/cells/grants/"],
    "forbidden_actions": ["send_email", "modify_code", "access_wallet", "kill_process"],
    "inbox_tag": "[CELL-GRANTS]",
    "training_data_dir": "/root/.automaton/training_data/cell_grants",
    "cell_dir": "/root/.automaton/cells/grants",
}

# ENERGENAI target areas
NAICS_CODES = ["541715", "541519"]
SEARCH_QUERIES = [
    "federal grant AI autonomous agent cybersecurity 2026",
    "SBIR STTR artificial intelligence privacy IoT",
    "DARPA BAA autonomous systems AI agent",
    "DOE ARPA-E AI energy grid wireless power",
    "NSF grant AI agent infrastructure security",
    "DHS SBIR cybersecurity IoT privacy",
    "NIH SBIR AI healthcare PII HIPAA",
]

SEEN_PATH = "/root/.automaton/cells/grants/seen.json"
FINDINGS_PATH = "/root/.automaton/cells/grants/findings.jsonl"
GRANT_MAP_PATH = "/root/.automaton/GRANT_MAP.md"


def load_seen():
    if os.path.exists(SEEN_PATH):
        with open(SEEN_PATH) as f:
            return json.load(f)
    return {"ids": [], "urls": []}


def save_seen(seen):
    with open(SEEN_PATH, "w") as f:
        json.dump(seen, f, indent=2)


class GrantsCell(HoneycombCell):
    def __init__(self):
        super().__init__(CELL_CONFIG)
        self.groq_key = os.environ.get("GROQ_API_KEY", "")
        self.perplexity_key = os.environ.get("PERPLEXITY_API_KEY", "")

    def execute(self):
        tool_calls = []
        findings = []
        seen = load_seen()

        # 1. Read grant map for context
        grant_context = ""
        if os.path.exists(GRANT_MAP_PATH):
            with open(GRANT_MAP_PATH) as f:
                grant_context = f.read()[:2000]
            tool_calls.append({"tool": "read_file", "args": {"path": GRANT_MAP_PATH}, "result": f"Read {len(grant_context)} chars"})

        # 2. Search for opportunities
        query = SEARCH_QUERIES[self.cycle_count % len(SEARCH_QUERIES)]
        self._log(f"Searching: {query}")

        search_results = self._search(query)
        tool_calls.append({"tool": "search", "args": {"query": query}, "result": f"{len(search_results)} results"})

        if not search_results:
            return {"label": "failure", "evidence": "Search returned no results", "tool_calls": tool_calls}

        # 3. Evaluate each result
        for result in search_results[:5]:
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            url = result.get("url", "")

            if url in seen.get("urls", []):
                continue

            score = self._score_opportunity(title, snippet, grant_context)

            finding = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "title": title,
                "url": url,
                "snippet": snippet[:300],
                "relevance_score": score,
                "search_query": query,
            }
            findings.append(finding)

            # Save finding
            with open(FINDINGS_PATH, "a") as f:
                f.write(json.dumps(finding) + "\n")

            # Track seen
            seen["urls"].append(url)
            seen["urls"] = seen["urls"][-500:]  # keep last 500

            tool_calls.append({"tool": "evaluate", "args": {"title": title[:60]}, "result": f"score={score}"})

            # Report high-scoring opportunities to queen
            if score >= 7:
                self.report_to_queen(
                    f"HIGH-VALUE GRANT ({score}/10): {title}\n{url}\n{snippet[:200]}",
                    priority="high"
                )

        save_seen(seen)

        if not findings:
            return {"label": "partial", "evidence": "All results already seen", "tool_calls": tool_calls}

        high_scores = [f for f in findings if f["relevance_score"] >= 7]
        if high_scores:
            return {"label": "success", "evidence": f"Found {len(high_scores)} high-value opportunities", "tool_calls": tool_calls}

        return {"label": "partial", "evidence": f"Found {len(findings)} opportunities, none scored 7+", "tool_calls": tool_calls}

    def _search(self, query):
        """Search using Perplexity Sonar, fall back to Groq on any failure."""
        if self.perplexity_key:
            results = self._search_perplexity(query)
            if results:
                return results
            self._log("Perplexity returned empty, falling back to Groq")
        return self._search_groq(query)

    def _search_perplexity(self, query):
        try:
            res = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {self.perplexity_key}", "Content-Type": "application/json"},
                json={
                    "model": "sonar",
                    "messages": [{"role": "user", "content": f"Find current federal grant opportunities for: {query}. List each with title, URL, deadline, and brief description. Focus on opportunities open in 2026."}],
                    "max_tokens": 1000,
                },
                timeout=30,
            )
            if res.status_code == 200:
                content = res.json()["choices"][0]["message"]["content"]
                # Parse into structured results
                return self._parse_search_results(content)
        except Exception as e:
            self._log(f"Perplexity error: {e}")
        return []

    def _search_groq(self, query):
        if not self.groq_key:
            return []
        try:
            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.groq_key}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": f"What are the current federal grant opportunities for AI, cybersecurity, and IoT companies with NAICS codes 541715 and 541519? Search query: {query}"}],
                    "max_tokens": 500,
                },
                timeout=30,
            )
            if res.status_code == 200:
                content = res.json()["choices"][0]["message"]["content"]
                return self._parse_search_results(content)
        except Exception as e:
            self._log(f"Groq error: {e}")
        return []

    def _parse_search_results(self, text):
        """Parse LLM response into structured results."""
        results = []
        lines = text.split("\n")
        current = {}
        for line in lines:
            line = line.strip()
            if not line:
                if current.get("title"):
                    results.append(current)
                    current = {}
                continue
            if line.startswith("http"):
                current["url"] = line
            elif not current.get("title") and len(line) > 10:
                current["title"] = line.lstrip("0123456789.-) ")
                current["snippet"] = line
            else:
                current["snippet"] = current.get("snippet", "") + " " + line
        if current.get("title"):
            results.append(current)
        return results

    def _score_opportunity(self, title, snippet, grant_context):
        """Score 0-10 based on relevance to ENERGENAI."""
        text = (title + " " + snippet).lower()
        score = 0

        # Direct NAICS match
        if "541715" in text or "541519" in text:
            score += 3

        # Tech area matches
        keywords = {
            "ai": 1, "artificial intelligence": 1, "autonomous": 2,
            "cybersecurity": 1, "privacy": 1, "iot": 2, "wireless": 1,
            "agent": 2, "sbir": 1, "sttr": 1, "small business": 1,
            "hipaa": 2, "pii": 2, "healthcare": 1, "edge": 1,
            "darpa": 1, "dod": 1, "dhs": 1, "nist": 1,
        }
        for keyword, weight in keywords.items():
            if keyword in text:
                score += weight

        return min(10, score)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv("/root/.env")

    cell = GrantsCell()
    cell.run_forever()
