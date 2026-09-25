"""
api.py - Backend API server for the Dashboard.

Serves the pipeline's CSV outputs (final_report.csv, health_scores.csv)
as JSON over HTTP, and handles login + role-based filtering, so the
dashboard (static/dashboard.html) is a real "live" frontend instead of
a static file viewer.

Run: python api.py
Then open http://localhost:8000 in a browser.

Requires main.py to have been run at least once (so final_report.csv,
health_scores.csv exist).
"""

import os
import json
import ast
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

import notifications  # reuses the same USERS list + station-region mapping
import config
from detection import rules, physics, neighbor, ml_model
import fusion
from live_service import live_service_instance
from detection.temporal import temporal_engine_instance
from utils.json_sanitizer import sanitize_for_json


app = FastAPI(title="SIH26073 AWS Anomaly Detection API")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    if getattr(config, "LIVE_METEO_ENABLED", True):
        print("[API] Initializing background live Open-Meteo polling service...")
        live_service_instance.start_service()


class LoginRequest(BaseModel):
    username: str
    password: str

class TelemetryInput(BaseModel):
    station_id: str
    timestamp: str
    temperature: float
    pressure: float
    humidity: float
    lat: float | None = None
    lon: float | None = None
    rainfall: float | None = None
    wind_speed: float | None = None
    wind_direction: float | None = None
    solar_radiation: float | None = None
    cloud_cover: float | None = None


# Simple demo credentials - maps to notifications.USERS by role.
# In production this would be a real user database with hashed passwords.
DEMO_LOGINS = {
    "admin": {"password": "admin123", "role": "admin", "name": "DDG Delhi"},
    "operator": {"password": "operator123", "role": "regional_operator", "name": "Met Officer Chennai", "region": "south"},
    "technician": {"password": "tech123", "role": "field_technician", "name": "Field Tech Team"},
    "forecaster": {"password": "forecast123", "role": "forecaster", "name": "Forecaster Delhi"},
    "viewer": {"password": "viewer123", "role": "viewer", "name": "Public Viewer"},
}


def _parse_ml_explanation(val):
    """
    Safely deserializes ml_explanation from native dict, JSON string,
    or Python dict repr string (from CSV storage) into a JSON-compliant dict.
    Returns None if deserialization fails or value is missing.
    """
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass

    if isinstance(val, dict):
        return val

    if isinstance(val, str):
        val_str = val.strip()
        if not val_str or val_str.lower() in ("none", "null", "nan", "undefined"):
            return None
        # 1. Standard JSON string
        try:
            res = json.loads(val_str)
            if isinstance(res, dict):
                return res
        except Exception:
            pass
        # 2. Python dict literal string (ast.literal_eval avoids unsafe eval)
        try:
            res = ast.literal_eval(val_str)
            if isinstance(res, dict):
                return res
        except Exception:
            pass

    return None


def _load_csv(filename: str) -> pd.DataFrame:
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    # Force object dtype before replacing NaN with None - pandas silently
    # reverts None back to NaN on float-typed columns otherwise, which
    # crashes FastAPI's JSON encoder ("Out of range float values...").
    df = df.astype(object).where(pd.notna(df), None)
    if "ml_explanation" in df.columns:
        df["ml_explanation"] = df["ml_explanation"].apply(_parse_ml_explanation)
    return df


def _filter_for_role(df: pd.DataFrame, role: str, region: str = None) -> pd.DataFrame:
    """Same routing logic as notifications.py, reused here so the
    dashboard shows each role exactly what they'd be emailed about."""
    if df.empty or role == "admin":
        return df
    if role == "regional_operator":
        region_stations = [s for s, r in notifications.STATION_REGION.items() if r == region]
        return df[df["station_id"].isin(region_stations)]
    if role == "field_technician":
        return df[df["attribution"].isin(notifications.MAINTENANCE_ATTRIBUTIONS)]
    if role == "forecaster":
        return df[df["attribution"].isin(notifications.WEATHER_ATTRIBUTIONS)]
    return df.iloc[0:0]  # viewer: no anomaly details, dashboard summary only


@app.post("/api/login")
def login(req: LoginRequest):
    user = DEMO_LOGINS.get(req.username)
    if not user or user["password"] != req.password:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {
        "username": req.username,
        "name": user["name"],
        "role": user["role"],
        "region": user.get("region"),
    }


@app.post("/api/detect")
def detect_single_reading(data: TelemetryInput):
    record = data.dict(exclude_none=True)
    df = pd.DataFrame([record])
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    rule_df = rules.run(df)
    physics_df = physics.run(df)
    neighbor_df = neighbor.run(df)
    try:
        ml_df = ml_model.run(df)
    except Exception:
        ml_df = pd.DataFrame()

    final_df = fusion.combine(rule_df, physics_df, neighbor_df, ml_df)

    if not final_df.empty:
        res = final_df.iloc[0].to_dict()
        layers = []
        if res.get("flagged_by_rule"): layers.append("Rule Engine")
        if res.get("flagged_by_physics"): layers.append("Physics Layer")
        if res.get("flagged_by_neighbor"): layers.append("Spatial Neighbor")
        if res.get("flagged_by_ml"): layers.append("ML Model")

        return {
            "station_id": res["station_id"],
            "timestamp": str(res["timestamp"]),
            "is_anomaly": True,
            "severity": res.get("trust_state", "CAUTION"),
            "root_cause": res.get("attribution", "Sensor fault"),
            "confidence_score": res.get("confidence_%", 0.0),
            "evidence_score": res.get("confidence_%", 0.0),
            "detection_layers": layers,
            "explanation": f"Flagged as {res.get('attribution')} with {res.get('confidence_%')}% confidence.",
            "health_impact": "Station maintenance recommended" if res.get("confidence_%", 0) > 60 else "Increased monitoring suggested",
            "corrected_value": res.get("corrected_value")
        }
    else:
        return {
            "station_id": data.station_id,
            "timestamp": data.timestamp,
            "is_anomaly": False,
            "severity": "NORMAL",
            "root_cause": "None",
            "confidence_score": 0.0,
            "evidence_score": 0.0,
            "detection_layers": [],
            "explanation": "All core parameters (Temperature, Pressure, Humidity) are within normal physical limits.",
            "health_impact": "Station operating normally",
            "corrected_value": None
        }


@app.get("/api/anomalies")
def get_anomalies(role: str = "admin", region: str = None):
    df = _load_csv("final_report.csv")
    df = _filter_for_role(df, role, region)
    records = df.to_dict(orient="records")
    for rec in records:
        if "ml_explanation" in rec:
            rec["ml_explanation"] = _parse_ml_explanation(rec["ml_explanation"])
    return sanitize_for_json(records)


@app.get("/api/health-scores")
def get_health_scores():
    df = _load_csv("health_scores.csv")
    return df.to_dict(orient="records")


@app.get("/api/system-status")
def get_system_status():
    """Powers the small green/red 'system health' indicator in the header."""
    checks = {
        "aws_data.csv": os.path.exists(os.path.join(BASE_DIR, "aws_data.csv")),
        "final_report.csv": os.path.exists(os.path.join(BASE_DIR, "final_report.csv")),
        "health_scores.csv": os.path.exists(os.path.join(BASE_DIR, "health_scores.csv")),
    }
    all_ok = all(checks.values())
    return {"status": "ok" if all_ok else "incomplete", "checks": checks}


@app.get("/api/comparison")
def get_comparison():
    """Namma-vs-existing-systems data for the About/Research tab."""
    path = os.path.join(BASE_DIR, "comparison_data.json")
    if not os.path.exists(path):
        return {"error": "comparison_data.json not found"}
    import json
    with open(path) as f:
        return json.load(f)


@app.get("/api/telemetry")
def get_telemetry():
    """Returns recent raw AWS telemetry observations from aws_data.csv."""
    df = _load_csv("aws_data.csv")
    if df.empty:
        return []
    return df.tail(20).to_dict(orient="records")



@app.get("/api/live/status")
def get_live_status():
    """Returns live collector status, last fetch time, error logs, and recent telemetry."""
    return sanitize_for_json(live_service_instance.get_status())


@app.post("/api/live/poll")
def poll_live_now():
    """Triggers an immediate live weather fetch cycle."""
    results = live_service_instance.poll_once()
    return sanitize_for_json({"status": "polled", "readings_count": len(results), "results": results})


@app.get("/api/live/history")
def get_live_history(station_id: str = "ST01", limit: int = 50):
    """Returns actual recent live observations for a station, sorted oldest -> newest."""
    history = live_service_instance.get_station_history(station_id=station_id, limit=limit)
    return sanitize_for_json({"station_id": station_id, "samples": history})


@app.get("/api/live/expected")
def get_live_expected(station_id: str = "ST01"):
    """Returns expected vs actual temporal & seasonal conditions for a station."""
    status = live_service_instance.get_status()
    telemetry = status.get("latest_telemetry", [])
    matched = next((r for r in telemetry if r and r.get("station_id") == station_id), None)

    if not matched:
        buf = live_service_instance.station_buffers.get(station_id)
        if buf and len(buf) > 0:
            matched = buf[-1]

    ts = matched.get("timestamp") if matched else str(pd.Timestamp.now())
    act_t = matched.get("temperature") if matched else None
    act_p = matched.get("pressure") if matched else None
    act_h = matched.get("humidity") if matched else None

    expected_data = temporal_engine_instance.get_expected_conditions(
        station_id=station_id,
        timestamp_val=ts,
        actual_t=act_t,
        actual_p=act_p,
        actual_h=act_h
    )
    return sanitize_for_json(expected_data)






# Serve the dashboard itself at the root URL
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    print("Starting dashboard server...")
    print("Open this in your browser: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)

