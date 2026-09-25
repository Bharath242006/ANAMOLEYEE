"""
fusion.py - Combines all detection layers into one final verdict.

EVIDENCE-BASED ANOMALY CONFIDENCE FUSION:
Takes independent outputs from rule-based, physics-based, neighbor spatial,
and ML (Isolation Forest) detection layers and calculates:
  - attribution    : Most specific single label for the root cause
  - confidence_%   : Evidence-based anomaly confidence score (0-100%),
                     combining layer base evidence, magnitude strength,
                     cross-layer agreement, and data quality penalties.
  - trust_state    : ACCEPT / CAUTION / QUARANTINE / REJECT
  - alert_priority : Role-based priority routing
"""

import pandas as pd
import numpy as np
import config


def _match_key(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["match_key"] = df["station_id"] + "_" + df["timestamp"].dt.floor("1min").astype(str)
    return df



def _trust_state(confidence: float, attribution: str) -> str:
    if attribution == "Silent station":
        return "REJECT"
    if confidence >= config.TRUST_QUARANTINE_CONFIDENCE:
        return "QUARANTINE"
    if confidence >= config.TRUST_CAUTION_CONFIDENCE:
        return "CAUTION"
    return "ACCEPT"


def _alert_priority(confidence: float) -> str:
    if confidence >= config.ALERT_CRITICAL_CONFIDENCE:
        return "CRITICAL - send immediately"
    if confidence >= config.ALERT_MEDIUM_CONFIDENCE:
        return "MEDIUM - daily digest"
    return "LOW - log only"


def _calculate_evidence_confidence(hit: dict, details: dict) -> float:
    """
    Calculates a deterministic, evidence-based anomaly confidence score (0-100).
    
    Formula Architecture:
      Confidence = Clamp( Max_Base_Evidence + Magnitude_Bonus + Agreement_Bonus - Uncertainty_Penalty, 10, 100 )
      
    Components:
      1. Base Evidence (E_base): Intrinsic reliability/weight of each triggered layer.
      2. Magnitude Strength (M_mag): Numerical severity/deviation magnitude (e.g. ML decision score,
         dew point excess, tampering z-score / mm diff, range violation count).
      3. Cross-Layer Agreement (A_agree): Synergy boost for multi-layer independent confirmation.
      4. Quality & Uncertainty Penalty (P_uncertainty): Deductions for missing peers or isolated weak signals.
    """
    if not any(hit.values()):
        return 0.0

    layer_bases = []
    layer_magnitudes = []
    penalties = 0.0
    
    # -------------------------------------------------------------
    # 1. Rule Layer Evidence
    # -------------------------------------------------------------
    if hit.get("rule"):
        rule_row = details.get("rule")
        flag_type = str(rule_row.get("flag_type", "")) if rule_row is not None else ""
        num_issues = int(rule_row.get("num_issues", 1)) if rule_row is not None else 1
        
        if "Silent" in flag_type:
            # Silent station outage (structural non-reception)
            rule_base = 85.0
            gap_mins = 120
            if rule_row is not None and "reason" in rule_row:
                try:
                    # Parse gap minutes if available
                    parts = str(rule_row["reason"]).split("for ")
                    if len(parts) > 1:
                        gap_mins = int(parts[1].split()[0])
                except (ValueError, IndexError):
                    gap_mins = 120
            gap_mag = min(10.0, max(0.0, (gap_mins - 120) / 20.0))
            rule_mag = gap_mag
        elif "flatline" in flag_type.lower():
            rule_base = 60.0
            run_len = 6
            if rule_row is not None and "reason" in rule_row:
                try:
                    parts = str(rule_row["reason"]).split("for ")
                    if len(parts) > 1:
                        run_len = int(parts[1].split()[0])
                except (ValueError, IndexError):
                    run_len = 6
            flat_mag = min(15.0, max(0.0, (run_len - 6) * 2.0))
            rule_mag = flat_mag
        else:
            rule_base = 50.0
            rule_mag = min(20.0, max(0.0, (num_issues - 1) * 10.0))
            
        layer_bases.append(rule_base)
        layer_magnitudes.append(rule_mag)

    # -------------------------------------------------------------
    # 2. Physics Layer Evidence
    # -------------------------------------------------------------
    if hit.get("physics"):
        physics_base = 58.0
        physics_row = details.get("physics")
        diff_c = 0.0
        if physics_row is not None and "dew_point_diff_c" in physics_row:
            try:
                diff_c = float(physics_row["dew_point_diff_c"])
            except (ValueError, TypeError):
                diff_c = 0.0
        
        # Magnitude bonus derived from dew point excess above dry-bulb temperature (dp - temp - 0.5)
        physics_mag = min(22.0, max(0.0, (diff_c - 0.5) * 4.0))
        layer_bases.append(physics_base)
        layer_magnitudes.append(physics_mag)

    # -------------------------------------------------------------
    # 3. Neighbor Layer Evidence
    # -------------------------------------------------------------
    if hit.get("neighbor"):
        neighbor_base = 52.0
        neighbor_row = details.get("neighbor")
        
        tamper_z = 0.0
        diff_val = 0.0
        num_neighbors = 3
        run_len = 3
        
        if neighbor_row is not None:
            try:
                tamper_z = float(neighbor_row.get("subtle_tampering_score_%", 0.0))
            except (ValueError, TypeError):
                tamper_z = 0.0
            try:
                diff_val = float(neighbor_row.get("diff_val", neighbor_row.get("diff_mm", 0.0)))
            except (ValueError, TypeError):
                diff_val = 0.0
            try:
                num_neighbors = int(neighbor_row.get("num_neighbors", 3))
            except (ValueError, TypeError):
                num_neighbors = 3
            try:
                run_len = int(neighbor_row.get("run_len", 3))
            except (ValueError, TypeError):
                run_len = 3

        diff_bonus = min(15.0, diff_val * 1.5)
        z_bonus = min(10.0, tamper_z / 5.0)
        run_bonus = min(8.0, (run_len - 3) * 2.0)
        neighbor_mag = min(25.0, diff_bonus + z_bonus + run_bonus)
        
        # Uncertainty penalty if no physical neighbor stations were available (fallback mode)
        if num_neighbors == 0 or "self-history" in str(neighbor_row.get("reason", "")):
            penalties += 12.0

        layer_bases.append(neighbor_base)
        layer_magnitudes.append(neighbor_mag)


    # -------------------------------------------------------------
    # 4. ML Layer Evidence (Isolation Forest)
    # -------------------------------------------------------------
    # -------------------------------------------------------------
    # 4. ML Layer Evidence (Isolation Forest)
    # -------------------------------------------------------------
    if hit.get("ml"):
        ml_base = 40.0
        ml_row = details.get("ml")
        anomaly_score = 0.0
        if ml_row is not None and "ml_anomaly_score" in ml_row:
            try:
                anomaly_score = float(ml_row["ml_anomaly_score"])
            except (ValueError, TypeError):
                anomaly_score = 0.0
        
        # Isolation Forest decision_function is negative for outliers.
        # Magnitude bonus scales smoothly with outlier distance from normal distribution.
        ml_mag = min(30.0, max(0.0, (abs(anomaly_score) - 0.005) * 180.0)) if anomaly_score < 0 else 0.0
        
        # Penalty for isolated unconfirmed ML flag (no physics/rule/neighbor confirmation)
        if sum(hit.values()) == 1:
            penalties += 5.0

        layer_bases.append(ml_base)
        layer_magnitudes.append(ml_mag)

    # -------------------------------------------------------------
    # 5. Temporal / Seasonal Layer Evidence
    # -------------------------------------------------------------
    if hit.get("temporal"):
        temporal_base = 30.0
        temporal_row = details.get("temporal")
        temp_score = 0.0
        if temporal_row is not None and "temporal_score" in temporal_row:
            try:
                temp_score = float(temporal_row["temporal_score"])
            except (ValueError, TypeError):
                temp_score = 0.0
        
        temporal_mag = min(15.0, max(0.0, (temp_score - 60.0) * 0.4))

        # Penalty for isolated unconfirmed temporal flag (no physics/rule/neighbor/ml confirmation)
        if sum(hit.values()) == 1:
            penalties += 10.0

        layer_bases.append(temporal_base)
        layer_magnitudes.append(temporal_mag)

    if not layer_bases:
        return 0.0

    # Max single-layer base evidence
    max_base = max(layer_bases)
    
    # Highest individual magnitude bonus
    max_magnitude = max(layer_magnitudes) if layer_magnitudes else 0.0
    
    # Cross-layer agreement (synergy bonus)
    agreeing_layers = len(layer_bases)
    synergy_bonus = 0.0
    if agreeing_layers == 2:
        synergy_bonus = 12.0
    elif agreeing_layers == 3:
        synergy_bonus = 20.0
    elif agreeing_layers >= 4:
        synergy_bonus = 25.0

    raw_score = max_base + max_magnitude + synergy_bonus - penalties
    return float(max(10.0, min(100.0, round(raw_score, 1))))


def combine(rule_df, physics_df, neighbor_df, ml_df, temporal_df=None) -> pd.DataFrame:
    rule_df = _match_key(rule_df)
    physics_df = _match_key(physics_df)
    neighbor_df = _match_key(neighbor_df)
    ml_df = _match_key(ml_df)

    layer_frames = {"rule": rule_df, "physics": physics_df, "neighbor": neighbor_df, "ml": ml_df}
    if temporal_df is not None and not temporal_df.empty:
        layer_frames["temporal"] = _match_key(temporal_df)

    all_keys = set()
    for df in layer_frames.values():
        if not df.empty and "match_key" in df.columns:
            all_keys.update(df["match_key"].tolist())

    results = []
    for key in all_keys:
        station_id, ts_str = key.split("_", 1)

        hit = {}
        details = {}
        for name, df in layer_frames.items():
            if not df.empty and "match_key" in df.columns:
                matched_rows = df[df["match_key"] == key]
                if not matched_rows.empty:
                    hit[name] = True
                    details[name] = matched_rows.iloc[0]
                else:
                    hit[name] = False
                    details[name] = None
            else:
                hit[name] = False
                details[name] = None

        confidence = _calculate_evidence_confidence(hit, details)

        if hit.get("rule"):
            rule_row = details["rule"]
            attribution = "Silent station" if "Silent" in str(rule_row.get("flag_type", "")) else "Sensor fault"
        elif hit.get("physics"):
            attribution = "Physics violation (sensor inconsistency)"
        elif hit.get("neighbor"):
            attribution = "Possible tampering"
        elif hit.get("ml"):
            attribution = "ML-detected anomaly (needs review)"
        elif hit.get("temporal"):
            attribution = "Temporal / seasonal pattern deviation"
        else:
            attribution = "Unknown"

        corrected_value = None
        if hit.get("neighbor") and details.get("neighbor") is not None:
            corrected_value = details["neighbor"].get("corrected_value")

        ml_explanation = None
        if hit.get("ml") and details.get("ml") is not None:
            ml_explanation = details["ml"].get("ml_explanation")

        results.append({
            "station_id": station_id,
            "timestamp": ts_str,
            "attribution": attribution,
            "flagged_by_rule": hit.get("rule", False),
            "flagged_by_physics": hit.get("physics", False),
            "flagged_by_neighbor": hit.get("neighbor", False),
            "flagged_by_ml": hit.get("ml", False),
            "flagged_by_temporal": hit.get("temporal", False),
            "confidence_%": confidence,
            "trust_state": _trust_state(confidence, attribution),
            "alert_priority": _alert_priority(confidence),
            "corrected_value": corrected_value,
            "ml_explanation": ml_explanation,
        })

    if not results:
        return pd.DataFrame(columns=["station_id", "timestamp", "attribution", "confidence_%",
                                      "trust_state", "alert_priority", "corrected_value", "flagged_by_temporal", "ml_explanation"])
    return pd.DataFrame(results).sort_values(["confidence_%", "station_id"], ascending=[False, True])



def compute_recall(final_df: pd.DataFrame, known_anomaly_stations: set) -> dict:
    """Honest accuracy on our synthetic test set - no fake precision claims."""
    detected_stations = set(final_df["station_id"].unique())
    true_positives = len(known_anomaly_stations & detected_stations)
    recall = true_positives / len(known_anomaly_stations) if known_anomaly_stations else 0
    return {
        "known_injected_anomaly_stations": sorted(known_anomaly_stations),
        "detected_stations": sorted(detected_stations),
        "recall_on_synthetic_test_%": round(recall * 100, 1),
        "note": "Precision requires real IMD ground-truth fault records to compute honestly; "
                "this recall figure is measured only against our own injected synthetic faults.",
    }
