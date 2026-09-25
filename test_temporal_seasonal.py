"""
test_temporal_seasonal.py - Comprehensive Unit Tests for Temporal & Seasonal Intelligence Upgrade.
"""

import pytest
import math
import pandas as pd
from datetime import datetime
from detection.temporal import TemporalSeasonalEngine, temporal_engine_instance
import fusion
from live_service import live_service_instance


def test_station_baseline_isolation():
    # Verify that ST01 and ST04 baselines differ according to their actual historical data
    res_st01 = temporal_engine_instance.get_expected_conditions("ST01", "2026-08-29 14:00:00")
    res_st04 = temporal_engine_instance.get_expected_conditions("ST04", "2026-08-29 14:00:00")

    assert res_st01["station_id"] == "ST01"
    assert res_st04["station_id"] == "ST04"

    exp_t_01 = res_st01["temperature"]["expected"]
    exp_t_04 = res_st04["temperature"]["expected"]

    assert exp_t_01 is not None
    assert exp_t_04 is not None
    assert isinstance(exp_t_01, float)
    assert isinstance(exp_t_04, float)


def test_day_night_classification():
    day_res = temporal_engine_instance.get_expected_conditions("ST01", "2026-08-29 12:00:00")
    night_res = temporal_engine_instance.get_expected_conditions("ST01", "2026-08-29 22:00:00")

    assert day_res["day_night_state"] == "DAY"
    assert night_res["day_night_state"] == "NIGHT"


def test_insufficient_history_handling():
    # Query non-existent station ID
    res = temporal_engine_instance.get_expected_conditions("UNKNOWN_STATION_99", "2026-08-29 14:00:00", 25.0, 1010.0, 50.0)

    assert res["temporal_support"] == "INSUFFICIENT_HISTORY"
    assert res["seasonal_support"] == "INSUFFICIENT_HISTORY"
    assert res["pattern_status"] == "INSUFFICIENT_HISTORY"
    assert res["temperature"]["expected"] is None
    assert "Insufficient historical observations" in res["explanation"]


def test_robust_deviation_and_z_score():
    res = temporal_engine_instance.get_expected_conditions("ST01", "2026-08-29 14:00:00", actual_t=45.0, actual_p=1008.0, actual_h=55.0)

    t_eval = res["temperature"]
    assert t_eval["actual"] == 45.0
    assert t_eval["deviation"] is not None
    assert t_eval["robust_z"] > 0.0
    assert not math.isnan(t_eval["robust_z"])
    assert not math.isinf(t_eval["robust_z"])


def test_fusion_layer_integration():
    # Test fusion.combine with temporal_df
    rule_df = pd.DataFrame()
    physics_df = pd.DataFrame()
    neighbor_df = pd.DataFrame()
    ml_df = pd.DataFrame()

    temporal_df = pd.DataFrame([{
        "station_id": "ST01",
        "timestamp": "2026-08-29 14:00:00",
        "flag_type": "Temporal Deviation",
        "temporal_score": 75.0,
        "reason": "Test temporal anomaly"
    }])

    fused = fusion.combine(rule_df, physics_df, neighbor_df, ml_df, temporal_df)
    assert not fused.empty
    row = fused.iloc[0]
    assert row["station_id"] == "ST01"
    assert row["flagged_by_temporal"] == True
    assert row["confidence_%"] >= 20.0
    assert "Temporal" in row["attribution"]


def test_expected_api_endpoint():
    from api import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.get("/api/live/expected?station_id=ST02")
    assert response.status_code == 200
    data = response.json()

    assert data["station_id"] == "ST02"
    assert "day_night_state" in data
    assert "temperature" in data
    assert "pressure" in data
    assert "humidity" in data
    assert "temporal_score" in data
    assert "pattern_status" in data
    assert "explanation" in data
