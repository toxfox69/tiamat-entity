#!/usr/bin/env node
/**
 * GitHub App Webhook Receiver
 * Handles CI/CD events and integrates with OpenPango orchestration system.
 *
 * Events handled:
 *   - pull_request (opened, synchronize, closed)
 *   - issue_comment (agent summon via @openpango)
 *   - push (branch protection + CI dispatch)
 *   - workflow_run (status tracking)
 *   - check_run, check_suite
 */

'use strict';

const http = require('http');
const crypto = require('crypto');
const { CIHandler } = require('./ci_handler');
const { GitHubClient } = require('./github_client');

const PORT = parseInt(process.env.GITHUB_WEBHOOK_PORT || '8080', 10);
const WEBHOOK_SECRET = process.env.GITHUB_WEBHOOK_SECRET || '';
const GITHUB_TOKEN = process.env.GITHUB_TOKEN || '';

/** Verify GitHub's HMAC-SHA256 signature */
function verifySignature(payload, signature, secret = WEBHOOK_SECRET) {
  if (!secret) return true; // allow unsigned in dev mode
  if (!signature) return false;

  const expected = `sha256=${crypto
    .createHmac('sha256', secret)
    .update(payload)
    .digest('hex')}`;

  try {
    return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature));
  } catch {
    return false; // length mismatch
  }
}

/** Read full request body */
function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

/** Send JSON response */
function sendJSON(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

class WebhookServer {
  constructor({ port = PORT, secret = WEBHOOK_SECRET, token = GITHUB_TOKEN } = {}) {
    this.port = port;
    this.secret = secret;
    this.ghClient = new GitHubClient(token);
    this.ciHandler = new CIHandler(this.ghClient);
    this.server = null;
    this._eventLog = [];
  }

  /** Route incoming webhook event to the appropriate handler */
  async dispatch(event, payload) {
    const action = payload.action;
    const entry = { ts: new Date().toISOString(), event, action };
    this._eventLog.push(entry);
    console.error(`[webhook] ${event}:${action || '-'} repo=${payload.repository?.full_name || '?'}`);

    switch (event) {
      case 'pull_request':
        return this.ciHandler.onPullRequest(payload);

      case 'issue_comment':
        return this.ciHandler.onIssueComment(payload);

      case 'push':
        return this.ciHandler.onPush(payload);

      case 'workflow_run':
        return this.ciHandler.onWorkflowRun(payload);

      case 'check_run':
        return this.ciHandler.onCheckRun(payload);

      case 'check_suite':
        return this.ciHandler.onCheckSuite(payload);

      default:
        console.error(`[webhook] unhandled event: ${event}`);
        return { handled: false, event };
    }
  }

  async handleRequest(req, res) {
    // Health probe
    if (req.method === 'GET' && req.url === '/health') {
      return sendJSON(res, 200, { status: 'ok', events: this._eventLog.length });
    }

    // Audit log
    if (req.method === 'GET' && req.url === '/events') {
      return sendJSON(res, 200, { events: this._eventLog.slice(-50) });
    }

    if (req.method !== 'POST' || req.url !== '/webhook') {
      return sendJSON(res, 404, { error: 'not found' });
    }

    // Read body
    let rawBody;
    try {
      rawBody = await readBody(req);
    } catch (err) {
      return sendJSON(res, 400, { error: 'body read failed' });
    }

    // Verify signature
    const sig = req.headers['x-hub-signature-256'];
    if (!verifySignature(rawBody, sig, this.secret)) {
      console.error('[webhook] signature verification FAILED');
      return sendJSON(res, 401, { error: 'invalid signature' });
    }

    // Parse JSON
    let payload;
    try {
      payload = JSON.parse(rawBody.toString('utf8'));
    } catch {
      return sendJSON(res, 400, { error: 'invalid JSON' });
    }

    const event = req.headers['x-github-event'];
    if (!event) {
      return sendJSON(res, 400, { error: 'missing x-github-event header' });
    }

    // Dispatch
    try {
      const result = await this.dispatch(event, payload);
      return sendJSON(res, 200, { ok: true, result });
    } catch (err) {
      console.error('[webhook] dispatch error:', err.message);
      return sendJSON(res, 500, { error: 'internal error', message: err.message });
    }
  }

  listen() {
    this.server = http.createServer((req, res) => {
      this.handleRequest(req, res).catch((err) => {
        console.error('[webhook] unhandled:', err);
        sendJSON(res, 500, { error: 'unhandled' });
      });
    });

    return new Promise((resolve) => {
      this.server.listen(this.port, '127.0.0.1', () => {
        console.error(`[webhook] listening on http://127.0.0.1:${this.port}/webhook`);
        resolve(this.server);
      });
    });
  }

  close() {
    return new Promise((resolve, reject) => {
      if (!this.server) return resolve();
      this.server.close((err) => (err ? reject(err) : resolve()));
    });
  }
}

// Start if run directly
if (require.main === module) {
  const server = new WebhookServer();
  server.listen().catch((err) => {
    console.error('Failed to start:', err);
    process.exit(1);
  });

  process.on('SIGTERM', () => server.close().then(() => process.exit(0)));
  process.on('SIGINT', () => server.close().then(() => process.exit(0)));
}

module.exports = { WebhookServer, verifySignature };
