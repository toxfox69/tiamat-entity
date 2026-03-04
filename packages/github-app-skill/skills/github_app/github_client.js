/**
 * Minimal GitHub REST API client using stdlib https only.
 * Handles: comments, PR diffs, branch protection checks.
 */

'use strict';

const https = require('https');

class GitHubClient {
  constructor(token) {
    this.token = token;
    this.baseHeaders = {
      'User-Agent': 'openpango-github-app/1.0',
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
  }

  /** Low-level request helper */
  _request(method, path, body = null) {
    return new Promise((resolve, reject) => {
      const opts = {
        hostname: 'api.github.com',
        port: 443,
        path,
        method,
        headers: { ...this.baseHeaders },
      };

      if (body) {
        const data = JSON.stringify(body);
        opts.headers['Content-Type'] = 'application/json';
        opts.headers['Content-Length'] = Buffer.byteLength(data);
      }

      const req = https.request(opts, (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          const raw = Buffer.concat(chunks).toString('utf8');
          let json;
          try { json = JSON.parse(raw); } catch { json = raw; }
          if (res.statusCode >= 400) {
            reject(Object.assign(new Error(`GitHub API ${res.statusCode}`), { status: res.statusCode, body: json }));
          } else {
            resolve(json);
          }
        });
      });

      req.on('error', reject);
      if (body) req.write(JSON.stringify(body));
      req.end();
    });
  }

  /** Check if a branch is protected */
  async isBranchProtected(owner, repo, branch) {
    // Protected by convention: main, master, develop, release/*
    const PROTECTED_PATTERNS = [/^main$/, /^master$/, /^develop$/, /^release\/.+/];
    if (PROTECTED_PATTERNS.some((p) => p.test(branch))) return true;

    // Check via API if token is available
    if (!this.token) return false;
    try {
      await this._request('GET', `/repos/${owner}/${repo}/branches/${encodeURIComponent(branch)}/protection`);
      return true; // 200 → protected
    } catch (err) {
      if (err.status === 404) return false; // no protection rule
      if (err.status === 403) return false; // not admin — assume unprotected
      throw err;
    }
  }

  /** Post a comment on an issue or PR */
  async postComment(owner, repo, issueNumber, body) {
    return this._request(
      'POST',
      `/repos/${owner}/${repo}/issues/${issueNumber}/comments`,
      { body }
    );
  }

  /** Get PR diff (returns raw patch text) */
  async getPRDiff(owner, repo, pullNumber) {
    return new Promise((resolve, reject) => {
      const opts = {
        hostname: 'api.github.com',
        port: 443,
        path: `/repos/${owner}/${repo}/pulls/${pullNumber}`,
        method: 'GET',
        headers: {
          ...this.baseHeaders,
          Accept: 'application/vnd.github.diff',
        },
      };

      const req = https.request(opts, (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
      });
      req.on('error', reject);
      req.end();
    });
  }

  /** List files changed in a PR */
  async getPRFiles(owner, repo, pullNumber) {
    return this._request('GET', `/repos/${owner}/${repo}/pulls/${pullNumber}/files`);
  }

  /** Get workflow run details */
  async getWorkflowRun(owner, repo, runId) {
    return this._request('GET', `/repos/${owner}/${repo}/actions/runs/${runId}`);
  }

  /** Create a check run */
  async createCheckRun(owner, repo, data) {
    return this._request('POST', `/repos/${owner}/${repo}/check-runs`, data);
  }

  /** Update a check run */
  async updateCheckRun(owner, repo, checkRunId, data) {
    return this._request('PATCH', `/repos/${owner}/${repo}/check-runs/${checkRunId}`, data);
  }

  /** Get PR info */
  async getPR(owner, repo, pullNumber) {
    return this._request('GET', `/repos/${owner}/${repo}/pulls/${pullNumber}`);
  }
}

module.exports = { GitHubClient };
