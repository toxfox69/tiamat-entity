#!/usr/bin/env node
/**
 * TIAMAT Supply Chain Scanner — MCP Server
 *
 * Adds scan_package tool to Claude Code / Cline / any MCP client.
 * Scans npm and PyPI packages for supply chain attack indicators.
 *
 * Install: npx @tiamat/scanner-mcp
 * Or add to claude_desktop_config.json / settings.json
 */

const http = require('https');
const readline = require('readline');

const API_URL = 'https://tiamat.live/scan';

// MCP Protocol implementation over stdio
const rl = readline.createInterface({ input: process.stdin });
let buffer = '';

function send(msg) {
  const json = JSON.stringify(msg);
  process.stdout.write(`Content-Length: ${Buffer.byteLength(json)}\r\n\r\n${json}`);
}

function scanPackage(packageName, registry = 'auto') {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ package: packageName, registry });
    const url = new URL(API_URL);
    const options = {
      hostname: url.hostname,
      port: 443,
      path: url.pathname,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
        'User-Agent': 'tiamat-scanner-mcp/1.0',
      },
    };
    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error(`Parse error: ${data.slice(0, 200)}`)); }
      });
    });
    req.on('error', reject);
    req.setTimeout(30000, () => { req.destroy(); reject(new Error('Timeout')); });
    req.write(body);
    req.end();
  });
}

function formatResult(d) {
  if (d.error) return `Error: ${d.error}`;

  let out = `## ${d.package} v${d.version} (${d.registry})\n`;
  out += `**Risk Score: ${d.risk_score}/100 — ${d.risk_level}**\n\n`;

  const m = d.metadata || {};
  if (m.weekly_downloads !== undefined) out += `- Downloads/week: ${m.weekly_downloads.toLocaleString()}\n`;
  if (m.age_days) out += `- Package age: ${m.age_days} days\n`;
  if (m.maintainer_count) out += `- Maintainers: ${m.maintainer_count}\n`;
  if (m.license) out += `- License: ${m.license}\n`;
  out += '\n';

  if (d.findings && d.findings.length > 0) {
    out += '### Findings\n';
    for (const f of d.findings) {
      const icon = f.severity === 'critical' ? '🔴' : f.severity === 'high' ? '🟠' : f.severity === 'medium' ? '🟡' : '🟢';
      out += `${icon} **[${f.severity.toUpperCase()}]** ${f.category}: ${f.detail}\n`;
    }
    out += '\n';
  } else {
    out += '✅ No supply chain attack indicators detected.\n\n';
  }

  if (d.ai_summary) {
    out += `### AI Assessment\n${d.ai_summary}\n`;
  }

  return out;
}

async function handleMessage(msg) {
  if (msg.method === 'initialize') {
    send({
      jsonrpc: '2.0',
      id: msg.id,
      result: {
        protocolVersion: '2024-11-05',
        capabilities: { tools: {} },
        serverInfo: {
          name: 'tiamat-scanner',
          version: '1.0.0',
        },
      },
    });
  } else if (msg.method === 'notifications/initialized') {
    // No response needed
  } else if (msg.method === 'tools/list') {
    send({
      jsonrpc: '2.0',
      id: msg.id,
      result: {
        tools: [
          {
            name: 'scan_package',
            description: 'Scan an npm or PyPI package for supply chain attack indicators including typosquatting, malicious install scripts, code obfuscation, and dependency confusion. Use this before installing unfamiliar packages.',
            inputSchema: {
              type: 'object',
              properties: {
                package: {
                  type: 'string',
                  description: 'Package name to scan (e.g. "express", "requests", "litellm")',
                },
                registry: {
                  type: 'string',
                  enum: ['npm', 'pypi', 'auto'],
                  description: 'Package registry. Default: auto-detect.',
                  default: 'auto',
                },
              },
              required: ['package'],
            },
          },
        ],
      },
    });
  } else if (msg.method === 'tools/call') {
    const { name, arguments: args } = msg.params;
    if (name === 'scan_package') {
      try {
        const result = await scanPackage(args.package, args.registry || 'auto');
        send({
          jsonrpc: '2.0',
          id: msg.id,
          result: {
            content: [{ type: 'text', text: formatResult(result) }],
          },
        });
      } catch (err) {
        send({
          jsonrpc: '2.0',
          id: msg.id,
          result: {
            content: [{ type: 'text', text: `Scan failed: ${err.message}` }],
            isError: true,
          },
        });
      }
    }
  } else if (msg.id) {
    send({ jsonrpc: '2.0', id: msg.id, error: { code: -32601, message: 'Method not found' } });
  }
}

// Parse MCP messages from stdin (Content-Length header framing)
process.stdin.on('data', (chunk) => {
  buffer += chunk.toString();
  while (true) {
    const headerEnd = buffer.indexOf('\r\n\r\n');
    if (headerEnd === -1) break;
    const header = buffer.slice(0, headerEnd);
    const match = header.match(/Content-Length:\s*(\d+)/i);
    if (!match) { buffer = buffer.slice(headerEnd + 4); continue; }
    const len = parseInt(match[1]);
    const bodyStart = headerEnd + 4;
    if (buffer.length < bodyStart + len) break;
    const body = buffer.slice(bodyStart, bodyStart + len);
    buffer = buffer.slice(bodyStart + len);
    try {
      handleMessage(JSON.parse(body));
    } catch (e) {
      process.stderr.write(`Parse error: ${e.message}\n`);
    }
  }
});

process.stderr.write('TIAMAT Supply Chain Scanner MCP server running\n');
