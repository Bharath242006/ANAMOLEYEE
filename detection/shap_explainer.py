"""
detection/shap_explainer.py - SHAP Explanation Layer for Isolation Forest.

Explains why the ML Isolation Forest model flagged an observation as anomalous
without modifying any model predictions, fusion logic, or anomaly decisions.
"""

import math
import pandas as pd
import numpy as np

_EXPLAINER_CACHE = {}

def get_tree_explainer(model):
    """Retrieves or caches a shap.TreeExplainer instance for an IsolationForest model."""
    model_id = id(model)
    if model_id not in _EXPLAINER_CACHE:
        try:
            import shap
            _EXPLAINER_CACHE[model_id] = shap.TreeExplainer(model)
        except Exception:
            return None
    return _EXPLAINER_CACHE.get(model_id)


def explain_observation(model, feature_cols: list, X_row) -> dict:
    """
    Calculates SHAP values for a single observation feature vector.
    
    Parameters:
      model: Trained sklearn IsolationForest model
      feature_cols: list of feature names matching X_row
      X_row: pandas Series, DataFrame (1 row), or dictionary/array of feature values
      
    Returns dict:
      {
        "available": bool,
        "model": "Isolation Forest",
        "top_features": [
           {
             "feature": str,
             "display_name": str,
             "contribution": float,
             "abs_contribution": float,
             "direction": "anomalous" | "normal",
             "importance": "HIGH" | "MEDIUM" | "LOW"
           }, ...
        ],
        "summary": str,
        "reason": str (optional)
      }
    """
    fallback_response = {
        "available": False,
        "model": "Isolation Forest",
        "top_features": [],
        "summary": "ML explanation temporarily unavailable.",
        "reason": "ML explanation temporarily unavailable."
    }

    if model is None or not feature_cols:
        return fallback_response

    try:
        import shap
    except ImportError:
        fallback_response["reason"] = "SHAP package not installed."
        return fallback_response

    try:
        # Convert X_row to 2D DataFrame matching feature_cols
        if isinstance(X_row, pd.Series):
            X_df = X_row.to_frame().T
        elif isinstance(X_row, pd.DataFrame):
            X_df = X_row.copy()
        elif isinstance(X_row, dict):
            X_df = pd.DataFrame([X_row])
        else:
            X_df = pd.DataFrame([X_row], columns=feature_cols)

        # Reindex to exact feature columns & replace invalid numeric values
        for c in feature_cols:
            if c not in X_df.columns:
                X_df[c] = 0.0

        X_df = X_df[feature_cols].replace([float("inf"), float("-inf")], np.nan).fillna(0)
        X_vals = X_df.values.astype(np.float64)

        if np.isnan(X_vals).any() or np.isinf(X_vals).any():
            return fallback_response

        explainer = get_tree_explainer(model)
        if explainer is None:
            explainer = shap.TreeExplainer(model)

        shap_values = explainer.shap_values(X_vals)

        # Handle different output structures of shap_values for IsolationForest
        if isinstance(shap_values, list):
            shap_vec = np.array(shap_values[0])[0]
        elif hasattr(shap_values, "values"):
            shap_vec = np.array(shap_values.values)[0]
        elif shap_values.ndim == 2:
            shap_vec = shap_values[0]
        else:
            shap_vec = np.array(shap_values).flatten()

        if len(shap_vec) != len(feature_cols):
            return fallback_response

        feature_contribs = []
        abs_sum = float(np.sum(np.abs(shap_vec))) or 1.0

        for col, val in zip(feature_cols, shap_vec):
            raw_val = float(val)
            if math.isnan(raw_val) or math.isinf(raw_val):
                raw_val = 0.0
            abs_val = abs(raw_val)
            rel_share = abs_val / abs_sum

            if rel_share >= 0.18:
                importance = "HIGH"
            elif rel_share >= 0.06:
                importance = "MEDIUM"
            else:
                importance = "LOW"

            direction = "anomalous" if raw_val <= 0 else "normal"
            clean_name = col.replace("_", " ").title()

            feature_contribs.append({
                "feature": col,
                "display_name": clean_name,
                "contribution": round(raw_val, 4),
                "abs_contribution": round(abs_val, 4),
                "importance": importance,
                "direction": direction,
            })

        # Rank features by absolute contribution descending
        feature_contribs.sort(key=lambda x: x["abs_contribution"], reverse=True)

        if not feature_contribs:
            return fallback_response

        top_name = feature_contribs[0]["display_name"]
        summary = f"{top_name} had the strongest contribution to the Isolation Forest decision."

        return {
            "available": True,
            "model": "Isolation Forest",
            "top_features": feature_contribs,
            "summary": summary,
        }

    except Exception as e:
        fallback_response["reason"] = f"SHAP calculation exception: {str(e)}"
        return fallback_response
