"""
test_core_pipeline.py - Verification tests for Core Meteorological Parameter Dependency.
Tests detection pipeline with ONLY station_id, timestamp, temperature, pressure, humidity.
"""

import pandas as pd
import pytest
from datetime import datetime, timedelta

import data_simulation
from detection import rules, physics, neighbor, ml_model
import fusion
import health_score


def test_normal_reading():
    """Normal reading: Temp=32°C, Pressure=1008 hPa, Humidity=65% -> NORMAL"""
    data = [{
        "station_id": "ST01",
        "timestamp": pd.Timestamp("2026-09-05 10:00:00"),
        "temperature": 32.0,
        "pressure": 1008.0,
        "humidity": 65.0,
    }]
    df = pd.DataFrame(data)

    rule_df = rules.run(df)
    physics_df = physics.run(df)
    neighbor_df = neighbor.run(df)
    
    assert rule_df.empty, "Expected rule layer to find no anomalies for normal reading"
    assert physics_df.empty, "Expected physics layer to find no anomalies for normal reading"


def test_temperature_spike():
    """Temperature spike: Temp=55°C or out of range -> ANOMALY"""
    data = [
        {"station_id": "ST01", "timestamp": pd.Timestamp("2026-09-05 10:00:00"), "temperature": 30.0, "pressure": 1008.0, "humidity": 65.0},
        {"station_id": "ST01", "timestamp": pd.Timestamp("2026-09-05 10:10:00"), "temperature": 55.0, "pressure": 1008.0, "humidity": 95.0},
    ]
    df = pd.DataFrame(data)

    rule_df = rules.run(df)
    physics_df = physics.run(df)
    
    assert not rule_df.empty, "Expected rule layer to flag temperature spike/jump"
    assert any("temperature" in r.lower() for r in rule_df["reason"]), "Expected temperature spike in reason"



def test_humidity_invalid():
    """Humidity invalid: Humidity=150% -> ANOMALY / INVALID SENSOR VALUE"""
    data = [{
        "station_id": "ST01",
        "timestamp": pd.Timestamp("2026-09-05 10:00:00"),
        "temperature": 32.0,
        "pressure": 1008.0,
        "humidity": 150.0,
    }]
    df = pd.DataFrame(data)

    rule_df = rules.run(df)
    assert not rule_df.empty, "Expected rule layer to flag out of range humidity"
    assert "Humidity 150.0% out of range" in rule_df.iloc[0]["reason"]


def test_frozen_sensor_flatline():
    """Frozen sensor: repeated identical Temperature/Pressure/Humidity -> FLATLINE"""
    rows = []
    ts = datetime(2026, 9, 5, 10, 0, 0)
    for _ in range(10):
        rows.append({
            "station_id": "ST01",
            "timestamp": ts,
            "temperature": 29.4,
            "pressure": 1010.0,
            "humidity": 60.0,
        })
        ts += timedelta(minutes=10)

    df = pd.DataFrame(rows)
    rule_df = rules.run(df)

    assert not rule_df.empty, "Expected flatline detector to flag stuck sensor"
    assert any("stuck" in str(r).lower() or "flatline" in str(f).lower() for r, f in zip(rule_df["reason"], rule_df["flag_type"]))


def test_missing_optional_parameters_pipeline():
    """Run complete pipeline with NO rainfall, wind, solar, cloud columns."""
    raw_df = data_simulation.build_dataset(include_optional=False, include_coords=True)
    raw_df = data_simulation.inject_anomalies(raw_df)

    # Verify optional columns are completely absent
    for col in ["rainfall", "wind_speed", "wind_direction", "solar_radiation", "cloud_cover"]:
        assert col not in raw_df.columns

    rule_df = rules.run(raw_df)
    physics_df = physics.run(raw_df)
    neighbor_df = neighbor.run(raw_df)
    ml_df = ml_model.run(raw_df)

    final_df = fusion.combine(rule_df, physics_df, neighbor_df, ml_df)
    assert not final_df.empty, "Expected pipeline to detect injected anomalies without optional parameters"

    # Health score computation
    health_df = health_score.compute_health_scores(raw_df, final_df)
    assert len(health_df) == 10, "Expected health scores for all 10 stations"


if __name__ == "__main__":
    pytest.main(["-v", __file__])
