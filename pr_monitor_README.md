# pr_monitor — GitHub PR Status Monitor

Batch-checks GitHub PR statuses from a JSON input file. Outputs a console table and CSV report.

## Features

- Batch monitor any number of PRs across multiple repos
- Shows: state, merged, mergeable, review count, last update, title
- Rate limiting: configurable, default 10 req/min (stays well under GitHub's 60/min unauthenticated limit)
- Handles closed/merged PRs, invalid repos, API errors gracefully
- Optional GitHub token for higher rate limits (5000 req/hr authenticated vs 60 unauthenticated)
- CSV output for spreadsheet analysis
- Zero dependencies beyond `requests`

## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Basic — reads example.json, writes pr_results.csv
python pr_monitor.py example.json

# Custom output file
python pr_monitor.py prs.json --output my_results.csv

# With GitHub token (recommended for >60 PRs/hr)
python pr_monitor.py prs.json --token ghp_yourtoken

# Or via environment variable
GITHUB_TOKEN=ghp_yourtoken python pr_monitor.py prs.json

# Table only, no CSV
python pr_monitor.py prs.json --no-csv

# Custom rate limit (e.g. 30/min with a token)
python pr_monitor.py prs.json --token ghp_xxx --rate-limit 30

# Quiet mode (no progress, just table + summary)
python pr_monitor.py prs.json --quiet
```

## Input Format

JSON array of `{"repo": "owner/name", "pr": number}` objects:

```json
[
  {"repo": "llvm/torch-mlir",       "pr": 4862},
  {"repo": "tenstorrent/tt-mlir",   "pr": 7327},
  {"repo": "openpango/pango",        "pr": 186},
  {"repo": "huggingface/transformers","pr": 35000}
]
```

## Output

### Console table

```
Repo                          PR      State     Merged   Mergeable   Reviews  Last Update   Title                                     Error
----------------------------  ------  --------  -------  ----------  -------  ------------  ----------------------------------------  ------------------------------
llvm/torch-mlir               4862    closed    yes      n/a         3        14d ago       [torch] Add TorchScript export pass
tenstorrent/tt-mlir           7327    open      no       yes         1        2h ago        Fix segfault in ttnn.matmul
openpango/pango               186     closed    no       n/a         0        3mo ago       Add PNG export support
huggingface/transformers      35000   closed    yes      n/a         5        1y ago        Improve tokenizer performance
```

### CSV columns

| Column         | Description                              |
|----------------|------------------------------------------|
| `repo`         | `owner/repo`                             |
| `pr`           | PR number                                |
| `state`        | `open` or `closed`                       |
| `merged`       | `yes` / `no`                             |
| `mergeable`    | `yes` / `no` / `unknown` / `n/a`        |
| `reviews_count`| Number of submitted reviews              |
| `last_update`  | Human-readable time since last activity  |
| `title`        | PR title (truncated to 80 chars)         |
| `url`          | Direct link to the PR                    |
| `error`        | Error message if fetch failed            |

## Rate Limits

| Auth status        | GitHub limit   | Recommended `--rate-limit` |
|--------------------|----------------|----------------------------|
| Unauthenticated    | 60 req/hr      | 10 (default)               |
| Authenticated token| 5000 req/hr    | 30–60                      |

Note: each PR check uses 2 API calls (PR data + reviews). The rate limiter applies between PRs.

## Examples

### Track bounty-eligible PRs

```json
[
  {"repo": "tenstorrent/tt-mlir",   "pr": 7327},
  {"repo": "llvm/torch-mlir",       "pr": 4862},
  {"repo": "openpango/pango",        "pr": 186}
]
```

```bash
python pr_monitor.py bounties.json --output bounty_status.csv
```

### Pipe from grep/jq

```bash
# Generate input from a list of PR URLs
echo '[{"repo":"owner/repo","pr":123}]' > prs.json
python pr_monitor.py prs.json
```

## Notes

- GitHub's `mergeable` field is computed lazily — it may return `unknown` for PRs not recently viewed. Re-check after a few minutes.
- Closed PRs that were never merged via the Pulls API endpoint may return 404; the tool falls back to the Issues API to handle these correctly.
- No authentication is required for public repos, but a token is strongly recommended for batch monitoring of >6 PRs to avoid hitting the 60 req/hr limit.

## License

MIT
