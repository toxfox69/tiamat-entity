#!/usr/bin/env python3
"""GitHub PR Status Batch Monitor CLI

Monitors multiple GitHub PR statuses efficiently.
Usage: python pr_monitor.py example.json
"""

import json
import sys
import time
import csv
from pathlib import Path
from typing import List, Dict, Optional

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not found. Install with: pip install requests")
    sys.exit(1)


class PRMonitor:
    """GitHub PR status batch monitor."""
    
    def __init__(self, rate_limit_per_min: int = 10):
        self.base_url = "https://api.github.com"
        self.rate_limit = rate_limit_per_min
        self.min_delay = 60 / rate_limit_per_min
        self.session = requests.Session()
        self.results = []
    
    def fetch_pr(self, repo: str, pr_number: int) -> Optional[Dict]:
        """Fetch a single PR's status from GitHub API."""
        url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}"
        
        try:
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 404:
                return {
                    'repo': repo,
                    'pr': pr_number,
                    'error': 'PR not found (404)'
                }
            elif response.status_code == 403:
                return {
                    'repo': repo,
                    'pr': pr_number,
                    'error': 'Rate limited or forbidden (403)'
                }
            elif response.status_code != 200:
                return {
                    'repo': repo,
                    'pr': pr_number,
                    'error': f'HTTP {response.status_code}'
                }
            
            data = response.json()
            return {
                'repo': repo,
                'pr': pr_number,
                'state': data.get('state', 'unknown'),
                'merged': data.get('merged', False),
                'mergeable': data.get('mergeable', 'unknown'),
                'reviews': data.get('review_comments', 0),
                'updated_at': data.get('updated_at', 'unknown'),
                'title': data.get('title', ''),
                'error': None
            }
        
        except requests.exceptions.Timeout:
            return {
                'repo': repo,
                'pr': pr_number,
                'error': 'Request timeout'
            }
        except requests.exceptions.RequestException as e:
            return {
                'repo': repo,
                'pr': pr_number,
                'error': f'Network error: {str(e)[:50]}'
            }
    
    def monitor_batch(self, prs: List[Dict[str, any]]) -> List[Dict]:
        """Monitor a batch of PRs with rate limiting."""
        self.results = []
        
        for i, pr_spec in enumerate(prs):
            repo = pr_spec.get('repo')
            pr_num = pr_spec.get('pr')
            
            if not repo or not pr_num:
                print(f"⚠ Invalid PR spec: {pr_spec}")
                continue
            
            # Rate limiting
            if i > 0:
                time.sleep(self.min_delay)
            
            print(f"📊 Fetching {repo}#{pr_num}...", end=' ')
            result = self.fetch_pr(repo, pr_num)
            self.results.append(result)
            
            if result.get('error'):
                print(f"❌ {result['error']}")
            else:
                state = result.get('state', '?')
                merged = '✓' if result.get('merged') else '○'
                print(f"{merged} {state.upper()}")
        
        return self.results
    
    def print_table(self):
        """Print results as formatted table."""
        if not self.results:
            print("No results to display.")
            return
        
        print("\n" + "="*100)
        print(f"{'REPO':<25} {'PR':<8} {'STATE':<10} {'MERGED':<8} {'MERGEABLE':<10} {'REVIEWS':<8} {'TITLE':<30}")
        print("="*100)
        
        for result in self.results:
            if result.get('error'):
                print(f"{result['repo']:<25} {result['pr']:<8} ERROR: {result['error']}")
            else:
                repo = result['repo'][:24]
                pr = str(result['pr'])[:7]
                state = result['state'][:9]
                merged = 'YES' if result['merged'] else 'NO'
                mergeable = 'YES' if result['mergeable'] == True else ('NO' if result['mergeable'] == False else '?')
                reviews = str(result['reviews'])[:7]
                title = result['title'][:29]
                
                print(f"{repo:<25} {pr:<8} {state:<10} {merged:<8} {mergeable:<10} {reviews:<8} {title:<30}")
        
        print("="*100 + "\n")
    
    def save_csv(self, filename: str = "pr_results.csv"):
        """Save results to CSV file."""
        if not self.results:
            print(f"No results to save to {filename}")
            return
        
        try:
            with open(filename, 'w', newline='') as f:
                fieldnames = ['repo', 'pr', 'state', 'merged', 'mergeable', 'reviews', 'updated_at', 'title', 'error']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for result in self.results:
                    # Ensure all keys exist
                    row = {k: result.get(k, '') for k in fieldnames}
                    writer.writerow(row)
            
            print(f"✅ Results saved to {filename}")
        except IOError as e:
            print(f"❌ Failed to save CSV: {e}")


def load_pr_list(json_file: str) -> List[Dict]:
    """Load PR list from JSON file."""
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and 'prs' in data:
            return data['prs']
        else:
            print(f"ERROR: JSON must contain list or dict with 'prs' key")
            return []
    except FileNotFoundError:
        print(f"ERROR: File not found: {json_file}")
        return []
    except json.JSONDecodeError:
        print(f"ERROR: Invalid JSON in {json_file}")
        return []


def main():
    if len(sys.argv) < 2:
        print("Usage: python pr_monitor.py <json_file> [output.csv]")
        print("\nExample JSON:")
        print('[{"repo": "llvm/torch-mlir", "pr": 4862}, {"repo": "openpango/openpango-skills", "pr": 186}]')
        sys.exit(1)
    
    json_file = sys.argv[1]
    csv_file = sys.argv[2] if len(sys.argv) > 2 else "pr_results.csv"
    
    prs = load_pr_list(json_file)
    if not prs:
        sys.exit(1)
    
    monitor = PRMonitor(rate_limit_per_min=10)
    monitor.monitor_batch(prs)
    monitor.print_table()
    monitor.save_csv(csv_file)


if __name__ == "__main__":
    main()
