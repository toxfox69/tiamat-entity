'use strict';

const http = require('http');
const crypto = require('crypto');
const { WebhookServer, verifySignature } = require('../webhook_server');
const { GitHubClient } = require('../github_client');
const { CIHandler } = require('../ci_handler');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SECRET = 'test-webhook-secret';

function makeSignature(secret, body) {
  return `sha256=${crypto.createHmac('sha256', secret).update(body).digest('hex')}`;
}

function httpPost(port, path, headers, body) {
  return new Promise((resolve, reject) => {
    const data = typeof body === 'string' ? body : JSON.stringify(body);
    const opts = {
      hostname: '127.0.0.1',
      port,
      path,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(data),
        ...headers,
      },
    };
    const req = http.request(opts, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        let json;
        try { json = JSON.parse(Buffer.concat(chunks).toString()); } catch { json = null; }
        resolve({ status: res.statusCode, body: json });
      });
    });
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

function httpGet(port, path) {
  return new Promise((resolve, reject) => {
    const req = http.request({ hostname: '127.0.0.1', port, path, method: 'GET' }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        let json;
        try { json = JSON.parse(Buffer.concat(chunks).toString()); } catch { json = null; }
        resolve({ status: res.statusCode, body: json });
      });
    });
    req.on('error', reject);
    req.end();
  });
}

// ---------------------------------------------------------------------------
// Mock GitHubClient
// ---------------------------------------------------------------------------

function makeMockGH(overrides = {}) {
  return {
    isBranchProtected: jest.fn().mockResolvedValue(false),
    postComment: jest.fn().mockResolvedValue({ id: 1 }),
    getPRFiles: jest.fn().mockResolvedValue([
      { filename: 'src/index.js', status: 'modified', additions: 10, deletions: 2 },
    ]),
    getPRDiff: jest.fn().mockResolvedValue('--- a/src/index.js\n+++ b/src/index.js\n'),
    getWorkflowRun: jest.fn().mockResolvedValue({}),
    createCheckRun: jest.fn().mockResolvedValue({ id: 42 }),
    updateCheckRun: jest.fn().mockResolvedValue({ id: 42 }),
    getPR: jest.fn().mockResolvedValue({}),
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// 1. Signature verification
// ---------------------------------------------------------------------------

describe('verifySignature', () => {
  test('accepts correct signature', () => {
    const payload = Buffer.from('{"action":"opened"}');
    const sig = makeSignature(SECRET, payload);
    expect(verifySignature(payload, sig, SECRET)).toBe(true);
  });

  test('rejects tampered payload', () => {
    const payload = Buffer.from('{"action":"opened"}');
    const sig = makeSignature(SECRET, Buffer.from('other'));
    expect(verifySignature(payload, sig, SECRET)).toBe(false);
  });

  test('rejects missing signature', () => {
    const payload = Buffer.from('{"action":"opened"}');
    expect(verifySignature(payload, undefined, SECRET)).toBe(false);
  });

  test('accepts any payload when secret is empty (dev mode)', () => {
    const payload = Buffer.from('test');
    expect(verifySignature(payload, undefined, '')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 2. CIHandler — pull_request
// ---------------------------------------------------------------------------

describe('CIHandler.onPullRequest', () => {
  let gh, handler;

  beforeEach(() => {
    gh = makeMockGH();
    handler = new CIHandler(gh);
    // Prevent real router.py calls
    handler._spawnAgent = jest.fn().mockReturnValue('session-pr-001');
  });

  test('handles PR opened', async () => {
    const result = await handler.onPullRequest({
      action: 'opened',
      pull_request: { number: 42, head: { ref: 'feature/x' }, html_url: 'https://github.com/a/b/pull/42' },
      repository: { owner: { login: 'owner' }, name: 'repo' },
    });

    expect(result.handled).toBe(true);
    expect(result.event).toBe('pull_request');
    expect(result.sessionId).toBe('session-pr-001');
    expect(handler._spawnAgent).toHaveBeenCalledWith('Coder', expect.stringContaining('#42'));
    expect(gh.postComment).toHaveBeenCalledWith('owner', 'repo', 42, expect.stringContaining('session-pr-001'));
  });

  test('handles PR synchronize', async () => {
    const result = await handler.onPullRequest({
      action: 'synchronize',
      pull_request: { number: 7, head: { ref: 'feat/y' }, html_url: 'u' },
      repository: { owner: { login: 'o' }, name: 'r' },
    });
    expect(result.handled).toBe(true);
    expect(result.action).toBe('synchronize');
  });

  test('ignores PR closed', async () => {
    const result = await handler.onPullRequest({
      action: 'closed',
      pull_request: { number: 1, head: { ref: 'b' }, html_url: 'u' },
      repository: { owner: { login: 'o' }, name: 'r' },
    });
    expect(result.handled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 3. CIHandler — issue_comment (agent summon)
// ---------------------------------------------------------------------------

describe('CIHandler.onIssueComment', () => {
  let gh, handler;

  beforeEach(() => {
    gh = makeMockGH();
    handler = new CIHandler(gh);
    handler._spawnAgent = jest.fn().mockReturnValue('session-comment-001');
  });

  test('summons agent on @openpango mention', async () => {
    const result = await handler.onIssueComment({
      action: 'created',
      comment: { body: '@openpango fix this null pointer bug' },
      issue: { number: 5, title: 'NPE in auth module', html_url: 'https://github.com/o/r/issues/5' },
      repository: {
        owner: { login: 'owner' }, name: 'repo',
        default_branch: 'main',
      },
    });

    expect(result.handled).toBe(true);
    expect(result.command).toBe('fix this null pointer bug');
    expect(result.sessionId).toBe('session-comment-001');
    expect(gh.isBranchProtected).toHaveBeenCalledWith('owner', 'repo', 'main');
    expect(gh.postComment).toHaveBeenCalled();
  });

  test('uses safe branch when base is protected', async () => {
    gh.isBranchProtected.mockResolvedValue(true);

    const result = await handler.onIssueComment({
      action: 'created',
      comment: { body: '@openpango add tests' },
      issue: { number: 99, title: 'Need tests', html_url: 'u' },
      repository: { owner: { login: 'o' }, name: 'r', default_branch: 'main' },
    });

    expect(result.targetBranch).toBe('openpango/fix-issue-99');
    expect(handler._spawnAgent).toHaveBeenCalledWith('Coder', expect.stringContaining('openpango/fix-issue-99'));
  });

  test('ignores comments without @openpango', async () => {
    const result = await handler.onIssueComment({
      action: 'created',
      comment: { body: 'great issue!' },
      issue: { number: 1, title: 'x', html_url: 'u' },
      repository: { owner: { login: 'o' }, name: 'r', default_branch: 'main' },
    });
    expect(result.handled).toBe(false);
    expect(gh.postComment).not.toHaveBeenCalled();
  });

  test('ignores edit actions', async () => {
    const result = await handler.onIssueComment({
      action: 'edited',
      comment: { body: '@openpango fix it' },
      issue: { number: 1, title: 'x', html_url: 'u' },
      repository: { owner: { login: 'o' }, name: 'r', default_branch: 'main' },
    });
    expect(result.handled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 4. CIHandler — push
// ---------------------------------------------------------------------------

describe('CIHandler.onPush', () => {
  let gh, handler;

  beforeEach(() => {
    gh = makeMockGH();
    handler = new CIHandler(gh);
    handler._spawnAgent = jest.fn().mockReturnValue('session-push-001');
  });

  test('handles push to feature branch', async () => {
    gh.isBranchProtected.mockResolvedValue(false);

    const result = await handler.onPush({
      ref: 'refs/heads/feature/my-feature',
      repository: { owner: { login: 'o' }, name: 'r' },
      pusher: { name: 'alice' },
      commits: [{ id: 'abc1234', message: 'add feature' }],
    });

    expect(result.handled).toBe(true);
    expect(result.branch).toBe('feature/my-feature');
    expect(result.protected).toBe(false);
  });

  test('flags push to main as protected', async () => {
    gh.isBranchProtected.mockResolvedValue(true);

    const result = await handler.onPush({
      ref: 'refs/heads/main',
      repository: { owner: { login: 'o' }, name: 'r' },
      pusher: { name: 'alice' },
      commits: [{ id: 'abc', message: 'merge PR' }],
    });

    expect(result.protected).toBe(true);
    expect(handler._spawnAgent).toHaveBeenCalledWith('Manager', expect.stringContaining('protected: true'));
  });

  test('skips push with no commits', async () => {
    const result = await handler.onPush({
      ref: 'refs/heads/main',
      repository: { owner: { login: 'o' }, name: 'r' },
      pusher: { name: 'alice' },
      commits: [],
    });
    expect(result.handled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 5. CIHandler — workflow_run
// ---------------------------------------------------------------------------

describe('CIHandler.onWorkflowRun', () => {
  let gh, handler;

  beforeEach(() => {
    gh = makeMockGH();
    handler = new CIHandler(gh);
    handler._spawnAgent = jest.fn().mockReturnValue('session-wf-001');
  });

  test('dispatches investigation on failure', async () => {
    const result = await handler.onWorkflowRun({
      action: 'completed',
      workflow_run: {
        conclusion: 'failure',
        name: 'CI',
        html_url: 'https://github.com/o/r/actions/runs/1',
        head_branch: 'feature/x',
      },
      repository: { owner: { login: 'o' }, name: 'r' },
    });

    expect(result.handled).toBe(true);
    expect(result.conclusion).toBe('failure');
    expect(handler._spawnAgent).toHaveBeenCalledWith('Researcher', expect.stringContaining('failure'));
  });

  test('dispatches on timeout', async () => {
    const result = await handler.onWorkflowRun({
      action: 'completed',
      workflow_run: {
        conclusion: 'timed_out',
        name: 'CI',
        html_url: 'u',
        head_branch: 'main',
      },
      repository: { owner: { login: 'o' }, name: 'r' },
    });
    expect(result.sessionId).toBe('session-wf-001');
  });

  test('logs but does not dispatch on success', async () => {
    const result = await handler.onWorkflowRun({
      action: 'completed',
      workflow_run: {
        conclusion: 'success',
        name: 'CI',
        html_url: 'u',
        head_branch: 'main',
      },
      repository: { owner: { login: 'o' }, name: 'r' },
    });
    expect(result.handled).toBe(true);
    expect(handler._spawnAgent).not.toHaveBeenCalled();
  });

  test('ignores non-completed actions', async () => {
    const result = await handler.onWorkflowRun({
      action: 'requested',
      workflow_run: { conclusion: null, name: 'CI', html_url: 'u', head_branch: 'main' },
      repository: { owner: { login: 'o' }, name: 'r' },
    });
    expect(result.handled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 6. WebhookServer HTTP integration
// ---------------------------------------------------------------------------

describe('WebhookServer HTTP', () => {
  let server;
  const TEST_PORT = 18181;

  beforeAll(async () => {
    server = new WebhookServer({ port: TEST_PORT, secret: SECRET, token: '' });

    // Stub CIHandler so we don't hit GitHub or router.py
    server.ciHandler.onPullRequest = jest.fn().mockResolvedValue({ handled: true, event: 'pull_request' });
    server.ciHandler.onIssueComment = jest.fn().mockResolvedValue({ handled: true });
    server.ciHandler.onPush = jest.fn().mockResolvedValue({ handled: true });
    server.ciHandler.onWorkflowRun = jest.fn().mockResolvedValue({ handled: true });

    await server.listen();
  });

  afterAll(() => server.close());

  test('GET /health returns ok', async () => {
    const res = await httpGet(TEST_PORT, '/health');
    expect(res.status).toBe(200);
    expect(res.body.status).toBe('ok');
  });

  test('POST /webhook with valid signature processes event', async () => {
    const payload = JSON.stringify({
      action: 'opened',
      pull_request: { number: 1, head: { ref: 'feat' }, html_url: 'u' },
      repository: { owner: { login: 'o' }, name: 'r' },
    });
    const sig = makeSignature(SECRET, payload);

    const res = await httpPost(TEST_PORT, '/webhook', {
      'x-github-event': 'pull_request',
      'x-hub-signature-256': sig,
    }, payload);

    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
  });

  test('POST /webhook with bad signature returns 401', async () => {
    const payload = JSON.stringify({ action: 'opened' });
    const res = await httpPost(TEST_PORT, '/webhook', {
      'x-github-event': 'pull_request',
      'x-hub-signature-256': 'sha256=badhash',
    }, payload);
    expect(res.status).toBe(401);
  });

  test('POST /webhook missing event header returns 400', async () => {
    const payload = JSON.stringify({});
    const sig = makeSignature(SECRET, payload);
    const res = await httpPost(TEST_PORT, '/webhook', {
      'x-hub-signature-256': sig,
    }, payload);
    expect(res.status).toBe(400);
  });

  test('POST /webhook with invalid JSON returns 400', async () => {
    const payload = 'not json';
    const sig = makeSignature(SECRET, payload);
    const res = await httpPost(TEST_PORT, '/webhook', {
      'x-github-event': 'push',
      'x-hub-signature-256': sig,
    }, payload);
    expect(res.status).toBe(400);
  });

  test('unknown event returns 200 with handled:false', async () => {
    const payload = JSON.stringify({ action: 'foo' });
    const sig = makeSignature(SECRET, payload);
    const res = await httpPost(TEST_PORT, '/webhook', {
      'x-github-event': 'star',
      'x-hub-signature-256': sig,
    }, payload);
    expect(res.status).toBe(200);
    expect(res.body.result.handled).toBe(false);
  });

  test('GET /events returns audit log', async () => {
    const res = await httpGet(TEST_PORT, '/events');
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body.events)).toBe(true);
  });

  test('GET /unknown returns 404', async () => {
    const res = await httpGet(TEST_PORT, '/unknown');
    expect(res.status).toBe(404);
  });
});

// ---------------------------------------------------------------------------
// 7. GitHubClient — branch protection patterns
// ---------------------------------------------------------------------------

describe('GitHubClient.isBranchProtected', () => {
  test('main is protected by convention', async () => {
    const gh = new GitHubClient(''); // no token → convention only
    expect(await gh.isBranchProtected('o', 'r', 'main')).toBe(true);
  });

  test('master is protected by convention', async () => {
    const gh = new GitHubClient('');
    expect(await gh.isBranchProtected('o', 'r', 'master')).toBe(true);
  });

  test('develop is protected by convention', async () => {
    const gh = new GitHubClient('');
    expect(await gh.isBranchProtected('o', 'r', 'develop')).toBe(true);
  });

  test('release/* is protected by convention', async () => {
    const gh = new GitHubClient('');
    expect(await gh.isBranchProtected('o', 'r', 'release/1.0')).toBe(true);
  });

  test('feature branch is not protected by convention', async () => {
    const gh = new GitHubClient('');
    expect(await gh.isBranchProtected('o', 'r', 'feature/my-feature')).toBe(false);
  });

  test('fix branch is not protected by convention', async () => {
    const gh = new GitHubClient('');
    expect(await gh.isBranchProtected('o', 'r', 'fix/bug-123')).toBe(false);
  });
});
