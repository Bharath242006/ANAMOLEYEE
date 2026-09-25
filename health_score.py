"""
health_score.py - Sensor Health, Degradation Trend & RUL Prediction Engine.

Combines multi-factor signals (Anomaly Frequency, Data Completeness, Sensor Variance,
Communication Reliability) into an explainable Health Score (0-100), computes temporal
degradation trends, classifies Maintenance Risk, and predicts Remaining Useful Life (RUL).
"""

from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import config
from utils.json_sanitizer import sanitize_for_json


# Factor weights (must sum to 1.0)
FACTOR_WEIGHTS = {
    "anomaly_frequency": 0.40,
    "data_completeness": 0.20,
    "sensor_variance": 0.20,
    "communication_reliability": 0.20,
}


def _score_anomaly_frequency(station_id: str, raw_df: pd.DataFrame, all_flags_df: pd.DataFrame, window_start: pd.Timestamp, station_raw_df: pd.DataFrame = None, station_flags_df: pd.DataFrame = None) -> float:
    """Fewer flags relative to this station's reading count = healthier."""
    st_raw = station_raw_df if station_raw_df is not None else raw_df[raw_df["station_id"] == station_id]
    n_readings = max(len(st_raw), 1)
    n_flags = 0
    st_flags = station_flags_df if station_flags_df is not None else (all_flags_df[all_flags_df["station_id"] == station_id] if not all_flags_df.empty and "station_id" in all_flags_df.columns else pd.DataFrame())
    if not st_flags.empty:
        matching_flags = st_flags[pd.to_datetime(st_flags["timestamp"]) >= window_start]
        n_flags = len(matching_flags)
    flag_rate = n_flags / n_readings
    return float(max(0.0, min(100.0, 100.0 - flag_rate * 400.0)))


def _score_data_completeness(station_id: str, raw_df: pd.DataFrame, window_start: pd.Timestamp, station_raw_df: pd.DataFrame = None) -> float:
    """Compares actual reading count to expected count in window."""
    station_df = station_raw_df if station_raw_df is not None else raw_df[(raw_df["station_id"] == station_id) & (raw_df["timestamp"] >= window_start)]
    if station_df.empty:
        return 0.0
    span_min = (station_df["timestamp"].max() - station_df["timestamp"].min()).total_seconds() / 60.0
    if span_min <= 0:
        return 100.0
    expected_readings = max(span_min / getattr(config, "DATA_INTERVAL_MINUTES", 10), 1.0)
    completeness_ratio = min(len(station_df) / expected_readings, 1.0)
    return float(completeness_ratio * 100.0)


def _score_sensor_variance(station_id: str, raw_df: pd.DataFrame, window_start: pd.Timestamp, station_raw_df: pd.DataFrame = None) -> float:
    """Sudden increase in reading noise across core parameters indicates sensor degradation."""
    station_df = station_raw_df if station_raw_df is not None else raw_df[(raw_df["station_id"] == station_id) & (raw_df["timestamp"] >= window_start)]
    if len(station_df) < 3:
        return 100.0
    
    jitters = []
    for col, scale in [("temperature", 5.0), ("pressure", 10.0), ("humidity", 25.0)]:
        if col in station_df.columns:
            j = station_df[col].diff().abs().mean()
            if pd.notna(j):
                jitters.append(float(j) / scale)
    if not jitters:
        return 100.0
    avg_jitter = float(np.mean(jitters))
    return float(max(0.0, min(100.0, 100.0 - avg_jitter * 80.0)))


def _score_communication_reliability(station_id: str, raw_df: pd.DataFrame, window_start: pd.Timestamp, station_raw_df: pd.DataFrame = None) -> float:
    """Penalizes long reporting gaps (hardware/radio dropouts)."""
    station_df = station_raw_df if station_raw_df is not None else raw_df[(raw_df["station_id"] == station_id) & (raw_df["timestamp"] >= window_start)]
    station_df = station_df.sort_values("timestamp")
    if len(station_df) < 2:
        return 100.0
    gaps_minutes = station_df["timestamp"].diff().dt.total_seconds().dropna() / 60.0
    longest_gap = gaps_minutes.max() if len(gaps_minutes) else 0.0
    interval = getattr(config, "DATA_INTERVAL_MINUTES", 10)
    if longest_gap <= interval * 1.5:
        return 100.0
    penalty = (max(0.0, longest_gap - interval) / 60.0) * 15.0
    return float(max(0.0, min(100.0, 100.0 - penalty)))


def get_health_status_label(score: float) -> str:
    """Standardized health status thresholds."""
    if score >= 90.0:
        return "HEALTHY"
    elif score >= 75.0:
        return "GOOD"
    elif score >= 60.0:
        return "WARNING"
    elif score >= 40.0:
        return "DEGRADED"
    else:
        return "CRITICAL"


def compute_health_explanation(factors: dict, health_score: float, status: str) -> dict:
    """Generates human-readable explanation of health score breakdown."""
    anomaly_pts_lost = round((100.0 - factors["anomaly_frequency"]) * FACTOR_WEIGHTS["anomaly_frequency"], 1)
    completeness_pts_lost = round((100.0 - factors["data_completeness"]) * FACTOR_WEIGHTS["data_completeness"], 1)
    variance_pts_lost = round((100.0 - factors["sensor_variance"]) * FACTOR_WEIGHTS["sensor_variance"], 1)
    comm_pts_lost = round((100.0 - factors["communication_reliability"]) * FACTOR_WEIGHTS["communication_reliability"], 1)

    breakdown = [
        {"factor": "Anomaly frequency penalty", "points_lost": -anomaly_pts_lost},
        {"factor": "Data completeness gap", "points_lost": -completeness_pts_lost},
        {"factor": "Sensor noise & instability", "points_lost": -variance_pts_lost},
        {"factor": "Communication link dropouts", "points_lost": -comm_pts_lost},
    ]
    
    # Sort by largest point loss
    breakdown_sorted = sorted(breakdown, key=lambda x: x["points_lost"])
    largest_loss = breakdown_sorted[0]

    if largest_loss["points_lost"] == 0:
        primary_concern = "All health indicators are operating within normal baseline parameters."
        recommended_action = "Routine monitoring; no action required."
    else:
        if "Anomaly frequency" in largest_loss["factor"]:
            primary_concern = f"Repeated anomaly events detected in recent window (-{abs(largest_loss['points_lost'])} pts)."
            recommended_action = "Inspect physical sensor element and verify calibration."
        elif "completeness" in largest_loss["factor"]:
            primary_concern = f"Missing telemetry observations in history window (-{abs(largest_loss['points_lost'])} pts)."
            recommended_action = "Check power supply, data logger storage, and upload schedule."
        elif "noise" in largest_loss["factor"]:
            primary_concern = f"Abnormal reading-to-reading variance and signal noise (-{abs(largest_loss['points_lost'])} pts)."
            recommended_action = "Check sensor wiring, transducer aging, and shield grounding."
        else:
            primary_concern = f"Long communication reporting gaps detected (-{abs(largest_loss['points_lost'])} pts)."
            recommended_action = "Inspect modem antenna, cellular signal strength, and gateway connection."

    return {
        "score": health_score,
        "status": status,
        "contributing_factors": breakdown,
        "primary_concern": primary_concern,
        "recommended_action": recommended_action,
    }


def compute_degradation_trend(history_records: list) -> dict:
    """
    Computes linear regression trend over health history.
    history_records: list of dicts with 'timestamp' and 'health_score' (chronological).
    Returns dict: trend, degradation_rate, trend_confidence, r_squared.
    """
    if not history_records or len(history_records) < 3:
        return {
            "trend": "INSUFFICIENT_HISTORY",
            "degradation_rate": 0.0,
            "trend_confidence": "INSUFFICIENT_HISTORY",
            "r_squared": 0.0,
            "n_observations": len(history_records) if history_records else 0,
        }

    # Extract timestamps and scores
    dates = []
    scores = []
    for rec in history_records:
        ts_val = rec.get("timestamp") or rec.get("run_date")
        sc_val = rec.get("health_score")
        if ts_val is not None and sc_val is not None:
            try:
                dt = pd.to_datetime(ts_val)
                dates.append(dt)
                scores.append(float(sc_val))
            except Exception:
                continue

    if len(scores) < 3:
        return {
            "trend": "INSUFFICIENT_HISTORY",
            "degradation_rate": 0.0,
            "trend_confidence": "INSUFFICIENT_HISTORY",
            "r_squared": 0.0,
            "n_observations": len(scores),
        }

    # Convert timestamps to days elapsed relative to first observation
    t0 = dates[0]
    days_elapsed = np.array([(d - t0).total_seconds() / 86400.0 for d in dates], dtype=float)
    scores_arr = np.array(scores, dtype=float)

    # If all timestamps are identical or zero delta, fallback to index step
    if np.max(days_elapsed) == 0:
        days_elapsed = np.arange(len(scores_arr), dtype=float)

    # Fit linear regression: score = slope * day + intercept
    try:
        poly = np.polyfit(days_elapsed, scores_arr, 1)
        slope = float(poly[0])  # score points per day
        intercept = float(poly[1])
        
        # Calculate R^2 fit coefficient
        y_pred = slope * days_elapsed + intercept
        ss_res = np.sum((scores_arr - y_pred) ** 2)
        ss_tot = np.sum((scores_arr - np.mean(scores_arr)) ** 2)
        r_squared = float(1.0 - (ss_res / ss_tot)) if ss_tot > 0 else 1.0
        r_squared = float(max(0.0, min(1.0, r_squared)))
    except Exception:
        slope = 0.0
        r_squared = 0.0

    # Negative slope means health score is declining -> positive degradation rate (points lost / day)
    degradation_rate = round(float(max(0.0, -slope)), 2)

    # Trend classification
    if slope < -0.5:
        trend = "DEGRADING"
    elif slope > 0.5:
        trend = "IMPROVING"
    else:
        trend = "STABLE"

    if len(scores) >= 5:
        conf_pct = min(98, max(50, int(r_squared * 100)))
    else:
        conf_pct = min(75, max(40, int(r_squared * 80)))
    trend_confidence = f"{conf_pct}%"

    return {
        "trend": trend,
        "degradation_rate": degradation_rate,
        "trend_confidence": trend_confidence,
        "r_squared": round(r_squared, 3),
        "n_observations": len(scores),
    }


def compute_maintenance_risk(health_score: float, status: str, trend: str, degradation_rate: float) -> str:
    """Classifies Maintenance Risk: LOW, MEDIUM, HIGH, CRITICAL."""
    if health_score < 40.0 or status == "CRITICAL":
        return "CRITICAL"
    if health_score < 60.0 or status == "DEGRADED" or (trend == "DEGRADING" and degradation_rate >= 3.0):
        return "HIGH"
    if health_score < 75.0 or status == "WARNING" or trend == "DEGRADING":
        return "MEDIUM"
    return "LOW"


def predict_rul(health_score: float, trend: str, degradation_rate: float, r_squared: float, n_obs: int, threshold: float = 40.0) -> dict:
    """
    Computes Remaining Useful Life (RUL) estimate to reach maintenance threshold (40.0).
    Returns dict: rul_days, rul_label, rul_confidence, maintenance_threshold.
    """
    if n_obs < 3 or trend == "INSUFFICIENT_HISTORY":
        return {
            "rul_days": None,
            "rul_label": "Insufficient history",
            "rul_confidence": "INSUFFICIENT_HISTORY",
            "maintenance_threshold": threshold,
        }

    if trend in ["STABLE", "IMPROVING"]:
        return {
            "rul_days": None,
            "rul_label": "Not currently indicated",
            "rul_confidence": "HIGH",
            "maintenance_threshold": threshold,
        }

    if degradation_rate < 0.1:
        return {
            "rul_days": None,
            "rul_label": "Insufficient degradation evidence",
            "rul_confidence": "LOW",
            "maintenance_threshold": threshold,
        }

    if health_score <= threshold:
        return {
            "rul_days": 0.0,
            "rul_label": "Maintenance threshold crossed (inspect now)",
            "rul_confidence": "HIGH",
            "maintenance_threshold": threshold,
        }

    # Calculate days to threshold
    days_to_thresh = round((health_score - threshold) / degradation_rate, 1)
    days_to_thresh = max(0.0, days_to_thresh)

    if n_obs >= 5:
        conf_val = min(96, max(50, int(r_squared * 100)))
    else:
        conf_val = min(75, max(40, int(r_squared * 80)))

    label = f"~{int(days_to_thresh)} day(s) (trend-based estimate)" if days_to_thresh >= 1.0 else "< 1 day (trend-based estimate)"

    return {
        "rul_days": days_to_thresh,
        "rul_label": label,
        "rul_confidence": f"{conf_val}%",
        "maintenance_threshold": threshold,
    }


def compute_health_scores(raw_df: pd.DataFrame, all_flags_df: pd.DataFrame, window_days: int = 30) -> pd.DataFrame:
    """
    Multi-factor station health scoring (0-100) + Status + Explanation.
    """
    if raw_df.empty:
        return pd.DataFrame(columns=[
            "station_id", "health_score", "status", "anomaly_frequency_score",
            "data_completeness_score", "sensor_variance_score", "communication_score",
            "explanation"
        ])

    raw_df = raw_df.copy()
    if not pd.api.types.is_datetime64_any_dtype(raw_df["timestamp"]):
        raw_df["timestamp"] = pd.to_datetime(raw_df["timestamp"])
    latest_time = raw_df["timestamp"].max()
    window_start = latest_time - timedelta(days=window_days)
    raw_df = raw_df[raw_df["timestamp"] >= window_start]

    results = []
    for station_id in raw_df["station_id"].unique():
        st_raw = raw_df[raw_df["station_id"] == station_id]
        st_flags = all_flags_df[all_flags_df["station_id"] == station_id] if not all_flags_df.empty and "station_id" in all_flags_df.columns else pd.DataFrame()

        factors = {
            "anomaly_frequency": _score_anomaly_frequency(station_id, raw_df, all_flags_df, window_start, station_raw_df=st_raw, station_flags_df=st_flags),
            "data_completeness": _score_data_completeness(station_id, raw_df, window_start, station_raw_df=st_raw),
            "sensor_variance": _score_sensor_variance(station_id, raw_df, window_start, station_raw_df=st_raw),
            "communication_reliability": _score_communication_reliability(station_id, raw_df, window_start, station_raw_df=st_raw),
        }
        final_score = round(sum(factors[k] * FACTOR_WEIGHTS[k] for k in factors), 1)
        final_score = float(max(0.0, min(100.0, final_score)))

        status = get_health_status_label(final_score)
        explanation = compute_health_explanation(factors, final_score, status)

        results.append({
            "station_id": station_id,
            "health_score": final_score,
            "status": status,
            "anomaly_frequency_score": round(factors["anomaly_frequency"], 1),
            "data_completeness_score": round(factors["data_completeness"], 1),
            "sensor_variance_score": round(factors["sensor_variance"], 1),
            "communication_score": round(factors["communication_reliability"], 1),
            "explanation": explanation,
        })

    res_df = pd.DataFrame(results)
    if not res_df.empty:
        res_df = res_df.sort_values("health_score")
    return res_df





# Legacy compatibility functions
HISTORY_FILE = "health_score_history.csv"

def predict_remaining_life(health_history: list, critical_threshold: float = 50.0) -> str:
    """Legacy helper for backward compatibility."""
    if len(health_history) < 3:
        return "Not enough history yet to predict (need 3+ past health readings)"

    recs = [{"timestamp": f"2026-09-0{i+1} 12:00:00", "health_score": sc} for i, sc in enumerate(health_history)]
    trend_res = compute_degradation_trend(recs)
    sc = health_history[-1]
    rul_res = predict_rul(sc, trend_res["trend"], trend_res["degradation_rate"], trend_res["r_squared"], len(health_history), critical_threshold)
    return rul_res["rul_label"]


def save_to_history(health_df: pd.DataFrame, history_file: str = HISTORY_FILE):
    import os
    snapshot = health_df[["station_id", "health_score"]].copy()
    snapshot["run_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if os.path.exists(history_file):
        try:
            existing = pd.read_csv(history_file)
            combined = pd.concat([existing, snapshot], ignore_index=True)
        except Exception:
            combined = snapshot
    else:
        combined = snapshot

    combined.to_csv(history_file, index=False)
    return combined


def load_history_for_station(station_id: str, history_file: str = HISTORY_FILE) -> list:
    import os
    if not os.path.exists(history_file):
        return []
    try:
        history = pd.read_csv(history_file)
        station_history = history[history["station_id"] == station_id].sort_values("run_date")
        return station_history["health_score"].tolist()
    except Exception:
        return []


def add_life_predictions(health_df: pd.DataFrame, history_file: str = HISTORY_FILE) -> pd.DataFrame:
    predictions = []
    for station_id in health_df["station_id"]:
        past_scores = load_history_for_station(station_id, history_file)
        predictions.append(predict_remaining_life(past_scores))
    health_df = health_df.copy()
    health_df["remaining_life_prediction"] = predictions
    return health_df
