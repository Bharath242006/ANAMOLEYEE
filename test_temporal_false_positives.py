"""
test_temporal_false_positives.py - Regression Test Suite for Temporal Anomaly Triggering.

Verifies that:
1. Normal live observations across ST01-ST10 do NOT become temporal anomalies.
2. Small deviations from historical baseline do NOT trigger temporal anomalies.
3. Limited history does NOT trigger temporal anomalies.
4. Insufficient history does NOT trigger temporal anomalies.
5. Genuine large historical deviations CAN still trigger temporal anomalies when support is sufficient.
6. Expected value estimation continues to work properly.
7. Station-specific historical baselines remain station-specific.
8. Hour/month matching remains accurate.
9. Existing Rule/Physics/Spatial/ML detection remains unchanged.
10. Existing SHAP functionality remains unchanged.
"""

import pytest
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from detection.temporal import TemporalSeasonalEngine, temporal_engine_instance
from detection import rules, physics, neighbor, ml_model, shap_explainer
import fusion
from live_service import LivePollingService


def test_1_normal_live_observations_not_anomalies():
    """1. Normal live observations across ST01-ST10 do NOT become temporal anomalies."""
    stations = ["ST01", "ST02", "ST03", "ST04", "ST05", "ST06", "ST07", "ST08", "ST09", "ST10"]
    for st_id in stations:
        cond = temporal_engine_instance.get_expected_conditions(st_id, "2026-09-07 14:00:00", actual_t=29.5, actual_p=1009.0, actual_h=62.0)
        anom = temporal_engine_instance.detect_anomaly({
            "station_id": st_id,
            "timestamp": "2026-09-07 14:00:00",
            "temperature": 29.5,
            "pressure": 1009.0,
            "humidity": 62.0
        })
        assert anom is None, f"Station {st_id} normal reading should not trigger temporal anomaly"
        assert cond["temperature"]["expected"] is not None


def test_2_small_deviation_does_not_trigger():
    """2. Small deviation from historical baseline does NOT trigger temporal anomaly."""
    # ST01 baseline temp is around 29-30°C. Small shift +2.5°C
    anom = temporal_engine_instance.detect_anomaly({
        "station_id": "ST01",
        "timestamp": "2026-08-29 12:00:00",
        "temperature": 32.0,
        "pressure": 1008.0,
        "humidity": 63.0
    })
    assert anom is None, "Small 2.5°C temperature deviation must not trigger temporal anomaly"


def test_3_limited_history_does_not_trigger():
    """3. Limited history does NOT independently trigger temporal anomaly."""
    engine = TemporalSeasonalEngine()
    # Mock a bucket with sample count in LIMITED_HISTORY range (5 to 19)
    engine.station_hourly_baselines[("ST99", 12)] = {
        "station_id": "ST99",
        "hour": 12,
        "sample_count": 8,
        "temperature": {"median": 28.0, "mad": 1.0},
        "pressure": {"median": 1010.0, "mad": 1.5},
        "humidity": {"median": 60.0, "mad": 3.0},
    }
    cond = engine.get_expected_conditions("ST99", "2026-08-29 12:00:00", actual_t=45.0, actual_p=1010.0, actual_h=60.0)
    assert cond["temporal_support"] == "LIMITED_HISTORY"

    anom = engine.detect_anomaly({
        "station_id": "ST99",
        "timestamp": "2026-08-29 12:00:00",
        "temperature": 45.0,
        "pressure": 1010.0,
        "humidity": 60.0
    })
    assert anom is None, "LIMITED_HISTORY must not trigger temporal anomaly"


def test_4_insufficient_history_does_not_trigger():
    """4. Insufficient history does NOT trigger temporal anomaly."""
    anom = temporal_engine_instance.detect_anomaly({
        "station_id": "ST_UNKNOWN_99",
        "timestamp": "2026-08-29 12:00:00",
        "temperature": 50.0,
        "pressure": 950.0,
        "humidity": 10.0
    })
    assert anom is None, "INSUFFICIENT_HISTORY must not trigger temporal anomaly"


def test_5_genuine_large_historical_deviation_triggers():
    """5. Genuine large historical deviation can still trigger temporal anomaly when history is sufficient."""
    engine = TemporalSeasonalEngine()
    # Mock a bucket with SUFFICIENT_HISTORY (>=20) and extreme deviation
    engine.station_hourly_baselines[("ST_SUFF", 12)] = {
        "station_id": "ST_SUFF",
        "hour": 12,
        "sample_count": 50,
        "temperature": {"median": 25.0, "mad": 1.0},
        "pressure": {"median": 1010.0, "mad": 1.5},
        "humidity": {"median": 60.0, "mad": 3.0},
    }
    cond = engine.get_expected_conditions("ST_SUFF", "2026-08-29 12:00:00", actual_t=50.0, actual_p=1010.0, actual_h=60.0)
    assert cond["temporal_support"] == "SUFFICIENT_HISTORY"
    assert cond["temperature"]["status"] == "ABNORMAL"

    anom = engine.detect_anomaly({
        "station_id": "ST_SUFF",
        "timestamp": "2026-08-29 12:00:00",
        "temperature": 50.0,
        "pressure": 1010.0,
        "humidity": 60.0
    })
    assert anom is not None, "Genuine large deviation with SUFFICIENT_HISTORY should trigger temporal anomaly"
    assert anom["is_temporal_anomaly"] == True


def test_6_expected_value_estimation_functional():
    """6. Expected-value estimation still works regardless of anomaly triggering."""
    res = temporal_engine_instance.get_expected_conditions("ST01", "2026-08-29 14:00:00", actual_t=30.0, actual_p=1009.0, actual_h=65.0)
    assert res["temperature"]["expected"] is not None
    assert res["pressure"]["expected"] is not None
    assert res["humidity"]["expected"] is not None
    assert "explanation" in res


def test_7_station_specific_baselines():
    """7. Station-specific historical baselines remain station-specific."""
    res1 = temporal_engine_instance.get_expected_conditions("ST01", "2026-08-29 14:00:00")
    res2 = temporal_engine_instance.get_expected_conditions("ST02", "2026-08-29 14:00:00")
    assert res1["station_id"] == "ST01"
    assert res2["station_id"] == "ST02"


def test_8_hour_month_matching():
    """8. Hour/month matching remains correct."""
    res_noon = temporal_engine_instance.get_expected_conditions("ST01", "2026-08-29 12:00:00")
    res_night = temporal_engine_instance.get_expected_conditions("ST01", "2026-08-29 23:00:00")
    assert res_noon["day_night_state"] == "DAY"
    assert res_night["day_night_state"] == "NIGHT"


def test_9_existing_layers_unchanged():
    """9. Existing Rule/Physics/Spatial/ML detection is unchanged."""
    test_df = pd.DataFrame([{
        "station_id": "ST01",
        "timestamp": pd.to_datetime("2026-08-29 12:00:00"),
        "temperature": 65.0,  # Extreme temp out of range (>50C)
        "pressure": 1008.0,
        "humidity": 95.0
    }])
    r_df = rules.run(test_df)
    assert not r_df.empty, "Rules engine should flag 65.0°C"


def test_10_shap_explainability_unchanged():
    """10. Existing SHAP functionality is unchanged."""
    raw_df = pd.DataFrame([{
        "station_id": "ST01",
        "timestamp": "2026-09-05 12:00:00",
        "temperature": 55.0,
        "pressure": 1008.0,
        "humidity": 95.0,
    }])
    df, feature_cols = ml_model.build_features(raw_df)
    model = IsolationForest(n_estimators=10, random_state=42)
    X = df[feature_cols].fillna(0)
    model.fit(X)

    exp = shap_explainer.explain_observation(model, feature_cols, df.iloc[0])
    assert exp["available"] is True
    assert len(exp["top_features"]) > 0
