import urllib.request
import json

url = "http://localhost:8000/api/live/status"
resp = urllib.request.urlopen(url)
data = json.loads(resp.read().decode())

print("==================================================")
print("LIVE ANOMALY API VERIFICATION REPORT")
print("==================================================")
print("Collector Status:", data.get("collector_status"))
print("Last Successful Fetch:", data.get("last_successful_fetch"))

anomalies = data.get("latest_anomalies", [])
print(f"Total Latest Anomalies in API: {len(anomalies)}")
print("\nTop Live Anomalies:")
for i, a in enumerate(anomalies[:8], 1):
    sid = a.get("station_id")
    ts = a.get("timestamp")
    attr = a.get("attribution")
    conf = a.get("confidence_%")
    trust = a.get("trust_state")
    corr = a.get("corrected_value", "None")
    print(f"{i}. [{sid}] Timestamp: {ts} | Issue: {attr} | Conf: {conf}% | Trust: {trust} | Corrected: {corr}")

print("==================================================")
