"""
detection/neighbor.py - Layer 2: Spatial cross-checking.
Compares each station against its nearest neighbors across core meteorological
parameters: Temperature, Pressure, and Humidity (and Rainfall if available).
Falls back gracefully if coordinates or neighbor stations are unavailable.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import config


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def find_neighbors(station_coords, n=config.NUM_NEIGHBORS):
    neighbors = {}
    for station, (lat, lon) in station_coords.items():
        distances = [(other, haversine_km(lat, lon, olat, olon))
                     for other, (olat, olon) in station_coords.items() if other != station]
        distances.sort(key=lambda x: x[1])
        neighbors[station] = [s for s, d in distances[:n]]
    return neighbors


def estimate_corrected_value(neighbor_avg, neighbor_std, unit="°C"):
    std = neighbor_std if (pd.notna(neighbor_std) and neighbor_std > 0) else 1.0
    low, high = round(neighbor_avg - std, 1), round(neighbor_avg + std, 1)
    return f"{low}{unit} to {high}{unit} (estimated, not confirmed)"


def subtle_tampering_score(diffs: np.ndarray) -> float:
    """% of readings that look suspicious vs neighbors."""
    if len(diffs) == 0 or diffs.std() == 0:
        return 0.0
    z = (diffs - diffs.mean()) / diffs.std()
    return round(float(np.mean(np.abs(z) > 1.0) * 100), 1)


def run(df) -> pd.DataFrame:
    # Check if lat/lon are present and station count >= 2
    has_coords = "lat" in df.columns and "lon" in df.columns and df["station_id"].nunique() >= 2
    if not has_coords:
        # Spatial analysis is unavailable; return graceful empty/unavailable state
        return pd.DataFrame(columns=[
            "station_id", "timestamp", "flag_type", "reason", "corrected_value",
            "subtle_tampering_score_%", "diff_val", "num_neighbors", "run_len"
        ])

    station_coords = df.drop_duplicates("station_id").set_index("station_id")[["lat", "lon"]]
    station_coords = {k: (v["lat"], v["lon"]) for k, v in station_coords.to_dict("index").items() if pd.notna(v["lat"]) and pd.notna(v["lon"])}
    if len(station_coords) < 2:
        return pd.DataFrame(columns=[
            "station_id", "timestamp", "flag_type", "reason", "corrected_value",
            "subtle_tampering_score_%", "diff_val", "num_neighbors", "run_len"
        ])

    neighbors = find_neighbors(station_coords)
    flags = []

    # Parameters to spatially cross-check
    spatial_checks = []
    if "temperature" in df.columns:
        spatial_checks.append(("temperature", config.TEMP_NEIGHBOR_DIFF, "Temperature", "°C"))
    if "pressure" in df.columns:
        spatial_checks.append(("pressure", config.PRESSURE_NEIGHBOR_DIFF, "Pressure", "hPa"))
    if "humidity" in df.columns:
        spatial_checks.append(("humidity", config.HUMIDITY_NEIGHBOR_DIFF, "Humidity", "%"))
    if "rainfall" in df.columns:
        spatial_checks.append(("rainfall", config.MISMATCH_THRESHOLD_MM, "Rainfall", "mm"))

    for param, threshold, label, unit in spatial_checks:
        pivot = df.pivot_table(index="timestamp", columns="station_id", values=param).sort_index()

        for station, nbr_list in neighbors.items():
            if station not in pivot.columns:
                continue
            nbr_cols = [n for n in nbr_list if n in pivot.columns]

            if nbr_cols:
                compare_series = pivot[nbr_cols].mean(axis=1)
                source = "neighbor-based"
            else:
                compare_series = pivot[station].expanding().mean()
                source = "self-history-based (no neighbors available)"

            station_series = pivot[station]

            if param == "pressure":
                # Normalize pressure by station mean to account for station elevation/altitude differences
                st_mean = pivot[station].mean()
                if nbr_cols:
                    nbr_means = pivot[nbr_cols].mean()
                    st_norm = pivot[station] - st_mean
                    cmp_norm = (pivot[nbr_cols] - nbr_means).mean(axis=1)
                else:
                    st_norm = pivot[station] - st_mean
                    cmp_norm = st_norm
                is_suspicious = (st_norm - cmp_norm).abs() > threshold
            elif param == "rainfall":
                is_suspicious = (station_series < 1.0) & (compare_series > threshold)
            else:
                is_suspicious = (station_series - compare_series).abs() > threshold

            timestamps = pivot.index.to_list()
            run_start = None
            for i, ts in enumerate(timestamps):
                val = is_suspicious.get(ts, False)
                if val and run_start is None:
                    run_start = i
                if (not val or i == len(timestamps) - 1) and run_start is not None:
                    run_end = i if not val else i + 1
                    run_len = run_end - run_start
                    if run_len >= config.REPEAT_COUNT or param != "rainfall":
                        seg_own = station_series.iloc[run_start:run_end]
                        seg_cmp = compare_series.iloc[run_start:run_end]
                        diffs = (seg_cmp - seg_own).values
                        diff_val = round(float(abs(seg_cmp.mean() - seg_own.mean())), 2)
                        flags.append({
                            "station_id": station,
                            "timestamp": timestamps[run_start],
                            "flag_type": "Possible tampering",
                            "reason": f"Reported {label} ~{seg_own.mean():.1f}{unit} while {source} average was "
                                      f"{seg_cmp.mean():.1f}{unit}, for {run_len} reading(s) ({source})",
                            "corrected_value": estimate_corrected_value(seg_cmp.mean(), seg_cmp.std(), unit),
                            "subtle_tampering_score_%": subtle_tampering_score(diffs),
                            "diff_val": diff_val,
                            "diff_mm": diff_val if param == "rainfall" else 0.0,
                            "num_neighbors": len(nbr_cols),
                            "run_len": run_len
                        })
                    run_start = None

    return pd.DataFrame(flags)

