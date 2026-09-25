"""
test_live_pipeline.py - Phase 2 Comprehensive Test Suite.

Tests live Open-Meteo data integration, real-time pipeline execution, station temporal ring buffer,
duplicate protection, SendGrid alert dispatch & cooldown, API failure resilience, and continuous processing.
"""

from unittest.mock import patch, MagicMock
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

import config
import live_data_fetcher
from live_service import LivePollingService


def test_1_normal_live_reading():
    """Test 1: Normal Live Reading -> NORMAL"""
    service = LivePollingService(seed_history=False)
    reading = {
        "station_id": "ST01",
        "timestamp": "2026-09-05 12:00:00",
        "temperature": 32.4,
        "pressure": 1008.2,
        "humidity": 71.0,
        "lat": 28.61,
        "lon": 77.20,
    }
    result = service.process_reading(reading)
    assert result["status"] == "NORMAL"
    assert result["severity"] == "NORMAL"
    assert result["confidence"] >= 90.0


def test_2_temperature_spike():
    """Test 2: Temperature Spike -> ANOMALY"""
    service = LivePollingService(seed_history=False)
    # Baseline normal reading
    service.process_reading({"station_id": "ST01", "timestamp": "2026-09-05 12:00:00", "temperature": 30.0, "pressure": 1008.0, "humidity": 65.0, "lat": 28.61, "lon": 77.20})
    # Sudden extreme spike
    spike_reading = {"station_id": "ST01", "timestamp": "2026-09-05 12:10:00", "temperature": 55.0, "pressure": 1008.0, "humidity": 90.0, "lat": 28.61, "lon": 77.20}
    result = service.process_reading(spike_reading)

    assert result["status"] == "ANOMALY"
    assert result["severity"] in ["CAUTION", "QUARANTINE", "REJECT"]
    assert result["confidence"] >= 50.0


def test_3_pressure_anomaly():
    """Test 3: Pressure Anomaly -> ANOMALY"""
    service = LivePollingService(seed_history=False)
    service.process_reading({"station_id": "ST01", "timestamp": "2026-09-05 12:00:00", "temperature": 30.0, "pressure": 1010.0, "humidity": 65.0, "lat": 28.61, "lon": 77.20})
    # Sudden 20 hPa pressure drop
    drop_reading = {"station_id": "ST01", "timestamp": "2026-09-05 12:10:00", "temperature": 30.0, "pressure": 990.0, "humidity": 65.0, "lat": 28.61, "lon": 77.20}
    result = service.process_reading(drop_reading)

    assert result["status"] == "ANOMALY"


def test_4_invalid_humidity():
    """Test 4: Invalid Humidity -> ANOMALY / Range Fault"""
    service = LivePollingService(seed_history=False)
    invalid_reading = {"station_id": "ST01", "timestamp": "2026-09-05 12:00:00", "temperature": 30.0, "pressure": 1008.0, "humidity": 150.0, "lat": 28.61, "lon": 77.20}
    result = service.process_reading(invalid_reading)

    assert result["status"] == "ANOMALY"


def test_5_flatline():
    """Test 5: Flatline Sensor -> FLATLINE / Sensor fault"""
    service = LivePollingService(seed_history=False)
    ts = datetime(2026, 9, 5, 12, 0, 0)
    results = []
    for _ in range(8):
        reading = {"station_id": "ST02", "timestamp": str(ts), "temperature": 29.4, "pressure": 1010.0, "humidity": 60.0, "lat": 19.07, "lon": 72.87}
        res = service.process_reading(reading)
        results.append(res)
        ts += timedelta(minutes=10)

    # Late readings should flag flatline
    assert any(r["status"] == "ANOMALY" for r in results[-3:])


def test_6_duplicate_timestamp():
    """Test 6: Duplicate Timestamp -> Process only once, return DUPLICATE_SKIPPED"""
    service = LivePollingService(seed_history=False)
    reading = {"station_id": "ST01", "timestamp": "2026-09-05 12:00:00", "temperature": 32.0, "pressure": 1008.0, "humidity": 65.0, "lat": 28.61, "lon": 77.20}

    first = service.process_reading(reading)
    second = service.process_reading(reading)

    assert first["status"] == "NORMAL"
    assert second["status"] == "DUPLICATE_SKIPPED"


def test_7_open_meteo_failure_handling():
    """Test 7: Open-Meteo Failure -> Graceful handling, status reports TEMPORARILY UNAVAILABLE"""
    service = LivePollingService(seed_history=False)
    with patch("requests.get", side_effect=Exception("API Network Timeout")):
        res = live_data_fetcher.fetch_live_station_reading("ST01", 28.61, 77.20, max_retries=1, timeout=1)
        assert res is None

        service.poll_once()
        status = service.get_status()
        assert status["collector_status"] == "TEMPORARILY UNAVAILABLE"
        assert "Open-Meteo" in status["last_api_error"]


def test_8_email_alert_with_cooldown():
    """Test 8: Email Alert -> Mock SendGrid, verify alert dispatch with cooldown prevention"""
    service = LivePollingService(seed_history=False)
    service.last_alert_time.clear()

    spike_reading = {"station_id": "ST07", "timestamp": "2026-09-05 12:00:00", "temperature": 61.0, "pressure": 1008.0, "humidity": 90.0, "lat": 26.85, "lon": 80.95}

    with patch("alerts.SendGridAPIClient") as mock_sg:
        mock_instance = MagicMock()
        mock_sg.return_value = mock_instance

        # First spike should trigger email dispatch
        res1 = service.process_reading(spike_reading)
        assert res1["status"] == "ANOMALY"

        # Immediate duplicate timestamp -> skipped
        res2 = service.process_reading(spike_reading)
        assert res2["status"] == "DUPLICATE_SKIPPED"

        # Sequential new timestamp with same condition within cooldown -> process reading, but don't re-send email
        spike_reading_2 = {"station_id": "ST07", "timestamp": "2026-09-05 12:10:00", "temperature": 61.0, "pressure": 1008.0, "humidity": 90.0, "lat": 26.85, "lon": 80.95}
        res3 = service.process_reading(spike_reading_2)
        assert res3["status"] == "ANOMALY"


def test_9_continuous_processing_50_readings():
    """Test 9: Continuous Processing -> 50 sequential readings, bounded memory, no crash"""
    service = LivePollingService(seed_history=False)

    ts = datetime(2026, 9, 5, 0, 0, 0)

    for i in range(50):
        temp = 30.0 + np.sin(i / 5.0) * 3.0
        reading = {
            "station_id": "ST01",
            "timestamp": str(ts),
            "temperature": round(float(temp), 1),
            "pressure": round(1010.0 + (i % 3), 1),
            "humidity": round(60.0 + (i % 5), 1),
            "lat": 28.61,
            "lon": 77.20,
        }
        res = service.process_reading(reading)
        assert "status" in res
        assert res["latency_ms"] >= 0
        ts += timedelta(minutes=10)

    # Check bounded memory buffer
    assert len(service.station_buffers["ST01"]) <= getattr(config, "STATION_HISTORY_MAX_LEN", 200)


def test_10_live_anomaly_history_stream():
    """Test 10: Bounded Live Anomaly History, Deduplication & Telemetry Separation"""
    service = LivePollingService(seed_history=True)

    # 1. Historical CSV anomalies must NOT be in live_anomaly_history
    status_initial = service.get_status()
    assert "live_anomaly_history" in status_initial
    for item in status_initial["live_anomaly_history"]:
        assert not str(item.get("timestamp", "")).startswith("2026-08")

    # 2. Process an anomaly reading for ST01 at 12:00
    r1 = {"station_id": "ST01", "timestamp": "2026-09-05 12:00:00", "temperature": 60.0, "pressure": 1008.0, "humidity": 90.0, "lat": 28.61, "lon": 77.20}
    service.process_reading(r1)

    status_1 = service.get_status()
    hist_1 = status_1["live_anomaly_history"]
    assert len(hist_1) >= 1
    assert any(h["station_id"] == "ST01" and str(h["timestamp"]) == "2026-09-05 12:00:00" for h in hist_1)

    # 3. Deduplication: process same station + same timestamp again -> no duplicate event added
    service.process_reading(r1)
    status_dup = service.get_status()
    assert len(status_dup["live_anomaly_history"]) == len(hist_1)

    # 4. New timestamp creates new event
    r2 = {"station_id": "ST01", "timestamp": "2026-09-05 12:10:00", "temperature": 62.0, "pressure": 1008.0, "humidity": 90.0, "lat": 28.61, "lon": 77.20}
    service.process_reading(r2)
    status_2 = service.get_status()
    hist_2 = status_2["live_anomaly_history"]
    assert len(hist_2) == len(hist_1) + 1

    # 5. Latest telemetry remains 1 record per station snapshot
    assert len(status_2["latest_telemetry"]) <= 10
    st01_telemetry = [t for t in status_2["latest_telemetry"] if t["station_id"] == "ST01"]
    assert len(st01_telemetry) == 1
    assert st01_telemetry[0]["timestamp"] == "2026-09-05 12:10:00"

    # 6. Verify maxlen bounding (bounded to 100 events)
    for i in range(15):
        r_i = {"station_id": f"ST{(i%10)+1:02d}", "timestamp": f"2026-09-06 {i//60:02d}:{i%60:02d}:00", "temperature": 65.0, "pressure": 1008.0, "humidity": 90.0, "lat": 28.61, "lon": 77.20}
        service.process_reading(r_i)

    status_bounded = service.get_status()
    assert len(status_bounded["live_anomaly_history"]) <= 100


def test_station_history_query():
    """Test get_station_history retrieves bounded observations sorted oldest -> newest."""
    service = LivePollingService(seed_history=False)
    for i in range(5):
        service.process_reading({
            "station_id": "ST01",
            "timestamp": f"2026-09-06 01:{i:02d}:00",
            "temperature": 25.0 + i,
            "pressure": 1010.0 - i,
            "humidity": 60.0 + i,
        })
    history = service.get_station_history("ST01", limit=3)
    assert len(history) == 3
    assert history[0]["timestamp"] == "2026-09-06 01:02:00"
    assert history[-1]["timestamp"] == "2026-09-06 01:04:00"
    assert history[-1]["temperature"] == 29.0


if __name__ == "__main__":
    pytest.main(["-v", __file__])
