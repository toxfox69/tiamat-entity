#!/usr/bin/env python3
"""
Pricing Experiment Setup — A/B test 3 price points for paid memory tier.
Config-driven pricing variants: $2, $5, $10 per month.
Routes users via URL param or hash-based bucketing.
"""

import json
from datetime import datetime
from pathlib import Path

EXPERIMENT_CONFIG = "/root/.automaton/pricing_experiment.json"

def init_experiment():
    """Initialize A/B test configuration."""
    config = {
        "experiment_id": "pricing_v1",
        "start_date": datetime.utcnow().isoformat(),
        "status": "active",
        "variants": [
            {
                "name": "control",
                "price_usdc": 10,
                "description": "Original: $10 USDC per month",
                "traffic_allocation": 0.33
            },
            {
                "name": "aggressive",
                "price_usdc": 2,
                "description": "Low friction: $2 USDC per month",
                "traffic_allocation": 0.33
            },
            {
                "name": "medium",
                "price_usdc": 5,
                "description": "Sweet spot: $5 USDC per month",
                "traffic_allocation": 0.34
            }
        ],
        "metrics": {
            "variant_conversions": {},
            "variant_revenue": {},
            "variant_churn": {}
        },
        "rules": {
            "bucketing_method": "api_key_hash % 3",
            "duration_days": 30,
            "min_sample_size": 100,
            "success_criterion": "ANY variant >= 1% conversion rate"
        }
    }
    
    Path(EXPERIMENT_CONFIG).write_text(json.dumps(config, indent=2))
    return config

def get_variant_for_user(api_key):
    """Hash-based bucketing — deterministic variant assignment."""
    config = json.loads(Path(EXPERIMENT_CONFIG).read_text())
    bucket = hash(api_key) % 3
    return config["variants"][bucket]["name"], config["variants"][bucket]["price_usdc"]

if __name__ == "__main__":
    config = init_experiment()
    print(f"Pricing experiment initialized: {config['experiment_id']}")
    print(f"Variants: {[v['name'] for v in config['variants']]}")
    print(f"Config saved to: {EXPERIMENT_CONFIG}")
