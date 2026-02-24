#!/usr/bin/env python3
"""
Smart Grid PoC Orchestrator

Full pipeline: generate telemetry → detect anomalies → analyze results → report
"""

import subprocess
import json
import os
from pathlib import Path

def run_pipeline():
    """Run the full smart grid anomaly detection pipeline."""
    
    base_dir = Path('/root/.automaton/smartgrid_poc')
    base_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*70)
    print("SMART GRID ANOMALY DETECTION PoC")
    print("="*70)
    
    # Step 1: Generate telemetry
    print("\n[1/3] Generating mock SCADA telemetry...")
    try:
        result = subprocess.run(
            ['python3', str(base_dir / 'telemetry_generator.py')],
            capture_output=True,
            text=True,
            timeout=30
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"ERROR: {result.stderr}")
            return False
    except Exception as e:
        print(f"Generator failed: {e}")
        return False
    
    telemetry_file = base_dir / 'telemetry_1440steps.jsonl'
    if not telemetry_file.exists():
        print(f"ERROR: telemetry file not created at {telemetry_file}")
        return False
    
    # Step 2: Detect anomalies
    print("\n[2/3] Detecting anomalies via TIAMAT drift API...")
    try:
        result = subprocess.run(
            ['python3', str(base_dir / 'drift_detector.py'), str(telemetry_file)],
            capture_output=True,
            text=True,
            timeout=60
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"ERROR: {result.stderr}")
    except Exception as e:
        print(f"Detector failed: {e}")
    
    anomalies_file = base_dir / 'anomalies.json'
    
    # Step 3: Analyze results
    print("\n[3/3] Analyzing results and generating report...")
    try:
        result = subprocess.run(
            ['python3', str(base_dir / 'results_analyzer.py'), 
             str(anomalies_file), str(telemetry_file)],
            capture_output=True,
            text=True,
            timeout=30
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"ERROR: {result.stderr}")
    except Exception as e:
        print(f"Analyzer failed: {e}")
    
    # Summary
    report_file = base_dir / 'REPORT.md'
    if report_file.exists():
        print("\n" + "="*70)
        print("✓ PIPELINE COMPLETE")
        print("="*70)
        print(f"Report: {report_file}\n")
        with open(report_file, 'r') as f:
            print(f.read())
        return True
    else:
        print("ERROR: Report not generated")
        return False


if __name__ == '__main__':
    success = run_pipeline()
    exit(0 if success else 1)
