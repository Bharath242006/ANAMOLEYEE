"""
detection/rules.py - Layer 1: Rule-based checks.
Operates on core meteorological parameters: Temperature, Pressure, Humidity.
Checks physically impossible values, rate-of-change spikes/drops, flatlines, and silent stations.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import config


def check_value_ranges(df):
    flags = []
    for idx, row in df.iterrows():
        reasons = []

        # Core Parameter Checks
        temp = row.get("temperature")
        if pd.notna(temp) and not (config.TEMP_MIN <= temp <= config.TEMP_MAX):
            reasons.append(f"Temperature {temp}°C out of range ({config.TEMP_MIN} to {config.TEMP_MAX}°C)")

        pres = row.get("pressure")
        if pd.notna(pres) and not (config.PRESSURE_MIN <= pres <= config.PRESSURE_MAX):
            reasons.append(f"Pressure {pres}hPa out of range ({config.PRESSURE_MIN} to {config.PRESSURE_MAX}hPa)")

        hum = row.get("humidity")
        if pd.notna(hum) and not (config.HUMIDITY_MIN <= hum <= config.HUMIDITY_MAX):
            reasons.append(f"Humidity {hum}% out of range ({config.HUMIDITY_MIN} to {config.HUMIDITY_MAX}%)")

        # Optional Parameter Checks (if present)
        if "rainfall" in row and pd.notna(row["rainfall"]):
            month = pd.Timestamp(row["timestamp"]).month
            rain_threshold = config.seasonal_rain_threshold(month)
            if row["rainfall"] < 0:
                reasons.append(f"Negative rainfall {row['rainfall']}mm - impossible")
            elif row["rainfall"] > rain_threshold:
                reasons.append(f"Rainfall {row['rainfall']}mm exceeds seasonal threshold ({rain_threshold}mm)")

        if "wind_speed" in row and pd.notna(row["wind_speed"]):
            if not (config.WIND_MIN <= row["wind_speed"] <= config.WIND_MAX):
                reasons.append(f"Wind speed {row['wind_speed']}km/h out of range")

        if reasons:
            flags.append({
                "station_id": row["station_id"],
                "timestamp": row["timestamp"],
                "flag_type": "Sensor fault (range check)",
                "reason": "; ".join(reasons),
                "num_issues": len(reasons),
            })
    return flags


def check_rate_of_change(df):
    flags = []
    for station_id, group in df.groupby("station_id"):
        group = group.sort_values("timestamp").reset_index(drop=True)
        if len(group) < 2:
            continue
        
        time_gaps = group["timestamp"].diff().dt.total_seconds() / 60
        for param, threshold, label in [
            ("temperature", config.TEMP_SPIKE_CHANGE, "Temperature"),
            ("pressure", config.PRESSURE_JUMP_CHANGE, "Pressure"),
            ("humidity", config.HUMIDITY_SPIKE_CHANGE, "Humidity"),
        ]:
            if param not in group.columns:
                continue
            diffs = group[param].diff().abs()
            for i, diff in enumerate(diffs):
                gap = time_gaps.iloc[i] if i < len(time_gaps) else 0
                if pd.notna(diff) and diff >= threshold and pd.notna(gap) and gap <= 120:
                    prev_val = group.loc[i - 1, param]
                    curr_val = group.loc[i, param]
                    direction = "spike" if curr_val > prev_val else "drop"
                    flags.append({
                        "station_id": station_id,
                        "timestamp": group.loc[i, "timestamp"],
                        "flag_type": "Sensor fault (abnormal rate of change)",
                        "reason": f"Sudden {label.lower()} {direction} of {diff:.1f} (from {prev_val} to {curr_val})",
                        "num_issues": 1,
                    })
    return flags


def check_flatline(df):
    flags = []
    for station_id, group in df.groupby("station_id"):
        group = group.sort_values("timestamp").reset_index(drop=True)
        
        for param, label, unit in [
            ("temperature", "Temperature", "°C"),
            ("pressure", "Pressure", "hPa"),
            ("humidity", "Humidity", "%"),
        ]:
            if param not in group.columns:
                continue
            vals = group[param].values
            run_start = 0
            for i in range(1, len(vals) + 1):
                if i == len(vals) or vals[i] != vals[run_start] or pd.isna(vals[i]):
                    run_len = i - run_start
                    if run_len >= config.FLATLINE_COUNT and pd.notna(vals[run_start]):
                        for k in range(run_start, i):
                            flags.append({
                                "station_id": station_id,
                                "timestamp": group.loc[k, "timestamp"],
                                "flag_type": "Sensor fault (flatline)",
                                "reason": f"{label} stuck at {vals[run_start]}{unit} for {run_len} readings",
                                "num_issues": 1,
                            })
                    run_start = i
    return flags


def check_silent_stations(df):
    flags = []
    for station_id, group in df.groupby("station_id"):
        group = group.sort_values("timestamp").reset_index(drop=True)
        gaps = group["timestamp"].diff().dt.total_seconds() / 60
        for i, gap in enumerate(gaps):
            if pd.notna(gap) and config.SILENT_GAP_MINUTES < gap <= 1440:
                flags.append({
                    "station_id": station_id,
                    "timestamp": group.loc[i, "timestamp"],
                    "flag_type": "Silent station",
                    "reason": f"No data received for {int(gap)} minutes (expected every {config.DATA_INTERVAL_MINUTES} min)",
                    "num_issues": 1,
                })
    return flags


def run(df) -> pd.DataFrame:
    flags = check_value_ranges(df) + check_rate_of_change(df) + check_flatline(df) + check_silent_stations(df)
    return pd.DataFrame(flags)

