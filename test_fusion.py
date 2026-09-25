"""
test_fusion.py - Comprehensive Unit & Regression Tests for Evidence-Based Anomaly Confidence Fusion.
"""

import math
import pandas as pd
import pytest
import fusion


def test_1_no_detector_evidence():
    res = fusion.combine(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    assert res.empty


def test_2_weak_ml_evidence():
    ml_df = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "ML-detected anomaly", "reason": "Borderline outlier",
        "ml_anomaly_score": -0.006
    }])
    res = fusion.combine(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), ml_df)
    assert len(res) == 1
    conf = res.iloc[0]["confidence_%"]
    # Mild ML outlier (40 base - 5 penalty + small mag) -> 35-40%
    assert 35.0 <= conf <= 45.0
    assert res.iloc[0]["trust_state"] == "CAUTION"


def test_3_strong_ml_evidence():
    ml_df_weak = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "ML-detected anomaly", "reason": "Borderline", "ml_anomaly_score": -0.006
    }])
    ml_df_strong = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "ML-detected anomaly", "reason": "Extreme outlier", "ml_anomaly_score": -0.18
    }])
    
    res_weak = fusion.combine(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), ml_df_weak)
    res_strong = fusion.combine(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), ml_df_strong)
    
    conf_weak = res_weak.iloc[0]["confidence_%"]
    conf_strong = res_strong.iloc[0]["confidence_%"]
    
    # Strong ML outlier produces higher confidence than borderline ML outlier
    assert conf_strong > conf_weak
    assert conf_strong >= 60.0


def test_4_weak_vs_strong_neighbor_discrepancy():
    nbr_weak = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Possible tampering", "reason": "Small mismatch",
        "subtle_tampering_score_%": 5.0, "diff_mm": 5.2, "num_neighbors": 3, "run_len": 3
    }])
    nbr_strong = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Possible tampering", "reason": "Large mismatch",
        "subtle_tampering_score_%": 45.0, "diff_mm": 15.0, "num_neighbors": 3, "run_len": 6
    }])
    
    res_weak = fusion.combine(pd.DataFrame(), pd.DataFrame(), nbr_weak, pd.DataFrame())
    res_strong = fusion.combine(pd.DataFrame(), pd.DataFrame(), nbr_strong, pd.DataFrame())
    
    conf_weak = res_weak.iloc[0]["confidence_%"]
    conf_strong = res_strong.iloc[0]["confidence_%"]
    
    assert conf_strong > conf_weak
    assert conf_strong >= 75.0


def test_5_weak_vs_strong_rule():
    rule_weak = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Sensor fault (range check)", "reason": "1 issue", "num_issues": 1
    }])
    rule_strong = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Silent station", "reason": "No data for 240 mins", "num_issues": 1
    }])
    
    res_weak = fusion.combine(rule_weak, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    res_strong = fusion.combine(rule_strong, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    
    assert res_strong.iloc[0]["confidence_%"] > res_weak.iloc[0]["confidence_%"]
    assert res_strong.iloc[0]["confidence_%"] >= 90.0


def test_6_weak_vs_strong_physics_violation():
    phys_weak = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Physics violation", "reason": "Small excess", "dew_point_diff_c": 0.6
    }])
    phys_strong = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Physics violation", "reason": "Large excess", "dew_point_diff_c": 4.5
    }])
    
    res_weak = fusion.combine(pd.DataFrame(), phys_weak, pd.DataFrame(), pd.DataFrame())
    res_strong = fusion.combine(pd.DataFrame(), phys_strong, pd.DataFrame(), pd.DataFrame())
    
    assert res_strong.iloc[0]["confidence_%"] > res_weak.iloc[0]["confidence_%"]


def test_7_two_independent_strong_detectors():
    phys_df = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Physics violation", "reason": "Dew point excess", "dew_point_diff_c": 3.0
    }])
    nbr_df = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Possible tampering", "reason": "Peer mismatch",
        "diff_mm": 8.0, "subtle_tampering_score_%": 20.0, "num_neighbors": 3, "run_len": 4
    }])
    
    res = fusion.combine(pd.DataFrame(), phys_df, nbr_df, pd.DataFrame())
    assert len(res) == 1
    conf = res.iloc[0]["confidence_%"]
    
    # 2 independent strong layers receive agreement synergy boost -> >= 80%
    assert conf >= 80.0
    assert res.iloc[0]["trust_state"] == "QUARANTINE"


def test_8_three_independent_detectors():
    rule_df = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Sensor fault (flatline)", "reason": "Stuck temp for 8 readings", "num_issues": 1
    }])
    phys_df = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Physics violation", "reason": "Dew point > temp", "dew_point_diff_c": 2.5
    }])
    ml_df = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "ML-detected anomaly", "reason": "Outlier", "ml_anomaly_score": -0.12
    }])
    
    res = fusion.combine(rule_df, phys_df, pd.DataFrame(), ml_df)
    conf = res.iloc[0]["confidence_%"]
    # 3 independent layers -> >= 85%
    assert conf >= 85.0


def test_9_all_four_detectors():
    rule_df = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Sensor fault (flatline)", "reason": "Flatline", "num_issues": 1
    }])
    phys_df = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Physics violation", "reason": "Dew point > temp", "dew_point_diff_c": 2.5
    }])
    nbr_df = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Possible tampering", "reason": "Mismatch",
        "subtle_tampering_score_%": 30.0, "diff_mm": 10.0, "num_neighbors": 3, "run_len": 5
    }])
    ml_df = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "ML-detected anomaly", "reason": "Outlier", "ml_anomaly_score": -0.2
    }])
    
    res = fusion.combine(rule_df, phys_df, nbr_df, ml_df)
    assert len(res) == 1
    conf = res.iloc[0]["confidence_%"]
    assert conf == 100.0


def test_10_insufficient_neighbor_peers_penalty():
    # Peer fallback mode (num_neighbors = 0) applies uncertainty penalty vs full 3 peers
    nbr_fallback = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Possible tampering", "reason": "self-history-based (no neighbors available)",
        "subtle_tampering_score_%": 15.0, "diff_mm": 6.0, "num_neighbors": 0, "run_len": 3
    }])
    nbr_full_peers = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Possible tampering", "reason": "neighbor-based average",
        "subtle_tampering_score_%": 15.0, "diff_mm": 6.0, "num_neighbors": 3, "run_len": 3
    }])
    
    res_fallback = fusion.combine(pd.DataFrame(), pd.DataFrame(), nbr_fallback, pd.DataFrame())
    res_full = fusion.combine(pd.DataFrame(), pd.DataFrame(), nbr_full_peers, pd.DataFrame())
    
    assert res_full.iloc[0]["confidence_%"] > res_fallback.iloc[0]["confidence_%"]


def test_11_malformed_detector_output():
    nbr_df = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Possible tampering", "reason": "Mismatch",
        "subtle_tampering_score_%": "corrupted_nan_string",
        "ml_anomaly_score": None
    }])
    res = fusion.combine(pd.DataFrame(), pd.DataFrame(), nbr_df, pd.DataFrame())
    assert len(res) == 1
    conf = res.iloc[0]["confidence_%"]
    assert 0.0 <= conf <= 100.0
    assert not math.isnan(conf)


def test_12_regression_proving_detector_count_formula_is_gone():
    """
    EXPLICIT REGRESSION TEST:
    Proves that confidence is NOT simply `(layers_agreeing / 4) * 100`.
    Old formula gave exactly 25.0% for any single detector flag.
    """
    ml_df_weak = pd.DataFrame([{
        "station_id": "ST01", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "ML-detected anomaly", "reason": "Mild", "ml_anomaly_score": -0.006
    }])
    rule_df_strong = pd.DataFrame([{
        "station_id": "ST02", "timestamp": "2026-08-28 10:00:00",
        "flag_type": "Silent station", "reason": "No data for 240m", "num_issues": 1
    }])
    
    res_weak = fusion.combine(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), ml_df_weak)
    res_strong = fusion.combine(rule_df_strong, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    
    conf_weak = res_weak.iloc[0]["confidence_%"]
    conf_strong = res_strong.iloc[0]["confidence_%"]
    
    # Neither score should be 25.0%
    assert conf_weak != 25.0
    assert conf_strong != 25.0
    assert conf_strong > conf_weak
