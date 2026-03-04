#!/usr/bin/env python3
"""GitHub Repository Intelligence Module"""
import requests
from datetime import datetime, timedelta
import json

class GitHubIntel:
    """Query GitHub API for repository metadata and activity metrics"""
    
    def __init__(self, token=None):
        self.token = token
        self.headers = {}
        if token:
            self.headers["Authorization"] = f"token {token}"
        self.headers["Accept"] = "application/vnd.github.v3+json"
    
    def get_repo_intel(self, owner, repo):
        """Get comprehensive intelligence on a GitHub repository"""
        try:
            # 1. Fetch repo metadata
            repo_url = f"https://api.github.com/repos/{owner}/{repo}"
            resp = requests.get(repo_url, headers=self.headers, timeout=8)
            
            if resp.status_code == 404:
                return {"error": "Repository not found", "status": 404}
            if resp.status_code != 200:
                return {"error": f"API error: {resp.status_code}", "status": resp.status_code}
            
            repo_data = resp.json()
            
            # 2. Get commits in last 30 days
            since = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
            commits_url = f"https://api.github.com/repos/{owner}/{repo}/commits"
            commit_resp = requests.get(
                commits_url,
                headers=self.headers,
                params={"since": since, "per_page": 100},
                timeout=8
            )
            commits_30d = 0
            if commit_resp.status_code == 200:
                commits_30d = len(commit_resp.json())
            
            # 3. Get contributors count
            contributors_url = f"https://api.github.com/repos/{owner}/{repo}/contributors"
            contrib_resp = requests.get(
                contributors_url,
                headers=self.headers,
                params={"per_page": 1},
                timeout=8
            )
            contributors = 0
            if contrib_resp.status_code == 200 and contrib_resp.headers.get('Link'):
                # Parse last page number from Link header
                link = contrib_resp.headers.get('Link', '')
                if 'last' in link:
                    import re
                    match = re.search(r'page=(\d+)>; rel="last"', link)
                    contributors = int(match.group(1)) if match else len(contrib_resp.json())
            
            # 4. Calculate activity score
            velocity = commits_30d / 30.0
            activity_score = min(5.0, round(velocity / 5.0, 2)) if velocity > 0 else 0.0
            
            # Build response
            return {
                "owner": owner,
                "repo": repo,
                "stars": repo_data.get("stargazers_count", 0),
                "forks": repo_data.get("forks_count", 0),
                "open_issues": repo_data.get("open_issues_count", 0),
                "commits_last_30_days": commits_30d,
                "velocity_commits_per_day": round(velocity, 2),
                "activity_score": activity_score,
                "contributors": contributors,
                "primary_language": repo_data.get("language", "Unknown"),
                "created_at": repo_data.get("created_at"),
                "pushed_at": repo_data.get("pushed_at"),
                "description": repo_data.get("description", ""),
                "url": repo_data.get("html_url"),
                "status": 200
            }
        
        except requests.exceptions.Timeout:
            return {"error": "GitHub API timeout", "status": 504}
        except Exception as e:
            return {"error": str(e), "status": 500}


def parse_github_url(url):
    """Extract owner/repo from GitHub URL"""
    # Handle: github.com/owner/repo, https://github.com/owner/repo, etc.
    url = url.replace('https://', '').replace('http://', '').rstrip('/')
    if 'github.com/' not in url:
        return None, None
    parts = url.split('github.com/')[-1].split('/')
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None
