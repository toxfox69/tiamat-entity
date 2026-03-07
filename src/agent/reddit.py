#!/usr/bin/env python3
"""
TIAMAT Reddit Integration — OAuth2 password grant client.
Post, comment, read, and search Reddit via the API.
"""

import os
import sys
import json
import time
import logging
import requests

log = logging.getLogger("reddit")
if not log.handlers:
    log.setLevel(logging.INFO)
    _fmt = logging.Formatter("%(asctime)s [REDDIT] %(message)s")
    _sh = logging.StreamHandler(sys.stderr)
    _sh.setFormatter(_fmt)
    log.addHandler(_sh)
    log.propagate = False

CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
USERNAME = os.environ.get("REDDIT_USERNAME", "")
PASSWORD = os.environ.get("REDDIT_PASSWORD", "")

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"
USER_AGENT = "python:TIAMAT-Agent:v1.0 (by /u/{})".format(USERNAME or "tiamat")

SUBREDDIT_WHITELIST = [
    "SideProject", "artificial", "MachineLearning", "androiddev",
    "programming", "Python", "opensource", "selfhosted",
    "ArtificialIntelligence", "LLM", "LocalLLaMA", "ChatGPT",
    "singularity", "technology", "webdev", "startups",
    "IndieHackers", "buildinpublic",
]

# Lowercase lookup for case-insensitive matching
_WHITELIST_LOWER = {s.lower(): s for s in SUBREDDIT_WHITELIST}


class RedditClient:
    def __init__(self):
        self._token = None
        self._token_expires = 0
        self.last_post_time = 0
        self.min_post_interval = 300  # 5 min between posts

    def _get_token(self):
        if self._token and self._token_expires > time.time() + 60:  # Refresh 60s early
            log.info("Using existing Reddit token.")
            return self._token

        log.info(f"Attempting to refresh/acquire Reddit token. CLIENT_ID_PRESENT: {bool(CLIENT_ID)}, USERNAME_PRESENT: {bool(USERNAME)}")
        return self._refresh_token()

    def _refresh_token(self):
        auth = requests.auth.HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET)
        data = {
            "grant_type": "password",
            "username": USERNAME,
            "password": PASSWORD
        }
        headers = {"User-Agent": USER_AGENT}

        try:
            response = requests.post(TOKEN_URL, auth=auth, data=data, headers=headers, timeout=10)
            response.raise_for_status()
            token_data = response.json()

            log.info(f"Reddit token response status: {response.status_code}")
            if response.status_code != 200:
                log.error(f"Reddit token refresh failed with status {response.status_code}: {response.text}")
                self._token = None
                self._token_expires = 0
                return None

            self._token = token_data["access_token"]
            self._token_expires = time.time() + token_data["expires_in"]
            log.info("Successfully refreshed Reddit token.")
            return self._token
        except requests.exceptions.RequestException as e:
            log.error(f"Error refreshing Reddit token: {e}")
            self._token = None
            self._token_expires = 0
            return None

    def _headers(self):
        token = self._get_token()
        if not token:
            raise Exception("Reddit authentication failed: Could not retrieve token.")
        return {
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT
        }

    def _validate_subreddit(self, subreddit):
        if subreddit.lower() not in _WHITELIST_LOWER:
            raise ValueError(f"Subreddit '{subreddit}' is not whitelisted. Allowed: {', '.join(SUBREDDIT_WHITELIST)}")
        return _WHITELIST_LOWER[subreddit.lower()]

    def read(self, subreddit, sort="hot", limit=5):
        subreddit = self._validate_subreddit(subreddit)
        endpoint = f"{API_BASE}/r/{subreddit}/{sort}"
        params = {"limit": limit}
        try:
            response = requests.get(endpoint, headers=self._headers(), params=params, timeout=10)
            response.raise_for_status()
            posts = response.json()["data"]["children"]
            results = []
            for post in posts:
                p_data = post["data"]
                results.append({
                    "title": p_data.get("title"),
                    "author": p_data.get("author"),
                    "score": p_data.get("score"),
                    "num_comments": p_data.get("num_comments"),
                    "url": p_data.get("url"),
                    "permalink": f"https://www.reddit.com{p_data.get('permalink')}",
                    "id": p_data.get("id"),
                    "created_utc": p_data.get("created_utc"),
                    "is_self": p_data.get("is_self"),
                    "selftext": p_data.get("selftext", "") if p_data.get("is_self") else None,
                })
            log.info(f"Read {len(results)} posts from r/{subreddit}.")
            return results
        except requests.exceptions.RequestException as e:
            log.error(f"Error reading Reddit posts from r/{subreddit}: {e}")
            raise
        except Exception as e:
            log.error(f"Unexpected error processing Reddit read for r/{subreddit}: {e}")
            raise

    def search(self, query, subreddit=None, limit=5):
        endpoint = f"{API_BASE}/r/{subreddit}/search" if subreddit else f"{API_BASE}/search"
        params = {"q": query, "limit": limit}
        if subreddit:
            subreddit = self._validate_subreddit(subreddit)
            params["restrict_sr"] = "on"

        try:
            response = requests.get(endpoint, headers=self._headers(), params=params, timeout=10)
            response.raise_for_status()
            posts = response.json()["data"]["children"]
            results = []
            for post in posts:
                p_data = post["data"]
                results.append({
                    "title": p_data.get("title"),
                    "author": p_data.get("author"),
                    "score": p_data.get("score"),
                    "num_comments": p_data.get("num_comments"),
                    "url": p_data.get("url"),
                    "permalink": f"https://www.reddit.com{p_data.get('permalink')}",
                    "id": p_data.get("id"),
                    "created_utc": p_data.get("created_utc"),
                })
            log.info(f"Searched Reddit for '{query}'. Found {len(results)} posts.")
            return results
        except requests.exceptions.RequestException as e:
            log.error(f"Error searching Reddit for '{query}': {e}")
            raise
        except Exception as e:
            log.error(f"Unexpected error processing Reddit search for '{query}': {e}")
            raise

    def post(self, subreddit, title, text=None, url=None):
        if not (text or url):
            raise ValueError("Must provide either 'text' or 'url' for a post.")
        if text and url:
            raise ValueError("Cannot provide both 'text' and 'url'. Choose one.")

        if time.time() - self.last_post_time < self.min_post_interval:
            raise Exception(f"Rate limit: Please wait {self.min_post_interval - (time.time() - self.last_post_time):.0f} seconds before posting again.")

        subreddit = self._validate_subreddit(subreddit)
        endpoint = f"{API_BASE}/api/submit"
        kind = "self" if text else "link"
        data = {
            "sr": subreddit,
            "kind": kind,
            "title": title,
            "api_type": "json",
        }
        if text:
            data["text"] = text
        if url:
            data["url"] = url

        try:
            response = requests.post(endpoint, headers=self._headers(), data=data, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get("json", {}).get("errors"):
                errors = result["json"]["errors"]
                error_msg = "; ".join([f"{e[0]}: {e[1]}" for e in errors])
                log.error(f"Reddit post failed: {error_msg}")
                raise Exception(f"Reddit post failed: {error_msg}")

            log.info(f"Successfully posted to r/{subreddit}: '{title}'")
            self.last_post_time = time.time()
            return {"status": "success", "response": result}
        except requests.exceptions.RequestException as e:
            log.error(f"Error posting to r/{subreddit}: {e}")
            raise
        except Exception as e:
            log.error(f"Unexpected error processing Reddit post for r/{subreddit}: {e}")
            raise

    def comment(self, post_id, text):
        endpoint = f"{API_BASE}/api/comment"
        data = {
            "parent": f"t3_{post_id}",  # t3_ prefix for posts
            "text": text,
            "api_type": "json",
        }
        try:
            response = requests.post(endpoint, headers=self._headers(), data=data, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get("json", {}).get("errors"):
                errors = result["json"]["errors"]
                error_msg = "; ".join([f"{e[0]}: {e[1]}" for e in errors])
                log.error(f"Reddit comment failed: {error_msg}")
                raise Exception(f"Reddit comment failed: {error_msg}")

            log.info(f"Successfully commented on post {post_id}.")
            return {"status": "success", "response": result}
        except requests.exceptions.RequestException as e:
            log.error(f"Error commenting on post {post_id}: {e}")
            raise
        except Exception as e:
            log.error(f"Unexpected error processing Reddit comment for post {post_id}: {e}")
            raise


if __name__ == "__main__":
    client = RedditClient()
    action = sys.argv[1]

    try:
        if action == "read":
            subreddit = sys.argv[2]
            sort = sys.argv[3] if len(sys.argv) > 3 else "hot"
            limit = int(sys.argv[4]) if len(sys.argv) > 4 else 5
            result = client.read(subreddit, sort, limit)
            print(json.dumps({"read_reddit_response": {"result": result}}))
        elif action == "search":
            query = sys.argv[2]
            subreddit = sys.argv[3] if len(sys.argv) > 3 else None
            limit = int(sys.argv[4]) if len(sys.argv) > 4 else 5
            result = client.search(query, subreddit, limit)
            print(json.dumps({"search_reddit_response": {"result": result}}))
        elif action == "post":
            subreddit = sys.argv[2]
            title = sys.argv[3]
            text = sys.argv[4] if len(sys.argv) > 4 else None
            url = sys.argv[5] if len(sys.argv) > 5 else None
            # Determine if it's a text post or link post
            if text and text.startswith("http"): # Simple heuristic: if text looks like a URL, treat as URL
                url = text
                text = None
            result = client.post(subreddit, title, text, url)
            print(json.dumps({"post_reddit_response": {"result": result}}))
        elif action == "comment":
            post_id = sys.argv[2]
            text = sys.argv[3]
            result = client.comment(post_id, text)
            print(json.dumps({"comment_reddit_response": {"result": result}}))
        else:
            print(json.dumps({"error": f"Unknown action: {action}"}))
            sys.exit(1)
    except Exception as e:
        log.error(f"Reddit operation failed: {e}")
        print(json.dumps({"read_reddit_response": {"result": f"Reddit operation failed: {e}"}}))
        sys.exit(1)
