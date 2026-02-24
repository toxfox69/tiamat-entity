# Drift Monitor v2 — Enterprise Assets

Built 2026-02-24. Ready to deploy.

## Structure

```
drift-v2/
├── pricing.html              ← /pricing page (deploy to tiamat.live)
├── blog/
│   ├── post-1-early-warning.md          ← PSI, fraud model case study
│   ├── post-2-recommendation-systems.md ← Embedding drift, recsys case study
│   └── post-3-automating-ml-observability.md ← Full MLOps integration guide
└── sdk/
    └── drift_monitor_sdk.py  ← Python client SDK
```

## Deploy Checklist

### Pricing Page
- Add route in summarize_api.py: `GET /pricing` → render pricing.html
- Or serve as static via nginx: `location /pricing { try_files /path/to/pricing.html =404; }`
- Update Slack webhook URL on `mailto:` links if needed
- Toggle annual/monthly billing is client-side JS — no backend needed

### Blog Posts
- Convert .md → HTML using your templating system, OR
- Serve raw .md via a markdown renderer endpoint, OR
- Post to dev.to / Hashnode / Medium (copy-paste ready)
- Internal links between posts work as relative paths if served together

### SDK
- Works as a drop-in file: `from drift_monitor_sdk import DriftMonitor`
- No external deps beyond `requests` (stdlib only otherwise)
- CLI: `python drift_monitor_sdk.py register my-model numeric`
- Future: `pip install tiamat-drift` (package TBD)

## API Endpoints Referenced

All at https://tiamat.live:

| Endpoint | Description |
|----------|-------------|
| `POST /drift/register` | Register model (name, model_type, config) |
| `POST /drift/baseline` | Set baseline (model_id, samples[20+]) |
| `POST /drift/check` | Check drift (model_id, samples[5+]) |
| `GET /drift/status/<id>` | Status + history |
| `GET /drift/dashboard` | Visual dashboard |
| `POST /drift/alert/test` | Test webhook delivery |
| `GET /drift/meta` | API metadata |

## Pricing Tiers (as documented in pricing.html)

| Tier | Price | Models | Checks/day | Webhooks |
|------|-------|--------|------------|----------|
| Free | $0 | 1 | 10 | No |
| Pro | $99/mo | 5 | Unlimited | Yes (webhook + Slack) |
| Enterprise | Custom | Unlimited | Unlimited | All (PagerDuty, Teams) |

Contact: tiamat.entity.prime@gmail.com
