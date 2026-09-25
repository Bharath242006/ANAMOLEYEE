"""
test_live_dashboard_binding.py - Verification of live dashboard data contract and station history filtering.
"""

import pytest
import math
from live_service import live_service_instance

def test_live_status_response_structure():
    status = live_service_instance.get_status()
    assert isinstance(status, dict)
    assert "collector_status" in status
    assert "latest_telemetry" in status
    assert "live_anomaly_history" in status
    
    # Check for NaN / Infinity
    telemetry = status.get("latest_telemetry", [])
    for rec in telemetry:
        if rec.get("temperature") is not None:
            assert not math.isnan(rec["temperature"])
            assert not math.isinf(rec["temperature"])

def test_station_history_isolation():
    stations = ["ST01", "ST02", "ST03", "ST04", "ST10"]
    histories = {}
    
    for st in stations:
        h = live_service_instance.get_station_history(station_id=st, limit=50)
        histories[st] = h
        assert isinstance(h, list)
        for sample in h:
            assert sample["station_id"] == st
            assert "timestamp" in sample
            assert "temperature" in sample
            assert "pressure" in sample
            assert "humidity" in sample

    # Verify that ST01 and ST02 samples reflect their respective station telemetry
    if len(histories["ST01"]) > 0 and len(histories["ST02"]) > 0:
        st01_temp = histories["ST01"][0]["temperature"]
        st02_temp = histories["ST02"][0]["temperature"]
        # They should both be valid numbers
        assert isinstance(st01_temp, (int, float))
        assert isinstance(st02_temp, (int, float))

def test_static_html_element_bindings():
    import os
    index_path = os.path.join("static", "index.html")
    assert os.path.exists(index_path)
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check required UI element IDs
    assert 'id="overviewTable"' in content
    assert 'id="attributionBreakdown"' in content
    assert 'id="stationSelector"' in content
    assert 'id="summaryTemp"' in content
    assert 'id="summaryPressure"' in content
    assert 'id="summaryHumidity"' in content
    assert 'id="tempChartContainer"' in content
    assert 'id="pressureChartContainer"' in content
    assert 'id="humidityChartContainer"' in content

    # Check required function calls
    assert 'renderLiveAnomalyFeed' in content
    assert 'renderIntelligenceAttribution' in content
    assert 'onStationChange' in content
    assert 'fetchLiveVisualizationData' in content

def test_duplicate_active_observation_removed_and_sections_preserved():
    import os
    index_path = os.path.join("static", "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Duplicate Active Station Observation section & Temporal UI must be removed
    assert "Active Station Observation" not in content
    assert "heroMetricCards" not in content
    assert "renderHeroObservation" not in content
    assert "TEMPORAL & SEASONAL INTELLIGENCE" not in content

    # 2. Existing primary dashboard sections must be preserved
    assert "LIVE WEATHER SIGNALS" in content
    assert "Recent Anomaly Intelligence Feed" in content
    assert "Intelligence Attribution" in content
    assert "Sensor Health" in content


