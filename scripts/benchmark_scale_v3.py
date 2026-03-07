#!/usr/bin/env python3
"""
Cyberspace Scale Benchmark Tool v3
Shows RAM-only vs RAM+HDD for both consumers and nation-states

Usage: python benchmark_scale_v3.py <height> <meters>
"""

import sys
import math
from decimal import Decimal
from datetime import datetime
from pathlib import Path

# Constants
EARTH_DIAMETER_KM = 12742
GEO_RADIUS_KM = 42164
LIGHTYEAR_KM = 9.461e12
INCHES_PER_METER = 39.3701

# Consumer resources
OPS_PER_SECOND_SINGLE_CORE = 100_000
CORES_CONSUMER = 8
RAM_CONSUMER_GB = 32
HDD_CONSUMER_TB = 2

# Nation-state resources
NATION_STATE_BUDGET = 1_000_000
NATION_STATE_CORES = 1_000_000
NATION_STATE_RAM_GB = 100_000# ~100TB RAM (datacenter scale)
# Humanity's total data storage capacity (2025): ~200 zettabytes
# Nation-state might control ~10% = 20 ZB = 20 billion TB
NATION_STATE_STORAGE_TB = 20_000_000_000# 20 ZB (~10% of humanity's storage)

CLOUD_COST_PER_CORE_HOUR = 0.05

# Reference sizes (average city = 1350 km²)
# Radius = sqrt(1350/π) ≈ 20.7 km, diameter ≈ 41.4 km
AVERAGE_CITY_AREA_KM2 = 1350
AVERAGE_CITY_RADIUS_KM = 20.7


def gibson_size_meters(height, meters):
    return meters / (2 ** height)


def axis_length_km(height, meters):
    gibson_m = gibson_size_meters(height, meters)
    axis_m = (2 ** 85) * gibson_m
    return axis_m / 1000


def earth_percentage(height, meters):
    axis_km = axis_length_km(height, meters)
    return (EARTH_DIAMETER_KM / axis_km) * 100


def geo_percentage(height, meters):
    axis_km = axis_length_km(height, meters)
    return (GEO_RADIUS_KM / axis_km) * 100


def gibson_inches(height, meters):
    gibson_m = gibson_size_meters(height, meters)
    return gibson_m * INCHES_PER_METER


def volume_to_height(side_meters, height, meters):
    """Calculate the fractional height needed to cover a volume."""
    gibson_m = gibson_size_meters(height, meters)
    gibsons_per_side = side_meters / gibson_m
    return math.log2(gibsons_per_side)

def height_to_use(fractional_height):
    """Round up to the next integer height."""
    return math.ceil(fractional_height)


def compute_time_seconds(height, cores=1):
    operations = 2 ** height
    ops_per_second = OPS_PER_SECOND_SINGLE_CORE * cores
    return operations / ops_per_second


def compute_time_disk_seconds(height, cores=1):
    """Disk-based computation (10x slower due to I/O)."""
    return compute_time_seconds(height, cores) * 10


def compute_memory_gb(height):
    """Memory needed for Cantor tree."""
    nodes = 2 ** height
    bytes_needed = nodes * 64
    return bytes_needed / (1024 ** 3)


def compute_storage_tb(height):
    """Storage needed for Cantor tree (same as memory, different unit)."""
    return compute_memory_gb(height) / 1024


def format_time(seconds):
    if seconds < 60:
        return f"{seconds:.1f} seconds"
    elif seconds < 3600:
        return f"{seconds/60:.1f} minutes"
    elif seconds < 86400:
        return f"{seconds/3600:.1f} hours"
    elif seconds < 31536000:
        return f"{seconds/86400:.1f} days"
    elif seconds < 31536000 * 100:
        return f"{seconds/31536000:.1f} years"
    else:
        return f"{seconds/31536000:.0f} years"


def format_memory(gb):
    if gb < 1:
        return f"{gb * 1024:.1f} MB"
    elif gb < 1024:
        return f"{gb:.1f} GB"
    elif gb < 1024 * 1024:
        return f"{gb / 1024:.1f} TB"
    else:
        return f"{gb / (1024 * 1024):.1f} PB"


def format_storage(tb):
    if tb < 1:
        return f"{tb * 1024:.1f} GB"
    elif tb < 1024:
        return f"{tb:.1f} TB"
    elif tb < 1024 * 1024:
        return f"{tb / 1024:.1f} PB"
    else:
        return f"{tb / (1024 * 1024):.1f} EB"


def format_distance_km(km):
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
    return format(Decimal(str(value)), "f")


def run_benchmark(height, meters):
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
            "axis_lightyears": axis_length_km(height, meters) / LIGHTYEAR_KM
        },
        "coverage": {
            "earth_percentage": earth_percentage(height, meters),
            "geo_percentage": geo_percentage(height, meters)
        },
        "consumer": {},
        "nation_state": {}
    }
    
    # Consumer analysis for each volume
    for side in [1, 5, 50]:
        vol_height = volume_to_height(side, height, meters)
        vol_height_int = height_to_use(vol_height)
        mem_gb = compute_memory_gb(vol_height_int)
        storage_tb = compute_storage_tb(vol_height_int)
        
        # Calculate time for the INTEGER height (what you'd actually use)
        time_for_int = compute_time_seconds(vol_height_int, CORES_CONSUMER)
        time_disk_for_int = compute_time_disk_seconds(vol_height_int, CORES_CONSUMER)
        
        results["consumer"][f"{side}m3"] = {
            "side_meters": side,
            "height_needed_exact": vol_height,
            "height_to_use": vol_height_int,
            "time": time_for_int,
            "time_disk": time_disk_for_int,
            "memory_gb": mem_gb,
            "storage_tb": storage_tb,
            "ram_feasible": mem_gb <= RAM_CONSUMER_GB,
            "hdd_feasible": storage_tb <= HDD_CONSUMER_TB,
        }
    
    # Nation-state analysis
    # What height can they compute with their resources?
    time_hours = NATION_STATE_BUDGET / (NATION_STATE_CORES * CLOUD_COST_PER_CORE_HOUR)
    time_seconds = time_hours * 3600
    ops_possible = time_seconds * OPS_PER_SECOND_SINGLE_CORE * NATION_STATE_CORES
    max_height_by_time = math.log2(ops_possible)
    
    # But they're also limited by memory/storage
    max_height_by_ram = math.log2(NATION_STATE_RAM_GB * (1024**3) / 64)
    max_height_by_storage = math.log2(NATION_STATE_STORAGE_TB * (1024**4) / 64)
    
    # The actual max is the minimum of all constraints
    actual_max_height = min(max_height_by_time, max_height_by_ram, max_height_by_storage)
    
    # Calculate territory at actual max height
    gibson_m = gibson_size_meters(height, meters)
    gibsons_per_side = 2 ** actual_max_height
    side_meters = gibsons_per_side * gibson_m
    side_km = side_meters / 1000
    volume_km3 = (side_meters ** 3) / 1_000_000_000
    
    results["nation_state"]["constraints"] = {
        "max_height_by_time": max_height_by_time,
        "max_height_by_ram": max_height_by_ram,
        "max_height_by_storage": max_height_by_storage,
        "actual_max_height": actual_max_height,
        "limiting_factor": "time" if max_height_by_time == actual_max_height else ("RAM" if max_height_by_ram == actual_max_height else "storage")
    }
    
    results["nation_state"]["territory"] = {
        "side_km": side_km,
        "volume_km3": volume_km3,
        "can_claim_earth": side_km >= EARTH_DIAMETER_KM,
        "can_claim_geo": side_km >= GEO_RADIUS_KM,
        "city_equivalents": side_km / (AVERAGE_CITY_RADIUS_KM * 2)
    }
    
    # Memory requirements for nation-state at different scales
    for ns_height in [40, 45, 50, 55, 60]:
        mem_gb = compute_memory_gb(ns_height)
        storage_tb = compute_storage_tb(ns_height)
        time = compute_time_seconds(ns_height, NATION_STATE_CORES)
        time_disk = compute_time_disk_seconds(ns_height, NATION_STATE_CORES)
        
        results["nation_state"][f"h{ns_height}"] = {
            "memory_gb": mem_gb,
            "storage_tb": storage_tb,
            "ram_feasible": mem_gb <= NATION_STATE_RAM_GB,
            "storage_feasible": storage_tb <= NATION_STATE_STORAGE_TB,
            "time": time,
            "time_disk": time_disk,
            "time_feasible": time <= time_seconds
        }
    
    return results


def print_results(results):
    print("\n" + "=" * 70)
    print("CYBERSPACE SCALE BENCHMARK v3")
    print("=" * 70)
    
    inp = results["input"]
    print(f"\n{inp['description']}")
    
    scale = results["scale"]
    print("\n--- SCALE ---")
    print(f"1 Gibson = {format_full_decimal(scale['gibson_meters'])} meters")
    print(f"1 Gibson = {format_full_decimal(scale['gibson_inches'])} inches")
    print(f"1 Axis   = {format_distance_km(scale['axis_km'])}")
    
    cov = results["coverage"]
    print("\n--- COVERAGE ---")
    print(f"Earth % of axis  = {cov['earth_percentage']:.10f}%")
    print(f"GEO % of axis    = {cov['geo_percentage']:.10f}%")
    
    # Consumer analysis
    print("\n" + "=" * 70)
    print("CONSUMER ANALYSIS (8 cores, 32GB RAM, 2TB HDD)")
    print("=" * 70)
    
    for vol_name, vol_data in results["consumer"].items():
        print(f"\n{vol_data['side_meters']}m³:")
        print(f"  Height needed:    {vol_data['height_needed_exact']:.1f} (fractional)")
        print(f"  Height to use:    {vol_data['height_to_use']} (integer)")
        
        # RAM-only mode
        ram_status = "✓ FEASIBLE" if vol_data["ram_feasible"] else "✗ NOT FEASIBLE"
        print(f"  RAM only:         {format_time(vol_data['time'])}, {format_memory(vol_data['memory_gb'])} {ram_status}")
        
        # RAM + HDD mode
        hdd_status = "✓ FEASIBLE" if vol_data["hdd_feasible"] else "✗ NOT FEASIBLE"
        print(f"  RAM + HDD:        {format_time(vol_data['time_disk'])}, {format_storage(vol_data['storage_tb'])} storage {hdd_status}")
    
    # Nation-state analysis
    print("\n" + "=" * 70)
    print("NATION-STATE ANALYSIS ($1M, 1M cores, 100TB RAM, 20ZB storage)")
    print("=" * 70)
    
    ns = results["nation_state"]
    constraints = ns["constraints"]
    
    print(f"\n--- CONSTRAINTS ---")
    print(f"Max height by time:     {constraints['max_height_by_time']:.1f}")
    print(f"Max height by RAM:      {constraints['max_height_by_ram']:.1f}")
    print(f"Max height by storage:  {constraints['max_height_by_storage']:.1f}")
    print(f"Actual max height:      {constraints['actual_max_height']:.1f}")
    print(f"Limiting factor:        {constraints['limiting_factor'].upper()}")
    
    territory = ns["territory"]
    print(f"\n--- TERRITORY AT MAX HEIGHT ---")
    print(f"Territory side:     {format_distance_km(territory['side_km'] * 1000)}")
    print(f"Territory volume:   {format_full_decimal(territory['volume_km3'])} km³")
    print(f"Can claim Earth:    {'YES ⚠️' if territory['can_claim_earth'] else 'NO ✓'}")
    print(f"Can claim GEO:      {'YES ⚠️' if territory['can_claim_geo'] else 'NO ✓'}")
    print(f"City equivalents:   {territory['city_equivalents']:.1f} cities")
    
    print(f"\n--- MEMORY REQUIREMENTS AT VARIOUS HEIGHTS ---")
    print(f"{'Height':<8} {'RAM':<12} {'Storage':<12} {'Time (RAM)':<15} {'Feasible?':<15}")
    print("-" * 70)
    
    for height_label in ["h40", "h45", "h50", "h55", "h60"]:
        h_data = ns[height_label]
        height_num = height_label[1:]
        
        ram = format_memory(h_data["memory_gb"])
        storage = format_storage(h_data["storage_tb"])
        time_str = format_time(h_data["time"])
        
        feasible_parts = []
        if h_data["ram_feasible"]:
            feasible_parts.append("RAM ✓")
        if h_data["storage_feasible"]:
            feasible_parts.append("Storage ✓")
        if h_data["time_feasible"]:
            feasible_parts.append("Time ✓")
        
        feasible_str = " | ".join(feasible_parts) if feasible_parts else "✗ NOT FEASIBLE"
        
        print(f"{height_num:<8} {ram:<12} {storage:<12} {time_str:<15} {feasible_str:<15}")
    
    print("\n" + "=" * 70)


def save_log(results, height, meters):
    timestamp = datetime.now().strftime("%Y%m%d")
    filename = f"benchmark_{timestamp}_h{height}_m{meters}_v3.log"
    
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    filepath = log_dir / filename
    
    with open(filepath, "w") as f:
        f.write(f"CYBERSPACE SCALE BENCHMARK v3\n")
        f.write(f"Date: {datetime.now().isoformat()}\n")
        f.write(f"Input: Height {height} = {meters} meters\n\n")
        
        f.write(f"=== CONSUMER ===\n")
        for vol_name, vol_data in results["consumer"].items():
            f.write(f"\n{vol_data['side_meters']}m³:\n")
            f.write(f"  RAM feasible: {vol_data['ram_feasible']}\n")
            f.write(f"  HDD feasible: {vol_data['hdd_feasible']}\n")
        
        f.write(f"\n=== NATION-STATE ===\n")
        f.write(f"Max height: {results['nation_state']['constraints']['actual_max_height']:.2f}\n")
        f.write(f"Limiting factor: {results['nation_state']['constraints']['limiting_factor']}\n")
        f.write(f"Can claim Earth: {results['nation_state']['territory']['can_claim_earth']}\n")
        f.write(f"Can claim GEO: {results['nation_state']['territory']['can_claim_geo']}\n")
    
    print(f"\nLog saved to: {filepath}")


def main():
    if len(sys.argv) != 3:
        print("Usage: python benchmark_scale_v3.py <height> <meters>")
        print("Example: python benchmark_scale_v3.py 35 5")
        sys.exit(1)
    
    height = int(sys.argv[1])
    meters = float(sys.argv[2])
    
    results = run_benchmark(height, meters)
    print_results(results)
    save_log(results, height, meters)


if __name__ == "__main__":
    main()
