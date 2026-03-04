/**
 * CI/CD Event Handler
 *
 * Processes GitHub App webhook events and integrates with the
 * OpenPango orchestration system (skills/orchestration/router.py).
 *
 * Key behaviours:
 *   - PR opened/synchronize → dispatch Code Review task to Coder/Manager agent
 *   - Issue comment "@openpango <cmd>" → summon agent, clone repo, fix, submit PR
 *   - Push → detect protected branches, dispatch CI task
 *   - Workflow run → log status, dispatch follow-up on failure
 *   - Never auto-merge to main/master (strict permission scoping)
 */

'use strict';

const { execFileSync } = require('child_process');
const path = require('path');

// Path to the openpango orchestration router
const ROUTER = process.env.OPENPANGO_ROUTER ||
  path.resolve(__dirname, '../../orchestration/router.py');

/** Summon agent via `@openpango <command>` comment syntax */
const MENTION_RE = /@openpango\s+(.+)/i;

class CIHandler {
  constructor(ghClient) {
    this.gh = ghClient;
  }

  // ---------------------------------------------------------------------------
  // PR events
  // ---------------------------------------------------------------------------

  async onPullRequest(payload) {
    const { action, pull_request: pr, repository: repo } = payload;
    if (!['opened', 'synchronize', 'reopened'].includes(action)) {
      return { handled: false, reason: `action ${action} not handled` };
    }

    const owner = repo.owner.login;
    const repoName = repo.name;
    const prNum = pr.number;
    const headBranch = pr.head.ref;

    // Fetch diff summary
    let diffSummary = '';
    try {
      const files = await this.gh.getPRFiles(owner, repoName, prNum);
      diffSummary = files
        .slice(0, 20) // cap at 20 files
        .map((f) => `${f.status} ${f.filename} (+${f.additions}/-${f.deletions})`)
        .join('\n');
    } catch (err) {
      console.error('[ci] getPRFiles failed:', err.message);
    }

    const task = [
      `Code Review Task for PR #${prNum} in ${owner}/${repoName}`,
      `Branch: ${headBranch}`,
      `Action: ${action}`,
      `Changed files:\n${diffSummary || '(unavailable)'}`,
      `URL: ${pr.html_url}`,
    ].join('\n');

    const sessionId = this._spawnAgent('Coder', task);

    // Post acknowledgement comment
    try {
      await this.gh.postComment(
        owner, repoName, prNum,
        `🤖 **OpenPango** is reviewing this PR (session \`${sessionId}\`).\n` +
        `I'll post findings shortly.`
      );
    } catch (err) {
      console.error('[ci] postComment failed:', err.message);
    }

    return { handled: true, event: 'pull_request', action, sessionId };
  }

  // ---------------------------------------------------------------------------
  // Issue comment events (agent summon)
  // ---------------------------------------------------------------------------

  async onIssueComment(payload) {
    const { action, comment, issue, repository: repo } = payload;
    if (action !== 'created') return { handled: false };

    const body = comment.body || '';
    const match = body.match(MENTION_RE);
    if (!match) return { handled: false, reason: 'no @openpango mention' };

    const command = match[1].trim();
    const owner = repo.owner.login;
    const repoName = repo.name;
    const issueNum = issue.number;

    // Determine safe target branch (never main/master)
    const baseBranch = repo.default_branch || 'main';
    const isProtected = await this.gh.isBranchProtected(owner, repoName, baseBranch);
    const targetBranch = isProtected
      ? `openpango/fix-issue-${issueNum}`
      : baseBranch;

    const task = [
      `Agent Summon from issue #${issueNum} comment`,
      `Repository: ${owner}/${repoName}`,
      `Command: ${command}`,
      `Issue: ${issue.title}`,
      `Target branch: ${targetBranch}`,
      `IMPORTANT: Do NOT commit directly to ${baseBranch}. Open a PR to ${targetBranch}.`,
      `Issue URL: ${issue.html_url}`,
    ].join('\n');

    const sessionId = this._spawnAgent('Coder', task);

    try {
      await this.gh.postComment(
        owner, repoName, issueNum,
        `🤖 **OpenPango** is on it!\n` +
        `Command: \`${command}\`\n` +
        `Session: \`${sessionId}\`\n` +
        `I'll open a PR to \`${targetBranch}\` when done.`
      );
    } catch (err) {
      console.error('[ci] postComment failed:', err.message);
    }

    return { handled: true, event: 'issue_comment', command, sessionId, targetBranch };
  }

  // ---------------------------------------------------------------------------
  // Push events
  // ---------------------------------------------------------------------------

  async onPush(payload) {
    const { ref, repository: repo, pusher, commits = [] } = payload;
    const branch = ref.replace('refs/heads/', '');
    const owner = repo.owner.login;
    const repoName = repo.name;

    // Check if this is a protected branch push (read-only for our agent)
    const isProtected = await this.gh.isBranchProtected(owner, repoName, branch);

    if (commits.length === 0) {
      return { handled: false, reason: 'no commits' };
    }

    const task = [
      `Push CI Task`,
      `Repository: ${owner}/${repoName}`,
      `Branch: ${branch} (protected: ${isProtected})`,
      `Pusher: ${pusher?.name || 'unknown'}`,
      `Commits: ${commits.length}`,
      commits.slice(0, 5).map((c) => `  - ${c.id?.slice(0, 7)} ${c.message?.split('\n')[0]}`).join('\n'),
      isProtected
        ? 'NOTE: This is a protected branch. Agent must NOT push directly here.'
        : '',
    ].filter(Boolean).join('\n');

    const sessionId = this._spawnAgent('Manager', task);
    return { handled: true, event: 'push', branch, protected: isProtected, sessionId };
  }

  // ---------------------------------------------------------------------------
  // Workflow run events
  // ---------------------------------------------------------------------------

  async onWorkflowRun(payload) {
    const { action, workflow_run: run, repository: repo } = payload;
    if (action !== 'completed') return { handled: false, reason: 'not completed' };

    const { conclusion, name, html_url, head_branch } = run;
    const owner = repo.owner.login;
    const repoName = repo.name;

    console.error(
      `[ci] workflow_run "${name}" on ${head_branch}: ${conclusion}`
    );

    if (conclusion === 'failure' || conclusion === 'timed_out') {
      const task = [
        `Workflow Failure Investigation`,
        `Repository: ${owner}/${repoName}`,
        `Workflow: ${name}`,
        `Branch: ${head_branch}`,
        `Conclusion: ${conclusion}`,
        `URL: ${html_url}`,
        `Task: Analyze the failure, suggest a fix, open a PR if appropriate.`,
        `IMPORTANT: Do NOT push to ${head_branch} if it is protected.`,
      ].join('\n');

      const sessionId = this._spawnAgent('Researcher', task);
      return { handled: true, event: 'workflow_run', conclusion, sessionId };
    }

    return { handled: true, event: 'workflow_run', conclusion, action: 'logged' };
  }

  // ---------------------------------------------------------------------------
  // Check run / suite (status tracking)
  // ---------------------------------------------------------------------------

  async onCheckRun(payload) {
    const { action, check_run: run } = payload;
    if (!['completed', 'rerequested'].includes(action)) return { handled: false };
    console.error(`[ci] check_run "${run.name}" → ${run.conclusion || action}`);
    return { handled: true, event: 'check_run', name: run.name, action };
  }

  async onCheckSuite(payload) {
    const { action, check_suite: suite } = payload;
    if (action !== 'completed') return { handled: false };
    console.error(`[ci] check_suite ${suite.head_branch} → ${suite.conclusion}`);
    return { handled: true, event: 'check_suite', conclusion: suite.conclusion };
  }

  // ---------------------------------------------------------------------------
  // Orchestration bridge
  // ---------------------------------------------------------------------------

  /**
   * Spawn an OpenPango agent session via router.py.
   * Returns session ID or a fallback ID if router is unavailable.
   */
  _spawnAgent(agentType, task) {
    try {
      const sessionId = execFileSync('python3', [ROUTER, 'spawn', agentType], {
        encoding: 'utf8',
        timeout: 10_000,
        stdio: ['pipe', 'pipe', 'pipe'],
      }).trim();

      execFileSync('python3', [ROUTER, 'append', sessionId, task], {
        encoding: 'utf8',
        timeout: 10_000,
        stdio: ['pipe', 'pipe', 'pipe'],
      });

      console.error(`[ci] spawned ${agentType} session ${sessionId}`);
      return sessionId;
    } catch (err) {
      // Router not available (e.g. in test/standalone mode)
      const fallback = `local-${agentType.toLowerCase()}-${Date.now()}`;
      console.error(`[ci] router unavailable, fallback session: ${fallback} — ${err.message}`);
      return fallback;
    }
  }
}

module.exports = { CIHandler };
