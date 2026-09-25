"""
live_service.py - Real-Time Polling Service & Temporal State Manager.

Continuously polls Open-Meteo current weather data, maintains a bounded temporal
history (ring buffer) for each station, enforces duplicate reading protection,
runs Phase 1 anomaly detection in real time, logs latency, and handles SendGrid
alert spam prevention with configurable cooldown.
"""

import time
import threading
from collections import deque
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

import config
import live_data_fetcher
from detection import rules, physics, neighbor, ml_model, temporal
from detection.temporal import temporal_engine_instance
import fusion
import health_score
import notifications
import alerts
from utils.json_sanitizer import sanitize_for_json



class LivePollingService:
    def __init__(self, seed_history: bool = True):
        self._lock = threading.Lock()
        self._thread = None
        self._running = False

        # Station temporal state: station_id -> deque of reading dicts (max 200)
        self.station_buffers = {}
        # Duplicate protection set: (station_id, timestamp_str)
        self.processed_timestamps = set()

        # Alert cooldown tracking: (station_id, attribution) -> datetime
        self.last_alert_time = {}

        # Status tracking & persistent live state per station
        self.last_successful_fetch = None
        self.last_api_error = None
        self.latest_live_by_station = {}  # station_id -> latest valid live reading dict
        self.latest_telemetry = []
        self.latest_anomalies = []
        self.latest_health_scores = []

        # Bounded live anomaly event stream across polling cycles (max 100 events)
        self.live_anomaly_history = deque(maxlen=100)
        self.live_anomaly_keys = set()

        # Bounded health history per station (max 100 health records per station)
        self.station_health_history = {}

        # Pre-populate station buffers from aws_data.csv if requested
        if seed_history:
            self._seed_history_from_csv()


    def _seed_history_from_csv(self, filename="aws_data.csv"):
        """Seeds initial station temporal state from existing aws_data.csv if available."""
        import os
        if not os.path.exists(filename):
            return
        try:
            df = pd.read_csv(filename)
            if df.empty:
                return
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            max_len = getattr(config, "STATION_HISTORY_MAX_LEN", 200)

            for station_id, group in df.groupby("station_id"):
                group = group.sort_values("timestamp")
                if station_id not in self.station_buffers:
                    self.station_buffers[station_id] = deque(maxlen=max_len)
                last_row_rec = None
                for _, row in group.iterrows():
                    rec = row.to_dict()
                    rec["timestamp"] = str(rec["timestamp"])
                    self.station_buffers[station_id].append(rec)
                    last_row_rec = rec
                
                # Seed initial baseline state for station if not present
                if last_row_rec and station_id not in self.latest_live_by_station:
                    self.latest_live_by_station[station_id] = {
                        "station_id": station_id,
                        "timestamp": str(last_row_rec.get("timestamp")),
                        "temperature": last_row_rec.get("temperature"),
                        "pressure": last_row_rec.get("pressure"),
                        "humidity": last_row_rec.get("humidity"),
                        "status": "NORMAL",
                        "severity": "NORMAL",
                        "confidence": 95.0,
                        "root_cause": "None",
                        "latency_ms": 0.0,
                        "anomaly_details": None,
                    }
            self.latest_telemetry = list(self.latest_live_by_station.values())

            # Seed initial health calculations across seeded history
            try:
                all_rows = []
                for s_id, s_buf in self.station_buffers.items():
                    all_rows.extend(list(s_buf))
                if all_rows:
                    raw_df = pd.DataFrame(all_rows)
                    raw_df["timestamp"] = pd.to_datetime(raw_df["timestamp"])
                    rule_df = rules.run(raw_df)
                    physics_df = physics.run(raw_df)
                    neighbor_df = neighbor.run(raw_df)
                    try:
                        ml_df = ml_model.run(raw_df)
                    except Exception:
                        ml_df = pd.DataFrame()
                    final_df = fusion.combine(rule_df, physics_df, neighbor_df, ml_df)
                    health_df = health_score.compute_health_scores(raw_df, final_df)

                    enriched_health = []
                    if not health_df.empty:
                        for rec in health_df.to_dict(orient="records"):
                            sid = rec["station_id"]
                            if sid not in self.station_health_history:
                                self.station_health_history[sid] = deque(maxlen=100)
                            
                            st_df = raw_df[raw_df["station_id"] == sid]
                            ts_latest = str(st_df["timestamp"].max()) if not st_df.empty else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            hist_entry = {
                                "station_id": sid,
                                "timestamp": ts_latest,
                                "health_score": rec["health_score"],
                                "status": rec["status"],
                            }
                            self.station_health_history[sid].append(hist_entry)
                            
                            station_hist = list(self.station_health_history[sid])
                            trend_eval = health_score.compute_degradation_trend(station_hist)
                            maint_risk = health_score.compute_maintenance_risk(rec["health_score"], rec["status"], trend_eval["trend"], trend_eval["degradation_rate"])
                            rul_eval = health_score.predict_rul(
                                rec["health_score"],
                                trend_eval["trend"],
                                trend_eval["degradation_rate"],
                                trend_eval["r_squared"],
                                trend_eval["n_observations"]
                            )
                            rec.update({
                                "trend": trend_eval["trend"],
                                "degradation_rate": trend_eval["degradation_rate"],
                                "trend_confidence": trend_eval["trend_confidence"],
                                "maintenance_risk": maint_risk,
                                "rul_days": rul_eval["rul_days"],
                                "rul_label": rul_eval["rul_label"],
                                "rul_confidence": rul_eval["rul_confidence"],
                                "maintenance_threshold": rul_eval["maintenance_threshold"],
                                "health_history": station_hist,
                            })
                            enriched_health.append(rec)
                    self.latest_health_scores = enriched_health
            except Exception as e:
                print(f"[LIVE SERVICE] Notice during health seeding: {e}")
        except Exception as e:
            print(f"[LIVE SERVICE] Notice: could not seed history from {filename}: {e}")

    def process_reading(self, reading: dict) -> dict:
        """
        Processes a single incoming live reading through the full Phase 1 detection pipeline.
        Idempotent: skips duplicate readings if (station_id, timestamp) already processed.
        """
        t_start = time.perf_counter()
        station_id = reading["station_id"]
        ts_str = str(reading["timestamp"])

        with self._lock:
            # 1. Duplicate Data Protection
            if (station_id, ts_str) in self.processed_timestamps:
                # Return duplicate skipped response, but maintain existing persistent telemetry object if present
                dup_res = {
                    "station_id": station_id,
                    "timestamp": ts_str,
                    "temperature": reading.get("temperature"),
                    "pressure": reading.get("pressure"),
                    "humidity": reading.get("humidity"),
                    "status": "DUPLICATE_SKIPPED",
                    "reason": "Reading already processed for this timestamp",
                }
                if station_id not in self.latest_live_by_station:
                    self.latest_live_by_station[station_id] = dup_res
                return dup_res

            # Mark timestamp as processed
            self.processed_timestamps.add((station_id, ts_str))

            # 2. Append to station temporal history (bounded deque)
            max_len = getattr(config, "STATION_HISTORY_MAX_LEN", 200)
            if station_id not in self.station_buffers:
                self.station_buffers[station_id] = deque(maxlen=max_len)
            self.station_buffers[station_id].append(reading)

            # 3. Assemble full multi-station temporal DataFrame from memory
            all_rows = []
            for s_id, s_buf in self.station_buffers.items():
                all_rows.extend(list(s_buf))

            raw_df = pd.DataFrame(all_rows)
            raw_df["timestamp"] = pd.to_datetime(raw_df["timestamp"])

        # 4. Run Phase 1 Detection Layers
        rule_df = rules.run(raw_df)
        physics_df = physics.run(raw_df)
        neighbor_df = neighbor.run(raw_df)
        try:
            ml_df = ml_model.run(raw_df)
        except Exception:
            ml_df = pd.DataFrame()

        temporal_anomalies = []
        for _, row in raw_df.iterrows():
            rec_dict = row.to_dict()
            anom = temporal_engine_instance.detect_anomaly(rec_dict)
            if anom:
                temporal_anomalies.append(anom)
        temporal_df = pd.DataFrame(temporal_anomalies) if temporal_anomalies else pd.DataFrame()

        # 5. Fusion Engine
        final_df = fusion.combine(rule_df, physics_df, neighbor_df, ml_df, temporal_df)

        # 6. Station Health Scoring
        try:
            health_df = health_score.compute_health_scores(raw_df, final_df)
        except Exception:
            health_df = pd.DataFrame()

        elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)

        # Filter anomaly result for this specific station reading
        matched_anomaly = None
        if not final_df.empty:
            target_matches = final_df[
                (final_df["station_id"] == station_id)
                & (final_df["timestamp"].astype(str).str.startswith(ts_str[:16]))
                & (final_df["trust_state"] != "ACCEPT")
            ]
            if not target_matches.empty:
                matched_anomaly = target_matches.iloc[0].to_dict()

        processed_result = {
            "station_id": station_id,
            "timestamp": ts_str,
            "temperature": reading.get("temperature"),
            "pressure": reading.get("pressure"),
            "humidity": reading.get("humidity"),
            "status": "ANOMALY" if matched_anomaly else "NORMAL",
            "severity": matched_anomaly.get("trust_state", "NORMAL") if matched_anomaly else "NORMAL",
            "confidence": matched_anomaly.get("confidence_%", 0.0) if matched_anomaly else 95.0,
            "root_cause": matched_anomaly.get("attribution", "None") if matched_anomaly else "None",
            "latency_ms": elapsed_ms,
            "anomaly_details": matched_anomaly,
        }

        # Save to latest output caches & persistent station telemetry map
        with self._lock:
            if not final_df.empty:
                sorted_anom = final_df.sort_values(by=["timestamp", "confidence_%"], ascending=[False, False])
                self.latest_anomalies = sorted_anom.to_dict(orient="records")
            else:
                self.latest_anomalies = []
            # Enrich health records with history, trend, risk, and RUL
            enriched_health = []
            if not health_df.empty:
                for rec in health_df.to_dict(orient="records"):
                    sid = rec["station_id"]
                    if sid not in self.station_health_history:
                        self.station_health_history[sid] = deque(maxlen=100)
                    
                    hist_entry = {
                        "station_id": sid,
                        "timestamp": ts_str,
                        "health_score": rec["health_score"],
                        "status": rec["status"],
                    }
                    self.station_health_history[sid].append(hist_entry)

                    station_hist = list(self.station_health_history[sid])
                    trend_eval = health_score.compute_degradation_trend(station_hist)
                    maint_risk = health_score.compute_maintenance_risk(rec["health_score"], rec["status"], trend_eval["trend"], trend_eval["degradation_rate"])
                    rul_eval = health_score.predict_rul(
                        rec["health_score"],
                        trend_eval["trend"],
                        trend_eval["degradation_rate"],
                        trend_eval["r_squared"],
                        trend_eval["n_observations"]
                    )
                    rec.update({
                        "trend": trend_eval["trend"],
                        "degradation_rate": trend_eval["degradation_rate"],
                        "trend_confidence": trend_eval["trend_confidence"],
                        "maintenance_risk": maint_risk,
                        "rul_days": rul_eval["rul_days"],
                        "rul_label": rul_eval["rul_label"],
                        "rul_confidence": rul_eval["rul_confidence"],
                        "maintenance_threshold": rul_eval["maintenance_threshold"],
                        "health_history": station_hist,
                    })
                    enriched_health.append(rec)

            self.latest_health_scores = enriched_health
            self.latest_live_by_station[station_id] = processed_result
            self.latest_telemetry = list(self.latest_live_by_station.values())

            # Append to bounded live anomaly event history across polling cycles
            if matched_anomaly:
                anom_key = (station_id, str(matched_anomaly.get("timestamp")))
                ts_str_val = str(matched_anomaly.get("timestamp", ""))
                if anom_key not in self.live_anomaly_keys and not ts_str_val.startswith("2026-08"):
                    self.live_anomaly_keys.add(anom_key)
                    self.live_anomaly_history.append(matched_anomaly)

        # 7. Email Alert Dispatch with Cooldown Spam Protection
        if matched_anomaly:
            self._handle_alert_dispatch(matched_anomaly, final_df)

        status_label = matched_anomaly["trust_state"] if matched_anomaly else "NORMAL"
        print(f"[LIVE METEO] Processed {station_id} reading at {ts_str} in {elapsed_ms} ms | Status: {status_label}")

        return processed_result

    def _handle_alert_dispatch(self, anomaly: dict, final_df: pd.DataFrame):
        """Sends email alert with deduplication and cooldown protection."""
        station_id = anomaly.get("station_id")
        attribution = anomaly.get("attribution", "Unknown")
        confidence = anomaly.get("confidence_%", 0.0)
        cooldown_sec = getattr(config, "LIVE_ALERT_COOLDOWN_SECONDS", 1800)

        if confidence < getattr(config, "ALERT_MEDIUM_CONFIDENCE", 33):
            return

        key = (station_id, attribution)
        now = datetime.now()
        last_sent = self.last_alert_time.get(key)

        if last_sent and (now - last_sent).total_seconds() < cooldown_sec:
            # In cooldown period; skip email dispatch to avoid spam
            remaining = round(cooldown_sec - (now - last_sent).total_seconds())
            print(f"EMAIL ALERT: COOLDOWN - Station {station_id} ({attribution}) alert suppressed by cooldown ({remaining}s remaining).")
            return

        self.last_alert_time[key] = now
        sub_df = pd.DataFrame([anomaly])
        try:
            notifications.route_and_send(sub_df)
        except Exception as e:
            print(f"[LIVE SERVICE] Alert notification failed: {e}")

    def poll_once(self) -> list[dict]:
        """Runs a single live fetch cycle across all configured stations."""
        stations = getattr(live_data_fetcher, "DEFAULT_LIVE_STATIONS", {})
        results = []
        fetch_errors = 0

        for station_id, info in stations.items():
            reading = live_data_fetcher.fetch_live_station_reading(station_id, info["lat"], info["lon"])
            if reading is None:
                fetch_errors += 1
                continue

            res = self.process_reading(reading)
            results.append(res)

        with self._lock:
            if fetch_errors == len(stations) and len(stations) > 0:
                self.last_api_error = f"Failed to reach Open-Meteo API for all {len(stations)} stations"
            else:
                self.last_api_error = None
                self.last_successful_fetch = datetime.now().isoformat()

            # Maintain all persistent live station records, incorporating newly fetched results
            self.latest_telemetry = list(self.latest_live_by_station.values())

        return self.latest_telemetry

    def _polling_loop(self):
        interval = getattr(config, "LIVE_POLL_INTERVAL_SECONDS", 300)
        while self._running:
            try:
                self.poll_once()
            except Exception as e:
                self.last_api_error = str(e)
                print(f"[LIVE SERVICE] Error in polling loop: {e}")

            time.sleep(interval)

    def start_service(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._polling_loop, daemon=True, name="LiveMeteoPollingService")
            self._thread.start()
            print("[LIVE SERVICE] Background live polling service started.")

    def stop_service(self):
        with self._lock:
            self._running = False
            print("[LIVE SERVICE] Stopping background polling service...")

    def get_status(self) -> dict:
        with self._lock:

            if self.last_api_error and not self.last_successful_fetch:
                status_str = "TEMPORARILY UNAVAILABLE"
            elif self.last_api_error:
                status_str = "TEMPORARILY UNAVAILABLE"
            elif self._running:
                status_str = "RUNNING"
            else:
                status_str = "STOPPED"

            last_ts = {}
            for sid, buf in self.station_buffers.items():
                if buf:
                    last_ts[sid] = buf[-1].get("timestamp")

            telemetry_list = self.latest_telemetry if self.latest_telemetry else list(self.latest_live_by_station.values())

            sorted_anom_list = sorted(
                self.latest_anomalies,
                key=lambda x: (str(x.get("timestamp", "")), float(x.get("confidence_%", 0.0))),
                reverse=True
            ) if self.latest_anomalies else []

            history_list = sorted(
                list(self.live_anomaly_history),
                key=lambda x: (str(x.get("timestamp", "")), float(x.get("confidence_%", 0.0))),
                reverse=True
            ) if self.live_anomaly_history else []

            raw_status = {
                "collector_status": status_str,
                "is_running": self._running,
                "poll_interval_seconds": getattr(config, "LIVE_POLL_INTERVAL_SECONDS", 300),
                "last_successful_fetch": self.last_successful_fetch,
                "last_processed_timestamp": last_ts,
                "station_count": len(self.station_buffers),
                "last_api_error": self.last_api_error,
                "latest_telemetry": telemetry_list[:10],
                "latest_anomalies": sorted_anom_list[:10],
                "live_anomaly_history": history_list[:100],
                "latest_health_scores": self.latest_health_scores,
            }
            return sanitize_for_json(raw_status)

    def get_station_history(self, station_id: str = "ST01", limit: int = 50) -> list:
        """Returns bounded recent live observations for a station, sorted oldest -> newest."""
        with self._lock:
            buf = self.station_buffers.get(station_id, deque())
            records = list(buf)
            records = sorted(records, key=lambda x: str(x.get("timestamp", "")))
            if len(records) > limit:
                records = records[-limit:]
            
            history = []
            for r in records:
                history.append({
                    "station_id": r.get("station_id", station_id),
                    "timestamp": str(r.get("timestamp")),
                    "temperature": float(r["temperature"]) if r.get("temperature") is not None else None,
                    "pressure": float(r["pressure"]) if r.get("pressure") is not None else None,
                    "humidity": float(r["humidity"]) if r.get("humidity") is not None else None,
                })
            return sanitize_for_json(history)



# Singleton service instance
live_service_instance = LivePollingService()
