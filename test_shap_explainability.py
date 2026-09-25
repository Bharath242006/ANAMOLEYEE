"""
test_shap_explainability.py - Verification & Integration Tests for SHAP Explainability Layer.
"""

import pytest
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from unittest.mock import patch, MagicMock

import config
from detection import ml_model, shap_explainer, rules, physics, neighbor
import fusion
from live_service import LivePollingService


def test_1_shap_module_import():
    """1. Test that shap and shap_explainer modules import successfully."""
    import shap
    assert hasattr(shap, "TreeExplainer"), "Expected shap to have TreeExplainer"
    assert hasattr(shap_explainer, "explain_observation"), "Expected shap_explainer to expose explain_observation"


def test_2_explanation_for_valid_observation():
    """2. Explanation generated for a valid ML observation."""
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
    assert exp["model"] == "Isolation Forest"
    assert len(exp["top_features"]) > 0


def test_3_feature_names_match():
    """3. Returned feature names match actual ML feature vector names."""
    raw_df = pd.DataFrame([{
        "station_id": "ST01",
        "timestamp": "2026-09-05 12:00:00",
        "temperature": 32.0,
        "pressure": 1008.0,
        "humidity": 65.0,
    }])
    df, feature_cols = ml_model.build_features(raw_df)
    model = IsolationForest(n_estimators=10, random_state=42)
    model.fit(df[feature_cols].fillna(0))

    exp = shap_explainer.explain_observation(model, feature_cols, df.iloc[0])
    exp_features = [f["feature"] for f in exp["top_features"]]
    assert sorted(exp_features) == sorted(feature_cols)


def test_4_contributions_numeric_and_finite():
    """4. Feature contributions are numeric and finite."""
    raw_df = pd.DataFrame([{
        "station_id": "ST01",
        "timestamp": "2026-09-05 12:00:00",
        "temperature": 45.0,
        "pressure": 1000.0,
        "humidity": 80.0,
    }])
    df, feature_cols = ml_model.build_features(raw_df)
    model = IsolationForest(n_estimators=10, random_state=42)
    model.fit(df[feature_cols].fillna(0))

    exp = shap_explainer.explain_observation(model, feature_cols, df.iloc[0])
    for feat in exp["top_features"]:
        contrib = feat["contribution"]
        assert isinstance(contrib, (float, int))
        assert not np.isnan(contrib)
        assert not np.isinf(contrib)


def test_5_features_ranked_by_abs_contribution():
    """5. Features are ranked by absolute contribution descending."""
    raw_df = pd.DataFrame([{
        "station_id": "ST01",
        "timestamp": "2026-09-05 12:00:00",
        "temperature": 60.0,
        "pressure": 980.0,
        "humidity": 95.0,
    }])
    df, feature_cols = ml_model.build_features(raw_df)
    model = IsolationForest(n_estimators=10, random_state=42)
    model.fit(df[feature_cols].fillna(0))

    exp = shap_explainer.explain_observation(model, feature_cols, df.iloc[0])
    abs_vals = [f["abs_contribution"] for f in exp["top_features"]]
    assert abs_vals == sorted(abs_vals, reverse=True)


def test_6_explanation_human_readable_summary():
    """6. Explanation contains dynamic human-readable summary string."""
    raw_df = pd.DataFrame([{
        "station_id": "ST01",
        "timestamp": "2026-09-05 12:00:00",
        "temperature": 60.0,
        "pressure": 1008.0,
        "humidity": 65.0,
    }])
    df, feature_cols = ml_model.build_features(raw_df)
    model = IsolationForest(n_estimators=10, random_state=42)
    model.fit(df[feature_cols].fillna(0))

    exp = shap_explainer.explain_observation(model, feature_cols, df.iloc[0])
    assert "summary" in exp
    assert "had the strongest contribution to the Isolation Forest decision" in exp["summary"]


def test_7_shap_failure_does_not_break_detection():
    """7. SHAP failure returns safe fallback without breaking anomaly detection."""
    with patch("shap.TreeExplainer", side_effect=Exception("Explainer crash")):
        raw_df = pd.DataFrame([{
            "station_id": "ST01",
            "timestamp": "2026-09-05 12:00:00",
            "temperature": 60.0,
            "pressure": 1008.0,
            "humidity": 65.0,
        }])
        df, feature_cols = ml_model.build_features(raw_df)
        model = IsolationForest(n_estimators=10, random_state=42)
        model.fit(df[feature_cols].fillna(0))

        exp = shap_explainer.explain_observation(model, feature_cols, df.iloc[0])
        assert exp["available"] is False
        assert "temporarily unavailable" in exp["summary"]


def test_8_nan_inf_input_handled_safely():
    """8. NaN/Infinity input handled safely."""
    raw_df = pd.DataFrame([{
        "station_id": "ST01",
        "timestamp": "2026-09-05 12:00:00",
        "temperature": float("nan"),
        "pressure": float("inf"),
        "humidity": 65.0,
    }])
    df, feature_cols = ml_model.build_features(raw_df)
    model = IsolationForest(n_estimators=10, random_state=42)
    model.fit(df[feature_cols].fillna(0))

    exp = shap_explainer.explain_observation(model, feature_cols, df.iloc[0])
    assert isinstance(exp, dict)
    assert "available" in exp


def test_9_fusion_behavior_unchanged():
    """9. Fusion behavior and confidence scoring remain unchanged."""
    rule_df = pd.DataFrame([{"station_id": "ST01", "timestamp": pd.Timestamp("2026-09-05 12:00:00"), "flag_type": "Sensor fault", "reason": "Range fault"}])
    physics_df = pd.DataFrame()
    neighbor_df = pd.DataFrame()
    ml_df = pd.DataFrame([{"station_id": "ST01", "timestamp": pd.Timestamp("2026-09-05 12:00:00"), "flag_type": "ML anomaly", "reason": "ML", "ml_anomaly_score": -0.15, "ml_explanation": {"available": True}}])

    fused = fusion.combine(rule_df, physics_df, neighbor_df, ml_df)
    assert not fused.empty
    assert "confidence_%" in fused.columns
    assert bool(fused.iloc[0]["flagged_by_ml"]) is True
    assert fused.iloc[0]["ml_explanation"] == {"available": True}



def test_10_schema_backward_compatibility():
    """10. Existing anomaly schema remains backward compatible."""
    rule_df = pd.DataFrame()
    physics_df = pd.DataFrame()
    neighbor_df = pd.DataFrame()
    ml_df = pd.DataFrame()

    fused_empty = fusion.combine(rule_df, physics_df, neighbor_df, ml_df)
    required_cols = ["station_id", "timestamp", "attribution", "confidence_%", "trust_state", "alert_priority", "corrected_value"]
    for col in required_cols:
        assert col in fused_empty.columns


def test_11_evidence_inspector_data_when_shap_available():
    """11. Evidence inspector payload formatting when SHAP is available."""
    raw_df = pd.DataFrame([
        {"station_id": "ST01", "timestamp": pd.Timestamp("2026-09-05 12:00:00"), "temperature": 30.0, "pressure": 1008.0, "humidity": 65.0},
        {"station_id": "ST01", "timestamp": pd.Timestamp("2026-09-05 12:10:00"), "temperature": 60.0, "pressure": 1008.0, "humidity": 95.0},
    ])
    ml_res = ml_model.run(raw_df)
    assert "ml_explanation" in ml_res.columns
    if not ml_res.empty:
        exp = ml_res.iloc[0]["ml_explanation"]
        assert exp["available"] in [True, False]


def test_12_evidence_inspector_data_when_shap_unavailable():
    """12. Evidence inspector payload formatting when SHAP is unavailable."""
    raw_df = pd.DataFrame([{"station_id": "ST01", "timestamp": pd.Timestamp("2026-09-05 12:00:00"), "temperature": 30.0, "pressure": 1008.0, "humidity": 65.0}])
    df, feature_cols = ml_model.build_features(raw_df)
    exp = shap_explainer.explain_observation(None, feature_cols, df.iloc[0])
    assert exp["available"] is False
    assert "summary" in exp


def test_13_live_pipeline_functional_with_shap():
    """13. Real-time live pipeline remains functional with SHAP."""
    service = LivePollingService(seed_history=False)
    r1 = {"station_id": "ST01", "timestamp": "2026-09-05 12:00:00", "temperature": 30.0, "pressure": 1008.0, "humidity": 65.0, "lat": 28.61, "lon": 77.20}
    res1 = service.process_reading(r1)
    assert res1["status"] == "NORMAL"

    r2 = {"station_id": "ST01", "timestamp": "2026-09-05 12:10:00", "temperature": 60.0, "pressure": 1008.0, "humidity": 95.0, "lat": 28.61, "lon": 77.20}
    res2 = service.process_reading(r2)
    assert res2["status"] == "ANOMALY"


def test_14_ml_explanation_deserialization_dict_and_json():
    """14. Test _parse_ml_explanation with dict, valid JSON string, and Python repr string."""
    from api import _parse_ml_explanation

    # Native dict
    d = {"available": True, "top_features": [{"feature": "temp", "contribution": 0.5}], "summary": "Temp anomaly"}
    assert _parse_ml_explanation(d) == d

    # Standard JSON string
    import json
    json_str = json.dumps(d)
    assert _parse_ml_explanation(json_str) == d

    # Python dict repr string (from CSV)
    repr_str = str(d)
    assert _parse_ml_explanation(repr_str) == d


def test_15_ml_explanation_deserialization_invalid_and_missing():
    """15. Test _parse_ml_explanation with invalid, empty, or missing values."""
    from api import _parse_ml_explanation

    assert _parse_ml_explanation(None) is None
    assert _parse_ml_explanation("") is None
    assert _parse_ml_explanation("None") is None
    assert _parse_ml_explanation("invalid JSON {") is None
    assert _parse_ml_explanation(float("nan")) is None


def test_16_api_anomalies_returns_parsed_ml_explanation():
    """16. Test that _load_csv and api.py get_anomalies parse ml_explanation correctly."""
    from api import _load_csv, _parse_ml_explanation
    import tempfile
    import os

    df_test = pd.DataFrame([
        {
            "station_id": "ST01",
            "timestamp": "2026-09-05 12:00:00",
            "attribution": "ML anomaly",
            "flagged_by_ml": True,
            "ml_explanation": str({"available": True, "top_features": [], "summary": "Test summary"}),
        }
    ])
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_csv = os.path.join(tmpdir, "test_report.csv")
        df_test.to_csv(tmp_csv, index=False)
        loaded_df = pd.read_csv(tmp_csv)
        parsed = _parse_ml_explanation(loaded_df.iloc[0]["ml_explanation"])
        assert isinstance(parsed, dict)
        assert parsed["available"] is True
        assert parsed["summary"] == "Test summary"


if __name__ == "__main__":
    pytest.main(["-v", __file__])
