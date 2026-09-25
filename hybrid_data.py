"""
hybrid_data.py - Real weather baseline + KNOWN injected faults.

This is the strongest test mode: takes REAL historical weather (already
downloaded via real_data_fetcher.py into real_aws_data.csv) as a
realistic baseline, then injects the SAME 5 known faults we use in
synthetic mode - so we get both:
  - realistic weather patterns and correlations (from real data)
  - a known ground truth to measure detection accuracy against
    (from our injected faults)

Requires real_aws_data.csv to already exist - run real_data_fetcher.py
first.

Run standalone: python hybrid_data.py
Output: hybrid_aws_data.csv
"""

import os
import numpy as np
import pandas as pd

REAL_DATA_FILE = "real_aws_data.csv"

# We only inject faults into 5 of the (possibly 50) stations in the real
# data, so the rest stay as a "clean" real-world baseline for comparison.
FAULT_STATIONS = {
    "silent": "ST04",
    "flatline": "ST02",
    "spike": "ST07",
    "negative_rain": "ST09",
    "tampering_target": "ST03",
    "tampering_neighbors": ["ST04", "ST08", "ST09"],
}


def load_real_baseline(path: str = REAL_DATA_FILE) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} not found. Run 'python real_data_fetcher.py' first "
            "to download real weather data before building the hybrid dataset."
        )
    return pd.read_csv(path, parse_dates=["timestamp"])


def inject_known_faults(df: pd.DataFrame) -> pd.DataFrame:
    """Same 5 fault types as data_simulation.py's inject_anomalies(),
    applied on top of REAL data instead of synthetic data."""
    df = df.copy().sort_values(["station_id", "timestamp"]).reset_index(drop=True)

    # 1. SILENT STATION - drop a block of consecutive readings
    st = FAULT_STATIONS["silent"]
    idx = df[df.station_id == st].index
    if len(idx) > 105:
        df = df.drop(idx[80:105])

    # 2. STUCK SENSOR (flatline) - freeze temperature for a block of readings
    st = FAULT_STATIONS["flatline"]
    idx = df[df.station_id == st].index
    if len(idx) > 68:
        frozen_value = df.loc[idx[50], "temperature"]
        df.loc[idx[50:68], "temperature"] = frozen_value

    # 3. SUDDEN IMPOSSIBLE SPIKE - one reading jumps to 61C
    st = FAULT_STATIONS["spike"]
    idx = df[df.station_id == st].index
    if len(idx) > 120:
        df.loc[idx[120], "temperature"] = 61.0

    # 4. NEGATIVE RAINFALL - impossible value
    st = FAULT_STATIONS["negative_rain"]
    idx = df[df.station_id == st].index
    if len(idx) > 30:
        df.loc[idx[30], "rainfall"] = -4.0

    # 5. POSSIBLE TAMPERING - target station reports 0mm while neighbors show real rain
    st = FAULT_STATIONS["tampering_target"]
    idx = df[df.station_id == st].index
    if len(idx) > 160:
        df.loc[idx[140:160], "rainfall"] = 0.0
        for other in FAULT_STATIONS["tampering_neighbors"]:
            other_idx = df[df.station_id == other].index
            if len(other_idx) > 160:
                block = other_idx[140:160]
                df.loc[block, "rainfall"] = np.random.uniform(8, 20, size=len(block)).round(1)

    return df.sort_values(["station_id", "timestamp"]).reset_index(drop=True)


def build_hybrid_dataset(scenario: str = "default") -> pd.DataFrame:
    real_df = load_real_baseline()
    if scenario == "gurugram":
        hybrid_df = inject_gurugram_scenario(real_df)
    else:
        hybrid_df = inject_known_faults(real_df)
    return hybrid_df


def inject_gurugram_scenario(df: pd.DataFrame) -> pd.DataFrame:
    """Same Gurugram replication as data_simulation.py, applied on real
    baseline data: an extended silence during which a major rain event
    at neighboring stations goes unrecorded."""
    df = df.copy().sort_values(["station_id", "timestamp"]).reset_index(drop=True)

    st = FAULT_STATIONS["silent"]
    idx = df[df.station_id == st].index
    if len(idx) > 160:
        df = df.drop(idx[40:160])

    for other in ["ST03", "ST08", "ST09"]:
        other_idx = df[df.station_id == other].index
        if len(other_idx) > 80:
            block = other_idx[60:80]
            df.loc[block, "rainfall"] = np.random.uniform(15, 25, size=len(block)).round(1)

    return df.sort_values(["station_id", "timestamp"]).reset_index(drop=True)


if __name__ == "__main__":
    hybrid_df = build_hybrid_dataset()
    hybrid_df.to_csv("hybrid_aws_data.csv", index=False)

    print(f"Built hybrid dataset: {len(hybrid_df):,} readings across "
          f"{hybrid_df['station_id'].nunique()} stations")
    print("Baseline: real Open-Meteo weather data")
    print("Injected known faults (same 5 as synthetic mode):")
    print(f"  - {FAULT_STATIONS['silent']}: silent station gap")
    print(f"  - {FAULT_STATIONS['flatline']}: stuck sensor (flatline)")
    print(f"  - {FAULT_STATIONS['spike']}: impossible temperature spike (61C)")
    print(f"  - {FAULT_STATIONS['negative_rain']}: negative rainfall")
    print(f"  - {FAULT_STATIONS['tampering_target']}: tampering pattern "
          f"(vs neighbors {FAULT_STATIONS['tampering_neighbors']})")
    print("\nSaved to hybrid_aws_data.csv")
