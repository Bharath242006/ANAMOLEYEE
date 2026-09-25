"""
live_data_fetcher.py - Live Open-Meteo Data Integration.

Fetches current/real-time meteorological observations (Temperature, Pressure, Relative Humidity)
from Open-Meteo forecast API for configured station coordinates. Handles timeouts, retries,
and error handling gracefully.
"""

import time
import requests
import pandas as pd
import numpy as np
import config

LIVE_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Station coordinates mapping (reused from project stations)
DEFAULT_LIVE_STATIONS = {
    "ST01": {"name": "Delhi", "lat": 28.61, "lon": 77.20},
    "ST02": {"name": "Mumbai", "lat": 19.07, "lon": 72.87},
    "ST03": {"name": "Chennai", "lat": 13.08, "lon": 80.27},
    "ST04": {"name": "Bengaluru", "lat": 12.97, "lon": 77.59},
    "ST05": {"name": "Kolkata", "lat": 22.57, "lon": 88.36},
    "ST06": {"name": "Ahmedabad", "lat": 23.03, "lon": 72.58},
    "ST07": {"name": "Lucknow", "lat": 26.85, "lon": 80.95},
    "ST08": {"name": "Hyderabad", "lat": 17.38, "lon": 78.49},
    "ST09": {"name": "Belagavi", "lat": 15.30, "lon": 74.12},
    "ST10": {"name": "Chandigarh", "lat": 30.74, "lon": 76.78},
}


def fetch_live_station_reading(station_id: str, lat: float, lon: float, max_retries: int = 2, timeout: int = None) -> dict | None:
    """
    Fetches latest single current weather reading for a station from Open-Meteo.
    Returns a dict containing core parameters (temperature, pressure, humidity, timestamp)
    or None if the API request fails.
    """
    if timeout is None:
        timeout = getattr(config, "OPEN_METEO_TIMEOUT_SECONDS", 10)

    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,surface_pressure",
        "timezone": "UTC",
    }

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(LIVE_FORECAST_URL, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()

            current = data.get("current", {})
            raw_time = current.get("time")
            temp = current.get("temperature_2m")
            hum = current.get("relative_humidity_2m")
            pres = current.get("surface_pressure")

            if raw_time is None or temp is None or hum is None or pres is None:
                raise ValueError(f"Incomplete payload from Open-Meteo for {station_id}: {current}")

            reading = {
                "station_id": station_id,
                "lat": float(lat),
                "lon": float(lon),
                "timestamp": str(pd.to_datetime(raw_time)),
                "temperature": round(float(temp), 1),
                "pressure": round(float(pres), 1),
                "humidity": round(float(hum), 1),
            }
            return reading

        except Exception as e:
            if attempt == max_retries:
                print(f"[LIVE METEO] Failed fetching {station_id} ({lat}, {lon}) after {max_retries} attempts: {e}")
                return None
            time.sleep(0.5)


    return None


def fetch_all_live_readings(stations: dict = DEFAULT_LIVE_STATIONS) -> pd.DataFrame:
    """
    Fetches current live readings for all configured stations and returns a DataFrame.
    """
    readings = []
    for sid, info in stations.items():
        reading = fetch_live_station_reading(sid, info["lat"], info["lon"])
        if reading is not None:
            readings.append(reading)

    if not readings:
        return pd.DataFrame(columns=["station_id", "lat", "lon", "timestamp", "temperature", "pressure", "humidity"])

    df = pd.DataFrame(readings)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.sort_values(["station_id", "timestamp"]).reset_index(drop=True)


if __name__ == "__main__":
    print("Testing Live Open-Meteo Fetcher...")
    df = fetch_all_live_readings()
    print(f"Fetched {len(df)} live station reading(s):")
    print(df.to_string(index=False))
