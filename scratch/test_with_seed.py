import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live_service import LivePollingService
import live_data_fetcher
import pandas as pd

service = LivePollingService(seed_history=True)
stations = live_data_fetcher.DEFAULT_LIVE_STATIONS

print("--- PROCESSING LIVE READINGS WITH CSV SEEDING & FIXED DETECTORS ---")
for sid, info in stations.items():
    r = live_data_fetcher.fetch_live_station_reading(sid, info['lat'], info['lon'])
    if r:
        res = service.process_reading(r)
        print(f"{sid}: status={res['status']}, severity={res['severity']}, conf={res['confidence']}%, cause={res['root_cause']}")

status = service.get_status()
print("\n--- LATEST ANOMALIES COUNT ---")
print("Anomalies count:", len(status.get('latest_anomalies', [])))
print("Latest Telemetry count:", len(status.get('latest_telemetry', [])))
