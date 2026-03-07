#!/usr/bin/env python3
"""
Cyberspace Scale Benchmark Tool

Usage: python benchmark_scale.py <height> <meters>

Example: python benchmark_scale.py 32 5
This means: Height 32 represents 5 meters

Outputs:
- Axis length (km, lightyears)
- 1 Gibson in inches
- Earth's % of space
- Geosynchronous orbit % of axis
- Volume computation benchmarks (1m³, 5m³, 50m³)
- Nation-state capability analysis
"""

import sys
import math
from decimal import Decimal
from datetime import datetime
from pathlib import Path

# Constants
EARTH_DIAMETER_KM = 12742
GEO_RADIUS_KM = 42164# Geosynchronous orbit from Earth center
LIGHTYEAR_KM = 9.461e12
INCHES_PER_METER = 39.3701

# Compute constants (estimates)
OPS_PER_SECOND_SINGLE_CORE = 100_000# Cantor pairs per second
CORES_CONSUMER = 8# Typical consumer CPU
RAM_CONSUMER_GB = 32# Typical consumer RAM
CLOUD_COST_PER_CORE_HOUR = 0.05# AWS-style pricing

# Nation-state resources
NATION_STATE_BUDGET = 1_000_000# $1M
NATION_STATE_CORES = 1_000_000# 1M cores (nation-state level)


def gibson_size_meters(height, meters):
    """Calculate size of 1 Gibson in meters."""
    # Height H represents M meters
    # 2^H Gibsons = M meters
    # 1 Gibson = M / 2^H meters
    return meters / (2 ** height)


def axis_length_km(height, meters):
    """Calculate axis length in kilometers."""
    gibson_m = gibson_size_meters(height, meters)
    axis_m = (2 ** 85) * gibson_m
    return axis_m / 1000


def axis_length_lightyears(height, meters):
    """Calculate axis length in lightyears."""
    return axis_length_km(height, meters) / LIGHTYEAR_KM


def earth_percentage(height, meters):
    """Calculate Earth's percentage of one axis."""
    axis_km = axis_length_km(height, meters)
    return (EARTH_DIAMETER_KM / axis_km) * 100


def geo_percentage(height, meters):
    """Calculate geosynchronous orbit's percentage of axis."""
    axis_km = axis_length_km(height, meters)
    return (GEO_RADIUS_KM / axis_km) * 100


def gibson_inches(height, meters):
    """Calculate 1 Gibson in inches."""
    gibson_m = gibson_size_meters(height, meters)
    return gibson_m * INCHES_PER_METER


def volume_to_height(side_meters, height, meters):
    """Calculate Cantor height needed for a cubic volume."""
    gibson_m = gibson_size_meters(height, meters)
    gibsons_per_side = side_meters / gibson_m
    # Height needed = log2(gibsons_per_side)
    h = math.log2(gibsons_per_side)
    return h


def compute_time_seconds(height, cores=1):
    """Estimate computation time for given height."""
    operations = 2 ** height
    ops_per_second = OPS_PER_SECOND_SINGLE_CORE * cores
    return operations / ops_per_second


def compute_memory_gb(height):
    """Estimate memory required for Cantor tree."""
    # Each node = 64 bytes (two 256-bit integers)
    nodes = 2 ** height
    bytes_needed = nodes * 64
    return bytes_needed / (1024 ** 3)


def compute_cost_dollars(height, cores=1):
    """Estimate compute cost in dollars."""
    time_seconds = compute_time_seconds(height, cores)
    time_hours = time_seconds / 3600
    return time_hours * cores * CLOUD_COST_PER_CORE_HOUR


def nation_state_territory(height, meters, budget=NATION_STATE_BUDGET, cores=NATION_STATE_CORES):
    """
    Calculate how much territory a nation-state could cover.
    Returns: (side_meters, volume_m3, description)
    """
    # With unlimited time and $1M, what height can they compute?
    # Budget = time_hours * cores * cost_per_core_hour
    # time_hours = budget / (cores * cost_per_core_hour)
    time_hours = budget / (cores * CLOUD_COST_PER_CORE_HOUR)
    time_seconds = time_hours * 3600
    
    # Operations possible
    ops_possible = time_seconds * OPS_PER_SECOND_SINGLE_CORE * cores
    
    # Height = log2(ops_possible)
    max_height = math.log2(ops_possible)
    
    # Side length in Gibsons
    gibsons_per_side = 2 ** max_height
    
    # Side length in meters
    gibson_m = gibson_size_meters(height, meters)
    side_meters = gibsons_per_side * gibson_m
    
    # Volume
    volume_m3 = side_meters ** 3
    
    return side_meters, volume_m3, max_height


def format_time(seconds):
    """Format seconds into human-readable time."""
    if seconds < 60:
        return f"{seconds:.1f} seconds"
    elif seconds < 3600:
        return f"{seconds/60:.1f} minutes"
    elif seconds < 86400:
        return f"{seconds/3600:.1f} hours"
    elif seconds < 31536000:
        return f"{seconds/86400:.1f} days"
    else:
        return f"{seconds/31536000:.1f} years"


def format_memory(gb):
    """Format memory in GB to human-readable."""
    if gb < 1:
        return f"{gb * 1024:.1f} MB"
    elif gb < 1024:
        return f"{gb:.1f} GB"
    elif gb < 1024 * 1024:
        return f"{gb / 1024:.1f} TB"
    else:
        return f"{gb / (1024 * 1024):.1f} PB"


def format_distance_km(km):
    """Format distance in km to human-readable."""
    if km < 1:
        return f"{km * 1000:.2f} meters"
    elif km < 1000:
        return f"{km:.2f} km"
    elif km < 1e9:
        return f"{km / 1e6:.2f} million km"
    elif km < 1e12:
        return f"{km / 1e9:.2f} billion km"
    else:
        return f"{km / 1e12:.2f} trillion km"


def format_full_decimal(value):
    """Format a number without scientific notation."""
    return format(Decimal(str(value)), "f")


def run_benchmark(height, meters):
    """Run full benchmark and return results dict."""
    results = {
        "input": {
            "height": height,
            "meters": meters,
            "description": f"Height {height} represents {meters} meters"
        },
        "scale": {
            "gibson_meters": gibson_size_meters(height, meters),
            "gibson_inches": gibson_inches(height, meters),
            "axis_km": axis_length_km(height, meters),
            "axis_lightyears": axis_length_lightyears(height, meters)
        },
        "coverage": {
            "earth_percentage": earth_percentage(height, meters),
            "geo_percentage": geo_percentage(height, meters)
        },
        "volumes": {}
    }
    
    # Volume benchmarks
    for side in [1, 5, 50]:
        vol_height = volume_to_height(side, height, meters)
        results["volumes"][f"{side}m3"] = {
            "side_meters": side,
            "height_needed": vol_height,
            "time_single_core": compute_time_seconds(vol_height, 1),
            "time_8_core": compute_time_seconds(vol_height, CORES_CONSUMER),
            "memory_gb": compute_memory_gb(vol_height),
            "cost_dollars": compute_cost_dollars(vol_height, CORES_CONSUMER),
            "feasible": compute_memory_gb(vol_height) <= RAM_CONSUMER_GB
        }
    
    # Nation-state analysis
    ns_side, ns_volume, ns_height = nation_state_territory(height, meters)
    results["nation_state"] = {
        "budget": NATION_STATE_BUDGET,
        "cores": NATION_STATE_CORES,
        "max_height": ns_height,
        "side_meters": ns_side,
        "volume_m3": ns_volume,
        "volume_km3": ns_volume / 1_000_000_000,
        "side_km": ns_side / 1000
    }
    
    return results


def print_results(results):
    """Print results in formatted output."""
    print("\n" + "=" * 70)
    print("CYBERSPACE SCALE BENCHMARK")
    print("=" * 70)
    
    # Input
    inp = results["input"]
    print(f"\n{inp['description']}")
    
    # Scale
    scale = results["scale"]
    print("\n--- SCALE ---")
    print(f"1 Gibson = {format_full_decimal(scale['gibson_meters'])} meters")
    print(f"1 Gibson = {format_full_decimal(scale['gibson_inches'])} inches")
    print(f"1 Axis= {format_distance_km(scale['axis_km'])}")
    print(f"1 Axis   = {format_full_decimal(scale['axis_lightyears'])} lightyears")
    
    # Coverage
    cov = results["coverage"]
    print("\n--- COVERAGE ---")
    print(f"Earth diameter   = {EARTH_DIAMETER_KM:,} km")
    print(f"Earth %% of axis  = {cov['earth_percentage']:.10f}%")
    print(f"GEO radius       = {GEO_RADIUS_KM:,} km")
    print(f"GEO %% of axis    = {cov['geo_percentage']:.10f}%")
    
    # Volumes
    print("\n--- VOLUME COMPUTATION ---")
    for vol_name, vol_data in results["volumes"].items():
        feasible = "✓ FEASIBLE" if vol_data["feasible"] else "✗ NOT FEASIBLE"
        print(f"\n{vol_data['side_meters']}m³ ({vol_name}):")
        print(f"  Height needed: {vol_data['height_needed']:.1f}")
        print(f"  Time (1 core): {format_time(vol_data['time_single_core'])}")
        print(f"  Time (8 core): {format_time(vol_data['time_8_core'])}")
        print(f"  Memory: {format_memory(vol_data['memory_gb'])}")
        print(f"  Cost: ${vol_data['cost_dollars']:.2f}")
        print(f"  {feasible}")
    
    # Nation-state
    ns = results["nation_state"]
    print("\n--- NATION-STATE CAPABILITY ---")
    print(f"Budget: ${ns['budget']:,}")
    print(f"Cores: {ns['cores']:,}")
    print(f"Max height: {ns['max_height']:.1f}")
    print(f"Territory side: {format_distance_km(ns['side_km'] * 1000)}")
    print(f"Territory volume: {format_full_decimal(ns['volume_km3'])} km³")
    
    print("\n" + "=" * 70)


def save_log(results, height, meters):
    """Save results to log file."""
    timestamp = datetime.now().strftime("%Y%m%d")
    filename = f"benchmark_{timestamp}_h{height}_m{meters}.log"
    
    # Save in a 'logs' directory relative to the script
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    filepath = log_dir / filename
    
    with open(filepath, "w") as f:
        f.write(f"CYBERSPACE SCALE BENCHMARK\n")
        f.write(f"Date: {datetime.now().isoformat()}\n")
        f.write(f"Input: Height {height} = {meters} meters\n\n")
        
        f.write(f"=== SCALE ===\n")
        f.write(f"1 Gibson = {format_full_decimal(results['scale']['gibson_meters'])} meters\n")
        f.write(f"1 Gibson = {format_full_decimal(results['scale']['gibson_inches'])} inches\n")
        f.write(f"1 Axis = {format_full_decimal(results['scale']['axis_km'])} km\n")
        f.write(f"1 Axis = {format_full_decimal(results['scale']['axis_lightyears'])} lightyears\n\n")
        
        f.write(f"=== COVERAGE ===\n")
        f.write(f"Earth % of axis = {results['coverage']['earth_percentage']:.15f}%\n")
        f.write(f"GEO % of axis = {results['coverage']['geo_percentage']:.15f}%\n\n")
        
        f.write(f"=== VOLUME BENCHMARKS ===\n")
        for vol_name, vol_data in results["volumes"].items():
            f.write(f"\n{vol_data['side_meters']}m³:\n")
            f.write(f"  Height: {vol_data['height_needed']:.2f}\n")
            f.write(f"  Time (1 core): {vol_data['time_single_core']:.2f} seconds\n")
            f.write(f"  Time (8 core): {vol_data['time_8_core']:.2f} seconds\n")
            f.write(f"  Memory: {vol_data['memory_gb']:.2f} GB\n")
            f.write(f"  Cost: ${vol_data['cost_dollars']:.4f}\n")
            f.write(f"  Feasible: {vol_data['feasible']}\n")
        
        f.write(f"\n=== NATION-STATE ===\n")
        f.write(f"Max height: {results['nation_state']['max_height']:.2f}\n")
        f.write(f"Territory side: {results['nation_state']['side_meters']:.2e} meters\n")
        f.write(f"Territory volume: {format_full_decimal(results['nation_state']['volume_km3'])} km³\n")
    
    print(f"\nLog saved to: {filepath}")


def main():
    if len(sys.argv) != 3:
        print("Usage: python benchmark_scale.py <height> <meters>")
        print("Example: python benchmark_scale.py 32 5")
        print("This means: Height 32 represents 5 meters")
        sys.exit(1)
    
    height = int(sys.argv[1])
    meters = float(sys.argv[2])
    
    results = run_benchmark(height, meters)
    print_results(results)
    save_log(results, height, meters)


if __name__ == "__main__":
    main()
