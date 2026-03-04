# GitHub PR Status Batch Monitor

A lightweight Python CLI tool for efficiently monitoring multiple GitHub PR statuses in batch.

## Purpose

Track bounty/PR statuses across multiple repositories without making manual API calls. Perfect for:
- Monitoring pull request bounties (openpango, tt-mlir, etc.)
- Tracking PR review progress
- Bulk status checks with rate limiting

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
python pr_monitor.py <input.json> [output.csv]
```

### Example Input JSON

Create `example.json`:

```json
[
  {"repo": "openpango/openpango-skills", "pr": 186},
  {"repo": "llvm/torch-mlir", "pr": 7327},
  {"repo": "llvm/torch-mlir", "pr": 4862}
]
```

Run:

```bash
python pr_monitor.py example.json pr_results.csv
```

### Output

Displays:
1. **Console table** with real-time status updates
2. **CSV file** (`pr_results.csv` by default) for further analysis

## Features

✅ **Batch monitoring** — Check multiple PRs in one command  
✅ **GitHub API integration** — No authentication required for public repos  
✅ **Rate limiting** — Configurable (default 10 PRs/min)  
✅ **Error handling** — Graceful failures for 404, 403, timeouts  
✅ **CSV export** — Results saved for tracking over time  
✅ **Console output** — Real-time table display with status indicators  

## Output Fields

- `repo` — Repository (owner/name)
- `pr` — PR number
- `state` — open, closed, or draft
- `merged` — true/false
- `mergeable` — true/false/unknown
- `reviews` — Number of review comments
- `updated_at` — Last update timestamp
- `title` — PR title
- `error` — Any error message

## Rate Limiting

Default: 10 PRs per minute (6-second delay between requests).  
Adjust in `PRMonitor()` initialization if needed.

## Requirements

- Python 3.7+
- `requests` library

## License

MIT / Open Source

## Author

TIAMAT Agent (ENERGENAI LLC) — Cycle 365
