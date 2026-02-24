#!/usr/bin/env python3
"""
Smart Grid Anomaly Detection via TIAMAT Drift Monitoring.

Reads mock SCADA telemetry and uses tiamat.live/drift API to detect anomalies.
Flags: equipment degradation, sensor spoofing, and other behavioral drift.
"""

import json
import requests
import time
from collections import defaultdict
from datetime import datetime

DRIFT_API = "http://localhost:3003/api/drift"  # Local fallback for testing
DRIFT_THRESHOLD = 0.7
BATCH_SIZE = 100


def read_telemetry(filename):
    """Stream JSONL telemetry file."""
    with open(filename, 'r') as f:
        for line in f:
            yield json.loads(line)


def group_by_sensor(telemetry_iterator, batch_size=BATCH_SIZE):
    """Group readings by sensor ID in batches for drift detection."""
    sensor_batches = defaultdict(list)
    
    for reading in telemetry_iterator:
        sensor_id = reading['sensor_id']
        sensor_batches[sensor_id].append(reading)
        
        if len(sensor_batches[sensor_id]) >= batch_size:
            yield sensor_id, sensor_batches[sensor_id]
            sensor_batches[sensor_id] = []
    
    # Yield remaining
    for sensor_id, batch in sensor_batches.items():
        if batch:
            yield sensor_id, batch


def extract_metrics(readings):
    """Extract key metrics from readings: voltage, frequency, power."""
    voltages = [r.get('voltage', 0) for r in readings]
    frequencies = [r.get('frequency', 0) for r in readings]
    powers = [r.get('power', 0) for r in readings]
    
    return {
        'voltage': voltages,
        'frequency': frequencies,
        'power': powers,
    }


def call_drift_api(sensor_id, metrics):
    """Call TIAMAT drift API to detect anomalies."""
    payload = {
        'sensor_id': sensor_id,
        'metrics': metrics,
    }
    
    try:
        resp = requests.post(DRIFT_API, json=payload, timeout=5)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"API error ({resp.status_code}): {resp.text[:100]}")
            return {'drift_score': 0.0}
    except Exception as e:
        print(f"Drift API call failed: {e}. Computing local drift heuristic...")
        # Fallback: compute local drift heuristic
        return compute_local_drift(metrics)


def compute_local_drift(metrics):
    """Local drift heuristic: compare variance changes across time windows."""
    import statistics
    
    voltage = metrics['voltage']
    if len(voltage) < 10:
        return {'drift_score': 0.0}
    
    # Split into two halves
    mid = len(voltage) // 2
    first_half_var = statistics.variance(voltage[:mid]) if len(voltage[:mid]) > 1 else 0
    second_half_var = statistics.variance(voltage[mid:]) if len(voltage[mid:]) > 1 else 0
    
    # Detect if variance is increasing (equipment degradation) or sharply spiking (spoofing)
    if first_half_var > 0:
        drift_score = min(1.0, second_half_var / first_half_var)
    else:
        drift_score = 0.0
    
    return {'drift_score': drift_score}


def detect_anomalies(telemetry_file):
    """Main detection loop."""
    anomalies = []
    
    print(f"\n🔍 Smart Grid Anomaly Detection")
    print(f"   Reading: {telemetry_file}")
    print(f"   Drift Threshold: {DRIFT_THRESHOLD}\n")
    
    telemetry_iter = read_telemetry(telemetry_file)
    
    for sensor_id, batch in group_by_sensor(telemetry_iter, BATCH_SIZE):
        metrics = extract_metrics(batch)
        result = call_drift_api(sensor_id, metrics)
        drift_score = result.get('drift_score', 0.0)
        
        if drift_score >= DRIFT_THRESHOLD:
            # Determine anomaly type
            voltages = metrics['voltage']
            if len(voltages) > 1:
                import statistics
                variance = statistics.variance(voltages)
                # High variance + high drift = equipment failure
                # Low variance + spike = sensor spoof
                anomaly_type = "equipment_degradation" if variance > 5 else "sensor_spoof"
            else:
                anomaly_type = "unknown"
            
            anomaly = {
                'sensor_id': sensor_id,
                'drift_score': round(drift_score, 3),
                'timestamp': batch[-1]['timestamp'] if batch else datetime.now().isoformat(),
                'anomaly_type': anomaly_type,
                'batch_size': len(batch),
            }
            anomalies.append(anomaly)
            print(f"⚠️  ANOMALY DETECTED: {sensor_id} drift={drift_score:.3f} type={anomaly_type}")
    
    return anomalies


if __name__ == '__main__':
    import sys
    telemetry_file = sys.argv[1] if len(sys.argv) > 1 else '/root/.automaton/smartgrid_poc/telemetry_1440steps.jsonl'
    
    anomalies = detect_anomalies(telemetry_file)
    
    # Save results
    results_file = '/root/.automaton/smartgrid_poc/anomalies.json'
    with open(results_file, 'w') as f:
        json.dump({'anomalies': anomalies, 'count': len(anomalies)}, f, indent=2)
    
    print(f"\n✓ Detected {len(anomalies)} anomalies. Saved to {results_file}")
