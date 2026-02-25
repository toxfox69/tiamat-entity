#!/usr/bin/env python3
"""
Cooldown task: Search for papers in TIAMAT's Glass Ceiling domains every 5 cycles.
Saves findings to /root/.automaton/hive/knowledge/ for use in social posts.
"""
import json
import os
from datetime import datetime
import subprocess

DOMAINS = {
    "energy_systems": "wireless power mesh energy grid 2026",
    "ai_agents": "AI agents autonomous systems 2026",
    "cybersecurity": "cybersecurity supply chain zero-trust 2026",
    "robotics": "autonomous robots DARPA 2026",
    "bioware": "brain-computer interface BCI 2026",
}

def search_arxiv(domain_key, query):
    """Search ArXiv for papers matching the query."""
    cmd = [
        "curl", "-s", 
        f"http://export.arxiv.org/api/query?search_query=cat:cs.AI+AND+({query})&start=0&max_results=5&sortBy=submittedDate&sortOrder=descending"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout
    except Exception as e:
        print(f"Error searching ArXiv for {domain_key}: {e}")
        return None

def save_findings(domain_key, xml_data):
    """Parse ArXiv XML and save structured findings."""
    # Simple XML extraction for titles and links
    if not xml_data:
        return
    
    lines = xml_data.split('\n')
    papers = []
    current_title = ""
    current_id = ""
    
    for line in lines:
        if '<title>' in line:
            current_title = line.split('<title>')[1].split('</title>')[0].strip()
        if '<id>' in line and 'arxiv' in line:
            current_id = line.split('<id>')[1].split('</id>')[0].strip()
            if current_title and current_id:
                papers.append({"title": current_title, "id": current_id})
    
    if papers:
        timestamp = datetime.now().strftime("%Y-%m-%d")
        filename = f"/root/.automaton/hive/knowledge/{timestamp}-{domain_key}.json"
        os.makedirs("/root/.automaton/hive/knowledge/", exist_ok=True)
        with open(filename, 'w') as f:
            json.dump(papers, f, indent=2)
        print(f"✓ Saved {len(papers)} papers to {filename}")

if __name__ == "__main__":
    for domain_key, query in DOMAINS.items():
        print(f"Searching {domain_key}...")
        xml_data = search_arxiv(domain_key, query)
        save_findings(domain_key, xml_data)
