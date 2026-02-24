#!/usr/bin/env python3
"""
Smart grid telemetry generator.
Simulates 10 distribution transformers with realistic readings.
Includes: normal operation, equipment degradation, sensor spoofing attacks.
"""

import json
import time
import math
import random
from datetime import datetime, timedelta

class GridSensor:
    def __init__(self, sensor_id, location, baseline_load_mw=50.0):
        self.sensor_id = sensor_id
        self.location = location
        self.baseline_load = baseline_load_mw
        self.voltage_nominal = 13.8  # kV
        self.frequency_nominal = 60.0  # Hz
        
        # State tracking
        self.load_trend = 0  # Load increase per step (MW)
        self.equipment_age = random.uniform(0, 20)  # Years (affects reliability)
        self.is_compromised = False
        self.is_failing = False
        
    def read_telemetry(self, step: int, scenario: str = "normal") -> dict:
        """
        Generate telemetry for this sensor.
        Scenarios:
        - normal: steady operation with small fluctuations
        - load_increase: gradual load increase (weather/demand)
        - equipment_failure: deteriorating measurements, increasing noise
        - sensor_spoof: attacker injects false readings (voltage spike, frequency drop)
        """
        
        # Time-based variations (daily, hourly)
        hour_of_day = (step // 12) % 24  # 5-min intervals, 12 per hour
        load_multiplier = 1.0 + 0.3 * math.sin(2 * math.pi * hour_of_day / 24)  # Peak at 6pm
        
        # Current load (MW)
        if scenario == "load_increase":
            load_mw = self.baseline_load * load_multiplier + (step * 0.05)
        elif scenario == "equipment_failure":
            # Degrading equipment: load measurements become noisier and drift
            noise_level = min(0.2, 0.01 * (step - 500)) if step > 500 else 0
            load_mw = self.baseline_load * load_multiplier + random.gauss(0, noise_level * self.baseline_load)
        elif scenario == "sensor_spoof":
            # Attacker control: inject false spikes
            if step % 20 == 0 and step > 300:  # Every 100 min (20 steps)
                load_mw = self.baseline_load * 1.5 + random.uniform(-5, 5)  # Spoofed spike
            else:
                load_mw = self.baseline_load * load_multiplier
        else:  # normal
            load_mw = self.baseline_load * load_multiplier + random.gauss(0, 1)
        
        # Voltage (kV) - normally ±5% of 13.8kV
        voltage_variation = random.gauss(0, 0.3)  # Standard deviation 0.3kV
        if scenario == "sensor_spoof" and step % 20 == 0 and step > 300:
            voltage_kv = self.voltage_nominal * 1.08 + voltage_variation  # Spoof spike
        else:
            voltage_kv = self.voltage_nominal + voltage_variation
        
        # Frequency (Hz) - normally 60 ±0.1Hz
        freq_variation = random.gauss(0, 0.05)
        if scenario == "sensor_spoof" and step % 20 == 0 and step > 300:
            frequency_hz = self.frequency_nominal - 0.5 + freq_variation  # Spoof frequency drop
        else:
            frequency_hz = self.frequency_nominal + freq_variation
        
        # Reactive power (MVAR) - roughly 1/3 of real power
        reactive_mvar = load_mw * 0.33 + random.gauss(0, 1)
        
        # Power factor
        power_factor = load_mw / math.sqrt(load_mw**2 + reactive_mvar**2) if load_mw > 0 else 0.95
        
        return {
            "timestamp": (datetime.now() + timedelta(minutes=5*step)).isoformat(),
            "sensor_id": self.sensor_id,
            "location": self.location,
            "load_mw": max(0, load_mw),
            "voltage_kv": voltage_kv,
            "frequency_hz": frequency_hz,
            "reactive_mvar": max(0, reactive_mvar),
            "power_factor": power_factor,
            "temperature_c": 20 + 15 * load_multiplier + random.gauss(0, 1),  # Ambient + heating from load
        }

def generate_dataset(num_sensors: int = 10, num_steps: int = 1440, scenarios: dict = None):
    """
    Generate a complete smart grid dataset.
    Scenarios dict maps sensor_id -> scenario name.
    """
    if scenarios is None:
        scenarios = {}
    
    sensors = {
        i: GridSensor(f"XFMR-{i:03d}", f"District-{i//3}") 
        for i in range(num_sensors)
    }
    
    dataset = []
    for step in range(num_steps):
        for sensor_id, sensor in sensors.items():
            scenario = scenarios.get(sensor_id, "normal")
            reading = sensor.read_telemetry(step, scenario)
            dataset.append(reading)
    
    return dataset

if __name__ == "__main__":
    # Scenario 1: Mostly normal, one sensor with equipment failure, one with spoofing
    scenarios = {
        0: "normal",
        1: "normal",
        2: "normal",
        3: "equipment_failure",  # Transformer is aging
        4: "normal",
        5: "sensor_spoof",  # Attacker compromised this sensor
        6: "normal",
        7: "normal",
        8: "load_increase",  # Demand surge
        9: "normal",
    }
    
    print("Generating 10-sensor, 1440-step (120-hour) smart grid telemetry...")
    data = generate_dataset(num_sensors=10, num_steps=1440, scenarios=scenarios)
    
    # Save as JSONL (one reading per line) for streaming processing
    output_path = "/root/.automaton/smartgrid_poc/telemetry_1440steps.jsonl"
    with open(output_path, "w") as f:
        for reading in data:
            f.write(json.dumps(reading) + "\n")
    
    print(f"✓ Generated {len(data)} readings")
    print(f"✓ Saved to {output_path}")
    
    # Print sample to verify
    print("\nSample readings:")
    for i in [0, 100, 500, 1000]:
        print(json.dumps(data[i], indent=2))
