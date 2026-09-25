import live_data_fetcher
from detection import rules, physics, neighbor, ml_model
import fusion
import pandas as pd
import sys

print("Fetching live station readings...")
stations = live_data_fetcher.DEFAULT_LIVE_STATIONS
readings = []
for sid, info in stations.items():
    r = live_data_fetcher.fetch_live_station_reading(sid, info['lat'], info['lon'])
    if r:
        readings.append(r)

df = pd.DataFrame(readings)
df['timestamp'] = pd.to_datetime(df['timestamp'])

print("--- RAW LIVE READINGS ---")
print(df[['station_id', 'timestamp', 'temperature', 'pressure', 'humidity']])

rule_df = rules.run(df)
print("\n--- RULE DETECTOR OUTPUT ---")
print(rule_df)

physics_df = physics.run(df)
print("\n--- PHYSICS DETECTOR OUTPUT ---")
print(physics_df)

neighbor_df = neighbor.run(df)
print("\n--- NEIGHBOR DETECTOR OUTPUT ---")
print(neighbor_df)

try:
    ml_df = ml_model.run(df)
    print("\n--- ML DETECTOR OUTPUT ---")
    print(ml_df)
except Exception as e:
    print("ML error:", e)
    ml_df = pd.DataFrame()

final_df = fusion.combine(rule_df, physics_df, neighbor_df, ml_df)
print("\n--- FUSION OUTPUT ---")
print(final_df)
