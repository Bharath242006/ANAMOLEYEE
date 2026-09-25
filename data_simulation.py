"""
SIH26073 - Part 1: Synthetic AWS Data Generator
--------------------------------------------------
Generates fake Automatic Weather Station (AWS) data for 10 stations.
By default generates core meteorological parameters (Temperature, Pressure, Humidity)
and intentionally injects 10 realistic faults across the core parameters.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

np.random.seed(42)  # so results are repeatable for demo

STATIONS = {
    "ST01": (28.61, 77.20),  # Delhi
    "ST02": (19.07, 72.87),  # Mumbai
    "ST03": (13.08, 80.27),  # Chennai
    "ST04": (12.97, 77.59),  # Bengaluru
    "ST05": (22.57, 88.36),  # Kolkata
    "ST06": (23.03, 72.58),  # Ahmedabad
    "ST07": (26.85, 80.95),  # Lucknow
    "ST08": (17.38, 78.49),  # Hyderabad
    "ST09": (15.30, 74.12),  # Belagavi
    "ST10": (30.74, 76.78),  # Chandigarh
}

READINGS_PER_STATION = 200
START_TIME = datetime(2026, 8, 28, 0, 0, 0)
INTERVAL_MIN = 10


def generate_clean_reading(base_temp=30, include_optional=False):
    """One normal, physically-realistic reading."""
    temperature = round(float(np.random.normal(base_temp, 2.5)), 1)
    humidity = round(float(np.clip(np.random.normal(60, 8), 15, 95)), 1)
    pressure = round(float(np.random.normal(1010, 3)), 1)

    if not include_optional:
        return temperature, pressure, humidity

    rainfall = round(float(max(0, np.random.exponential(1.2) - 0.8)), 1)
    wind_speed = round(float(max(0, np.random.normal(12, 4))), 1)
    wind_direction = round(float(np.random.uniform(0, 360)), 1)
    cloud_cover = round(float(np.clip(np.random.normal(40, 25), 0, 100)), 1)
    solar_radiation = round(float(max(0, np.random.normal(500, 150) * (1 - cloud_cover / 150))), 1)

    return (temperature, pressure, humidity, rainfall, wind_speed, wind_direction, solar_radiation, cloud_cover)


def build_dataset(include_optional=False, include_coords=True):
    rows = []
    for station_id, (lat, lon) in STATIONS.items():
        base_temp = np.random.uniform(24, 34)
        timestamp = START_TIME
        for i in range(READINGS_PER_STATION):
            if include_optional:
                temp, pres, hum, rain, wind, wind_dir, solar, cloud = generate_clean_reading(base_temp, include_optional=True)
                row = [station_id, timestamp, temp, pres, hum, rain, wind, wind_dir, solar, cloud]
            else:
                temp, pres, hum = generate_clean_reading(base_temp, include_optional=False)
                row = [station_id, timestamp, temp, pres, hum]

            if include_coords:
                row.insert(1, lat)
                row.insert(2, lon)

            rows.append(row)
            timestamp += timedelta(minutes=INTERVAL_MIN)

    cols = ["station_id"]
    if include_coords:
        cols.extend(["lat", "lon"])
    cols.extend(["timestamp", "temperature", "pressure", "humidity"])
    if include_optional:
        cols.extend(["rainfall", "wind_speed", "wind_direction", "solar_radiation", "cloud_cover"])

    df = pd.DataFrame(rows, columns=cols)
    return df


def inject_anomalies(df, scenario="default"):
    """Injects 10 fault types across core parameters: Temperature, Pressure, and Humidity."""
    df = df.copy()

    if scenario == "gurugram":
        st04_idx = df[df.station_id == "ST04"].index
        silent_block = st04_idx[40:160]
        df = df.drop(silent_block)
        return df.sort_values(["station_id", "timestamp"]).reset_index(drop=True)

    # 1. TEMPERATURE SPIKE (impossible value / extreme spike) -> ST07 temp jumps to 61°C
    st07_idx = df[df.station_id == "ST07"].index
    if len(st07_idx) > 120:
        df.loc[st07_idx[120], "temperature"] = 61.0

    # 2. PRESSURE ANOMALY (impossible low pressure value) -> ST05 pressure drops to 850 hPa
    st05_idx = df[df.station_id == "ST05"].index
    if len(st05_idx) > 40:
        df.loc[st05_idx[40], "pressure"] = 850.0

    # 3. HUMIDITY ANOMALY (impossible value > 100%) -> ST08 humidity set to 150%
    st08_idx = df[df.station_id == "ST08"].index
    if len(st08_idx) > 70:
        df.loc[st08_idx[70], "humidity"] = 150.0

    # 4. TEMPERATURE FLATLINE (stuck sensor) -> ST02 temp frozen for 18 readings
    st02_idx = df[df.station_id == "ST02"].index
    if len(st02_idx) > 68:
        df.loc[st02_idx[50:68], "temperature"] = 29.4

    # 5. PRESSURE FLATLINE -> ST06 pressure frozen for 18 readings
    st06_idx = df[df.station_id == "ST06"].index
    if len(st06_idx) > 100:
        df.loc[st06_idx[80:98], "pressure"] = 1012.4

    # 6. HUMIDITY FLATLINE -> ST01 humidity frozen for 18 readings
    st01_idx = df[df.station_id == "ST01"].index
    if len(st01_idx) > 48:
        df.loc[st01_idx[30:48], "humidity"] = 65.0

    # 7. SENSOR DRIFT -> ST09 temperature gradually drifts +0.5°C per step over 20 readings
    st09_idx = df[df.station_id == "ST09"].index
    if len(st09_idx) > 150:
        drift_indices = st09_idx[130:150]
        drift_offsets = np.linspace(0.5, 10.0, len(drift_indices))
        df.loc[drift_indices, "temperature"] += drift_offsets

    # 8. MISSING READINGS / SILENT STATION -> Drop 25 consecutive readings for ST04
    st04_idx = df[df.station_id == "ST04"].index
    if len(st04_idx) > 105:
        silent_block = st04_idx[80:105]
        df = df.drop(silent_block)

    # 9. MULTIVARIATE INCONSISTENCY -> ST10 temp set to 15°C while humidity=100% and dew point > temp
    st10_idx = df[df.station_id == "ST10"].index
    if len(st10_idx) > 110:
        df.loc[st10_idx[110], "temperature"] = 15.0
        df.loc[st10_idx[110], "humidity"] = 99.0
        df.loc[st10_idx[110], "pressure"] = 950.0  # combined shift

    # 10. SPATIAL INCONSISTENCY -> ST03 temp set to 55°C while neighbors are ~30°C
    st03_idx = df[df.station_id == "ST03"].index
    if len(st03_idx) > 160:
        df.loc[st03_idx[140:160], "temperature"] = 55.0

    return df.sort_values(["station_id", "timestamp"]).reset_index(drop=True)


if __name__ == "__main__":
    clean_df = build_dataset(include_optional=False)
    final_df = inject_anomalies(clean_df)
    final_df.to_csv("aws_data.csv", index=False)
    print(f"Generated {len(final_df)} readings across {len(STATIONS)} stations using ONLY core parameters.")
    print("Saved to aws_data.csv")

