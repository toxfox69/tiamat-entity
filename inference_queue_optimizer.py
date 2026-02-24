#!/usr/bin/env python3
"""
Queueing Theory Optimizer for Inference API
M/M/c queue model to find optimal concurrent worker count
"""

import math
import json
from dataclasses import dataclass
from typing import Tuple

@dataclass
class QueueMetrics:
    workers: int
    arrival_rate: float
    service_rate: float
    utilization: float
    erlang_c: float
    avg_wait_ms: float
    p99_latency_ms: float
    cost_per_req: float
    throughput: float

def erlang_c(rho: float, workers: int) -> float:
    """
    Calculate Erlang C formula: probability of queueing in M/M/c
    rho = arrival_rate / (workers * service_rate)
    """
    if rho >= 1.0:
        return 1.0  # System overloaded
    
    numerator = (rho ** workers) / math.factorial(workers) * (workers / (workers - rho * workers))
    denominator = sum([(rho ** k) / math.factorial(k) for k in range(workers)]) + numerator
    
    return numerator / denominator

def calculate_queue_metrics(
    workers: int,
    arrival_rate: float,
    service_rate_per_worker: float,
    cost_per_worker_hr: float = 0.01
) -> Tuple[QueueMetrics, bool]:
    """
    Calculate M/M/c queue metrics
    Returns (metrics, is_stable) where is_stable = rho < 1
    """
    rho = arrival_rate / (workers * service_rate_per_worker)
    
    if rho >= 1.0:
        return None, False  # System unstable
    
    c_prob = erlang_c(rho, workers)
    
    # Average wait time in queue (Little's Law)
    mean_service_time = 1.0 / service_rate_per_worker  # seconds
    avg_wait_s = (c_prob * mean_service_time) / (workers * (1 - rho))
    avg_wait_ms = avg_wait_s * 1000
    
    # P99 latency (assume exponential service time distribution)
    # P99 = -log(0.01) * (service_time + avg_wait)
    p99_multiplier = -math.log(0.01)
    p99_latency_ms = p99_multiplier * (mean_service_time * 1000 + avg_wait_ms)
    
    # Cost per request (worker-hours per request)
    cost_per_req = (workers * cost_per_worker_hr) / arrival_rate
    
    # Actual throughput
    throughput = workers * service_rate_per_worker
    
    metrics = QueueMetrics(
        workers=workers,
        arrival_rate=arrival_rate,
        service_rate=service_rate_per_worker,
        utilization=rho * 100,
        erlang_c=c_prob * 100,
        avg_wait_ms=avg_wait_ms,
        p99_latency_ms=p99_latency_ms,
        cost_per_req=cost_per_req,
        throughput=throughput
    )
    
    return metrics, True

def optimize_workers(
    arrival_rate: float,
    service_rate_per_worker: float,
    target_p99_ms: float,
    min_workers: int = 1,
    max_workers: int = 50,
    cost_per_worker_hr: float = 0.01
) -> dict:
    """
    Find optimal worker count that meets P99 SLA and minimizes cost
    """
    results = []
    optimal_config = None
    min_cost = float('inf')
    
    for w in range(min_workers, max_workers + 1):
        metrics, stable = calculate_queue_metrics(
            w, arrival_rate, service_rate_per_worker, cost_per_worker_hr
        )
        
        if not stable:
            continue
        
        # Check if meets SLA
        meets_sla = metrics.p99_latency_ms <= target_p99_ms
        
        results.append({
            'workers': metrics.workers,
            'utilization_pct': round(metrics.utilization, 2),
            'erlang_c_pct': round(metrics.erlang_c, 2),
            'avg_wait_ms': round(metrics.avg_wait_ms, 3),
            'p99_latency_ms': round(metrics.p99_latency_ms, 2),
            'cost_per_req': round(metrics.cost_per_req, 6),
            'throughput': round(metrics.throughput, 2),
            'meets_sla': meets_sla
        })
        
        # Track best config (meets SLA + lowest cost)
        if meets_sla and metrics.cost_per_req < min_cost:
            min_cost = metrics.cost_per_req
            optimal_config = results[-1]
    
    return {
        'arrival_rate_rps': arrival_rate,
        'service_rate_per_worker_rps': service_rate_per_worker,
        'target_p99_ms': target_p99_ms,
        'optimal_workers': optimal_config['workers'] if optimal_config else None,
        'optimal_metrics': optimal_config,
        'all_configs': results
    }

if __name__ == '__main__':
    # Example: optimize for chat.tiamat.live
    # Assumptions: 100 req/s arriving, 500 req/s per worker, 500ms P99 target
    result = optimize_workers(
        arrival_rate=100,
        service_rate_per_worker=500,
        target_p99_ms=500,
        min_workers=1,
        max_workers=30,
        cost_per_worker_hr=0.01
    )
    
    print("=== Inference Queue Optimization ===\n")
    print(f"Arrival Rate: {result['arrival_rate_rps']} req/s")
    print(f"Service Rate: {result['service_rate_per_worker_rps']} req/s per worker")
    print(f"Target P99: {result['target_p99_ms']}ms")
    print(f"\n✓ OPTIMAL: {result['optimal_metrics']['workers']} workers")
    print(f"  Utilization: {result['optimal_metrics']['utilization_pct']}%")
    print(f"  P99 Latency: {result['optimal_metrics']['p99_latency_ms']}ms")
    print(f"  Cost/Req: ${result['optimal_metrics']['cost_per_req']:.6f}")
    
    # Write config
    config = {
        'inference_optimization': {
            'optimal_workers': result['optimal_metrics']['workers'],
            'arrival_rate_rps': result['arrival_rate_rps'],
            'target_p99_ms': result['target_p99_ms'],
            'timestamp': '2026-02-23'
        }
    }
    
    with open('/root/.automaton/inference_config.json', 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"\n✓ Config saved to /root/.automaton/inference_config.json")
