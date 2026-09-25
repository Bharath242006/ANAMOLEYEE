"""
test_sensor_health_rul.py - Comprehensive Unit Tests for Sensor Health, Degradation Trend & RUL Prediction.
"""

import pytest
import math
import pandas as pd
from datetime import datetime, timedelta
import health_score
from live_service import LivePollingService
from utils.json_sanitizer import sanitize_for_json


def test_1_new_station_insufficient_history():
    """1. New station starts with insufficient health history."""
    recs = [{"timestamp": "2026-09-01 12:00:00", "health_score": 95.0}]
    trend_res = health_score.compute_degradation_trend(recs)
    assert trend_res["trend"] == "INSUFFICIENT_HISTORY"
    rul_res = health_score.predict_rul(95.0, trend_res["trend"], trend_res["degradation_rate"], trend_res["r_squared"], len(recs))
    assert rul_res["rul_days"] is None
    assert rul_res["rul_label"] == "Insufficient history"


def test_2_stable_health_history():
    """2. Stable health history -> STABLE."""
    recs = [
        {"timestamp": f"2026-09-0{i+1} 12:00:00", "health_score": 92.0 + (i % 2) * 0.5}
        for i in range(5)
    ]
    trend_res = health_score.compute_degradation_trend(recs)
    assert trend_res["trend"] == "STABLE"


def test_3_increasing_health_history():
    """3. Increasing health -> IMPROVING."""
    recs = [
        {"timestamp": f"2026-09-0{i+1} 12:00:00", "health_score": 70.0 + i * 3.0}
        for i in range(5)
    ]
    trend_res = health_score.compute_degradation_trend(recs)
    assert trend_res["trend"] == "IMPROVING"


def test_4_decreasing_health_history():
    """4. Decreasing health -> DEGRADING."""
    recs = [
        {"timestamp": f"2026-09-0{i+1} 12:00:00", "health_score": 95.0 - i * 5.0}
        for i in range(5)
    ]
    trend_res = health_score.compute_degradation_trend(recs)
    assert trend_res["trend"] == "DEGRADING"
    assert trend_res["degradation_rate"] > 0.0


def test_5_severe_degradation_increases_risk():
    """5. Severe degradation -> maintenance risk increases."""
    risk_low = health_score.compute_maintenance_risk(95.0, "HEALTHY", "STABLE", 0.0)
    assert risk_low == "LOW"

    risk_high = health_score.compute_maintenance_risk(55.0, "DEGRADED", "DEGRADING", 4.5)
    assert risk_high in ["HIGH", "CRITICAL"]


def test_6_rul_insufficient_history():
    """6. RUL is not produced with insufficient history."""
    rul_res = health_score.predict_rul(85.0, "INSUFFICIENT_HISTORY", 0.0, 0.0, 1)
    assert rul_res["rul_days"] is None
    assert rul_res["rul_label"] == "Insufficient history"


def test_7_degradation_sequence_prediction():
    """7. RUL is calculated from a degradation sequence when sufficient history exists."""
    recs = [
        {"timestamp": f"2026-09-0{i+1} 12:00:00", "health_score": 94.0 - i * 7.0}
        for i in range(5)
    ]
    trend_eval = health_score.compute_degradation_trend(recs)
    assert trend_eval["trend"] == "DEGRADING"
    rul_eval = health_score.predict_rul(61.0, trend_eval["trend"], trend_eval["degradation_rate"], trend_eval["r_squared"], 5)
    assert rul_eval["rul_days"] is not None
    assert rul_eval["rul_days"] > 0.0


def test_8_rul_never_negative():
    """8. RUL never becomes negative."""
    # Score already below threshold 40.0
    rul_res = health_score.predict_rul(35.0, "DEGRADING", 5.0, 0.95, 5)
    assert rul_res["rul_days"] == 0.0
    assert rul_res["rul_days"] >= 0.0


def test_9_stable_sensor_no_false_maintenance():
    """9. Stable sensor does not receive a false maintenance prediction."""
    rul_res = health_score.predict_rul(90.0, "STABLE", 0.0, 0.99, 10)
    assert rul_res["rul_days"] is None
    assert rul_res["rul_label"] == "Not currently indicated"


def test_10_isolated_anomaly_not_automatic_degradation():
    """10. One isolated anomaly does not automatically cause degradation."""
    recs = [
        {"timestamp": "2026-09-01 12:00:00", "health_score": 95.0},
        {"timestamp": "2026-09-02 12:00:00", "health_score": 94.0},
        {"timestamp": "2026-09-03 12:00:00", "health_score": 85.0}, # isolated dip
        {"timestamp": "2026-09-04 12:00:00", "health_score": 94.0},
        {"timestamp": "2026-09-05 12:00:00", "health_score": 95.0},
    ]
    trend_res = health_score.compute_degradation_trend(recs)
    assert trend_res["trend"] != "DEGRADING"


def test_11_health_history_is_bounded():
    """11. Health history is bounded."""
    from collections import deque
    service = LivePollingService(seed_history=False)
    service.station_health_history["ST_BOUNDED"] = deque(maxlen=100)
    for i in range(150):
        service.station_health_history["ST_BOUNDED"].append({
            "station_id": "ST_BOUNDED",
            "timestamp": f"2026-09-01 12:{i:02d}:00",
            "health_score": 90.0,
            "status": "HEALTHY",
        })
    assert len(service.station_health_history["ST_BOUNDED"]) == 100


def test_12_bridge_gap_safe():
    """12. Historical/live bridge gaps do not create fake degradation."""
    recs = [
        {"timestamp": "2026-08-01 12:00:00", "health_score": 90.0},
        {"timestamp": "2026-08-02 12:00:00", "health_score": 90.0},
        {"timestamp": "2026-09-05 12:00:00", "health_score": 90.0},
    ]
    trend_res = health_score.compute_degradation_trend(recs)
    assert trend_res["trend"] == "STABLE"


def test_13_communication_failures_affect_health():
    """13. Communication failures affect health appropriately."""
    dates = pd.date_range("2026-09-01", periods=10, freq="10min")
    # Simulate a gap of 5 hours
    gap_dates = dates.tolist() + [pd.Timestamp("2026-09-01 07:00:00")]
    df = pd.DataFrame({
        "station_id": ["ST01"] * len(gap_dates),
        "timestamp": gap_dates,
        "temperature": [25.0] * len(gap_dates),
        "pressure": [1013.25] * len(gap_dates),
        "humidity": [65.0] * len(gap_dates),
    })
    comm_score = health_score._score_communication_reliability("ST01", df, pd.Timestamp("2026-09-01 00:00:00"))
    assert comm_score < 100.0


def test_14_json_nan_infinity_safe():
    """14. API JSON contains no NaN/Infinity."""
    res = health_score.predict_rul(85.0, "DEGRADING", 2.5, 0.95, 5)
    sanitized = sanitize_for_json(res)
    
    import json
    json_str = json.dumps(sanitized)
    assert "NaN" not in json_str
    assert "Infinity" not in json_str

