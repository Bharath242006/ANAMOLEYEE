"""
detection/temporal.py - Station-Specific Temporal & Seasonal Baseline Engine.

Learns normal hour-of-day, day/night, and seasonal baseline conditions for each AWS station
from historical observations (aws_data.csv) and live temporal buffers.

Calculates:
  - Expected temperature, pressure, humidity per station & time bucket
  - Parameter-specific robust deviations (median, MAD, robust z-score)
  - Data sufficiency support states (SUFFICIENT_HISTORY, LIMITED_HISTORY, INSUFFICIENT_HISTORY)
  - Temporal anomaly score (0-100) and Seasonal anomaly score (0-100)
  - Dynamic explainable insight text
"""

import math
from datetime import datetime
import pandas as pd
import numpy as np
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TemporalSeasonalEngine:
    def __init__(self, data_path=None):
        self.data_path = data_path or os.path.join(BASE_DIR, "aws_data.csv")
        self.station_hourly_baselines = {}
        self.station_monthly_baselines = {}
        self.is_trained = False
        self.train_baseline()

    def train_baseline(self, additional_df: pd.DataFrame = None):
        """
        Trains station-specific hourly and monthly baselines using robust statistics (median & MAD).
        Validates quality, rejects NaN/Inf/physically invalid records.
        """
        df_list = []
        if os.path.exists(self.data_path):
            try:
                hist_df = pd.read_csv(self.data_path)
                if not hist_df.empty:
                    df_list.append(hist_df)
            except Exception as e:
                print(f"[TEMPORAL ENGINE] Error reading historical CSV: {e}")

        if additional_df is not None and not additional_df.empty:
            df_list.append(additional_df)

        if not df_list:
            print("[TEMPORAL ENGINE] Warning: No training data available.")
            return

        full_df = pd.concat(df_list, ignore_index=True)

        # 1. Data Quality Filtering
        required_cols = ["station_id", "timestamp", "temperature", "pressure", "humidity"]
        for col in required_cols:
            if col not in full_df.columns:
                print(f"[TEMPORAL ENGINE] Missing column {col} in dataset.")
                return

        full_df = full_df.dropna(subset=required_cols)
        full_df["timestamp"] = pd.to_datetime(full_df["timestamp"], errors="coerce")
        full_df = full_df.dropna(subset=["timestamp"])

        # Physical range validation
        full_df = full_df[
            (full_df["temperature"] >= -50) & (full_df["temperature"] <= 60) &
            (full_df["pressure"] >= 800) & (full_df["pressure"] <= 1100) &
            (full_df["humidity"] >= 0) & (full_df["humidity"] <= 100)
        ]

        if full_df.empty:
            print("[TEMPORAL ENGINE] No valid data records after quality filtering.")
            return

        # Extract temporal features
        full_df["hour"] = full_df["timestamp"].dt.hour
        full_df["month"] = full_df["timestamp"].dt.month

        # 2. Hourly Baselines per Station
        self.station_hourly_baselines = {}
        for (st_id, hr), group in full_df.groupby(["station_id", "hour"]):
            if len(group) == 0:
                continue

            t_med = float(group["temperature"].median())
            t_mad = float((group["temperature"] - t_med).abs().median()) or 1.0

            p_med = float(group["pressure"].median())
            p_mad = float((group["pressure"] - p_med).abs().median()) or 1.5

            h_med = float(group["humidity"].median())
            h_mad = float((group["humidity"] - h_med).abs().median()) or 3.0

            self.station_hourly_baselines[(st_id, hr)] = {
                "station_id": st_id,
                "hour": hr,
                "sample_count": len(group),
                "temperature": {"median": t_med, "mad": t_mad},
                "pressure": {"median": p_med, "mad": p_mad},
                "humidity": {"median": h_med, "mad": h_mad},
            }

        # 3. Monthly Baselines per Station
        self.station_monthly_baselines = {}
        for (st_id, mo), group in full_df.groupby(["station_id", "month"]):
            if len(group) == 0:
                continue

            t_med = float(group["temperature"].median())
            t_mad = float((group["temperature"] - t_med).abs().median()) or 1.5

            p_med = float(group["pressure"].median())
            p_mad = float((group["pressure"] - p_med).abs().median()) or 2.0

            h_med = float(group["humidity"].median())
            h_mad = float((group["humidity"] - h_med).abs().median()) or 4.0

            self.station_monthly_baselines[(st_id, mo)] = {
                "station_id": st_id,
                "month": mo,
                "sample_count": len(group),
                "temperature": {"median": t_med, "mad": t_mad},
                "pressure": {"median": p_med, "mad": p_mad},
                "humidity": {"median": h_med, "mad": h_mad},
            }

        self.is_trained = True
        print(f"[TEMPORAL ENGINE] Trained station baselines across {len(self.station_hourly_baselines)} station-hour buckets & {len(self.station_monthly_baselines)} station-month buckets.")

    def _get_smoothed_hourly_baseline(self, station_id: str, hour: int) -> dict:
        """Rolling 3-hour window smoothing for temporal baselines (hour-1, hour, hour+1)."""
        hours_to_check = [(hour - 1) % 24, hour, (hour + 1) % 24]
        buckets = [self.station_hourly_baselines.get((station_id, h)) for h in hours_to_check]
        valid_buckets = [b for b in buckets if b is not None]

        if not valid_buckets:
            return None

        main_bucket = self.station_hourly_baselines.get((station_id, hour))
        if main_bucket and main_bucket["sample_count"] >= 5:
            return main_bucket

        t_meds = [b["temperature"]["median"] for b in valid_buckets]
        t_mads = [b["temperature"]["mad"] for b in valid_buckets]
        p_meds = [b["pressure"]["median"] for b in valid_buckets]
        p_mads = [b["pressure"]["mad"] for b in valid_buckets]
        h_meds = [b["humidity"]["median"] for b in valid_buckets]
        h_mads = [b["humidity"]["mad"] for b in valid_buckets]

        total_samples = sum(b["sample_count"] for b in valid_buckets)

        return {
            "station_id": station_id,
            "hour": hour,
            "sample_count": total_samples,
            "temperature": {"median": float(np.median(t_meds)), "mad": float(np.median(t_mads)) or 1.0},
            "pressure": {"median": float(np.median(p_meds)), "mad": float(np.median(p_mads)) or 1.5},
            "humidity": {"median": float(np.median(h_meds)), "mad": float(np.median(h_mads)) or 3.0},
        }

    def _evaluate_param(self, actual, expected_median, mad, param_type: str = "temperature") -> dict:
        if actual is None or math.isnan(actual) or math.isinf(actual):
            return {"expected": round(expected_median, 1) if expected_median is not None else None, "actual": None, "deviation": None, "robust_z": 0.0, "status": "NO_DATA"}

        actual_val = float(actual)
        expected_val = float(expected_median)
        diff = actual_val - expected_val

        # Safe MAD Floors & Material Absolute Deviation Thresholds per parameter
        mad_floors = {
            "temperature": 2.5,
            "pressure": 3.5,
            "humidity": 8.0,
        }
        material_thresholds = {
            "temperature": 6.0,
            "pressure": 12.0,
            "humidity": 25.0,
        }

        mad_floor = mad_floors.get(param_type, 2.5)
        mat_thresh = material_thresholds.get(param_type, 6.0)

        effective_mad = max(float(mad) if mad else mad_floor, mad_floor)
        denom = 1.4826 * effective_mad + 1e-5
        robust_z = abs(diff) / denom

        status = "NORMAL"
        if robust_z > 4.0 and abs(diff) >= mat_thresh:
            status = "ABNORMAL"
        elif robust_z > 2.5 and abs(diff) >= (mat_thresh / 2.0):
            status = "ELEVATED"

        return {
            "expected": round(expected_val, 1),
            "actual": round(actual_val, 1),
            "deviation": round(diff, 1),
            "robust_z": round(robust_z, 2),
            "status": status
        }

    def _build_explanation(self, station_id, ts, day_night, res_t, res_p, res_h, pattern_status):
        ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)
        if pattern_status == "NORMAL":
            return f"Station {station_id} observations at {ts_str} UTC ({day_night}) match learned hourly baseline expectations."

        abnormal_params = []
        if res_t["status"] != "NORMAL" and res_t["deviation"] is not None:
            sign = "+" if res_t["deviation"] > 0 else ""
            abnormal_params.append(f"Temperature ({sign}{res_t['deviation']}°C vs expected {res_t['expected']}°C)")
        if res_p["status"] != "NORMAL" and res_p["deviation"] is not None:
            sign = "+" if res_p["deviation"] > 0 else ""
            abnormal_params.append(f"Pressure ({sign}{res_p['deviation']} hPa vs expected {res_p['expected']} hPa)")
        if res_h["status"] != "NORMAL" and res_h["deviation"] is not None:
            sign = "+" if res_h["deviation"] > 0 else ""
            abnormal_params.append(f"Humidity ({sign}{res_h['deviation']}% vs expected {res_h['expected']}%)")

        if abnormal_params:
            return f"Station {station_id} exhibits {pattern_status.lower()}: " + ", ".join(abnormal_params) + "."
        return f"Station {station_id} shows mild temporal variation relative to learned baseline."

    def get_expected_conditions(self, station_id: str, timestamp_val, actual_t=None, actual_p=None, actual_h=None) -> dict:
        """
        Calculates expected conditions, deviations, and temporal anomaly scores for a station at a timestamp.
        """
        try:
            if isinstance(timestamp_val, str):
                ts = pd.to_datetime(timestamp_val)
            elif isinstance(timestamp_val, (datetime, pd.Timestamp)):
                ts = timestamp_val
            else:
                ts = pd.to_datetime(str(timestamp_val))
        except Exception:
            ts = pd.Timestamp.now()

        hour = ts.hour if hasattr(ts, "hour") else 12
        month = ts.month if hasattr(ts, "month") else 8
        day_night_state = "DAY" if 6 <= hour < 18 else "NIGHT"

        h_base = self._get_smoothed_hourly_baseline(station_id, hour)
        m_base = self.station_monthly_baselines.get((station_id, month))

        h_count = h_base.get("sample_count", 0) if h_base else 0
        m_count = m_base.get("sample_count", 0) if m_base else 0

        temporal_support = "SUFFICIENT_HISTORY" if h_count >= 20 else ("LIMITED_HISTORY" if h_count >= 5 else "INSUFFICIENT_HISTORY")
        seasonal_support = "SUFFICIENT_HISTORY" if m_count >= 30 else ("LIMITED_HISTORY" if m_count >= 10 else "INSUFFICIENT_HISTORY")

        if not h_base:
            return {
                "station_id": station_id,
                "timestamp": str(ts),
                "day_night_state": day_night_state,
                "temporal_support": "INSUFFICIENT_HISTORY",
                "seasonal_support": "INSUFFICIENT_HISTORY",
                "temperature": {"expected": None, "actual": actual_t, "deviation": None, "robust_z": 0.0, "status": "INSUFFICIENT_HISTORY"},
                "pressure": {"expected": None, "actual": actual_p, "deviation": None, "robust_z": 0.0, "status": "INSUFFICIENT_HISTORY"},
                "humidity": {"expected": None, "actual": actual_h, "deviation": None, "robust_z": 0.0, "status": "INSUFFICIENT_HISTORY"},
                "temporal_score": 0.0,
                "seasonal_score": None,
                "combined_score": 0.0,
                "pattern_status": "INSUFFICIENT_HISTORY",
                "explanation": f"Insufficient historical observations to compute expected baseline for station {station_id}."
            }

        res_t = self._evaluate_param(actual_t, h_base["temperature"]["median"], h_base["temperature"]["mad"], param_type="temperature")
        res_p = self._evaluate_param(actual_p, h_base["pressure"]["median"], h_base["pressure"]["mad"], param_type="pressure")
        res_h = self._evaluate_param(actual_h, h_base["humidity"]["median"], h_base["humidity"]["mad"], param_type="humidity")

        max_z = max(res_t["robust_z"], res_p["robust_z"], res_h["robust_z"])
        temporal_score = min(100.0, round(max(0.0, (max_z - 1.5) * 28.5), 1)) if max_z > 1.5 else 0.0

        seasonal_score = None
        if m_base and seasonal_support != "INSUFFICIENT_HISTORY":
            s_t = self._evaluate_param(actual_t, m_base["temperature"]["median"], m_base["temperature"]["mad"], param_type="temperature")
            s_p = self._evaluate_param(actual_p, m_base["pressure"]["median"], m_base["pressure"]["mad"], param_type="pressure")
            s_h = self._evaluate_param(actual_h, m_base["humidity"]["median"], m_base["humidity"]["mad"], param_type="humidity")
            s_max_z = max(s_t["robust_z"], s_p["robust_z"], s_h["robust_z"])
            seasonal_score = min(100.0, round(max(0.0, (s_max_z - 1.5) * 28.5), 1)) if s_max_z > 1.5 else 0.0

        combined_score = temporal_score if seasonal_score is None else round(0.7 * temporal_score + 0.3 * seasonal_score, 1)

        pattern_status = "NORMAL"
        if combined_score >= 60.0 and any(r["status"] == "ABNORMAL" for r in [res_t, res_p, res_h]):
            pattern_status = "ABNORMAL DEVIATION"
        elif combined_score >= 35.0 and any(r["status"] != "NORMAL" for r in [res_t, res_p, res_h]):
            pattern_status = "ELEVATED DEVIATION"

        explanation = self._build_explanation(station_id, ts, day_night_state, res_t, res_p, res_h, pattern_status)

        return {
            "station_id": station_id,
            "timestamp": str(ts),
            "day_night_state": day_night_state,
            "temporal_support": temporal_support,
            "seasonal_support": seasonal_support,
            "temperature": res_t,
            "pressure": res_p,
            "humidity": res_h,
            "temporal_score": temporal_score,
            "seasonal_score": seasonal_score,
            "combined_score": combined_score,
            "pattern_status": pattern_status,
            "explanation": explanation,
        }

    def detect_anomaly(self, reading: dict) -> dict:
        """
        Runs Temporal Layer Anomaly Detection on a single reading dict.
        Returns detection dict for integration into fusion.py ONLY when
        supported by sufficient history, material deviation, and high combined score.
        """
        st_id = reading.get("station_id")
        ts = reading.get("timestamp")
        t = reading.get("temperature")
        p = reading.get("pressure")
        h = reading.get("humidity")

        cond = self.get_expected_conditions(st_id, ts, t, p, h)

        # Conservative false positive protection:
        # 1. Must have SUFFICIENT_HISTORY (never trigger on LIMITED or INSUFFICIENT history)
        # 2. Combined score must exceed conservative threshold (>= 75.0)
        # 3. At least one core parameter must be ABNORMAL (material deviation & robust_z > 4.0)
        is_sufficient = cond.get("temporal_support") == "SUFFICIENT_HISTORY"
        has_abnormal_param = any(
            cond.get(param, {}).get("status") == "ABNORMAL"
            for param in ["temperature", "pressure", "humidity"]
        )
        strong_score = cond.get("combined_score", 0.0) >= 75.0

        is_anomaly = is_sufficient and has_abnormal_param and strong_score

        if is_anomaly:
            return {
                "station_id": st_id,
                "timestamp": str(ts),
                "flag_type": "Temporal Deviation",
                "is_temporal_anomaly": True,
                "temporal_score": cond["combined_score"],
                "reason": cond["explanation"],
                "expected_conditions": cond
            }
        return None


# Global singleton instance
temporal_engine_instance = TemporalSeasonalEngine()
