"""
test_live_status_json.py - Unit tests for JSON sanitization in /api/live/status
and SendGrid email alert handling.
"""

import os
import math
import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from api import app
from live_service import LivePollingService, live_service_instance
from utils.json_sanitizer import sanitize_for_json
import alerts
import notifications


client = TestClient(app)


def test_sanitize_for_json_direct():
    """Direct unit tests for sanitize_for_json utility function."""
    data = {
        "nan_val": float("nan"),
        "pos_inf": float("inf"),
        "neg_inf": float("-inf"),
        "np_nan": np.nan,
        "np_inf": np.inf,
        "np_float32": np.float32(23.5),
        "np_float64": np.float64(1013.25),
        "np_int64": np.int64(42),
        "valid_float": 15.6,
        "valid_str": "ST01",
        "valid_none": None,
        "nested_dict": {"inner_nan": float("nan")},
        "nested_list": [1.0, float("nan"), float("inf")],
    }

    sanitized = sanitize_for_json(data)

    assert sanitized["nan_val"] is None
    assert sanitized["pos_inf"] is None
    assert sanitized["neg_inf"] is None
    assert sanitized["np_nan"] is None
    assert sanitized["np_inf"] is None
    assert sanitized["np_float32"] == 23.5
    assert isinstance(sanitized["np_float32"], float)
    assert sanitized["np_float64"] == 1013.25
    assert sanitized["np_int64"] == 42
    assert isinstance(sanitized["np_int64"], int)
    assert sanitized["valid_float"] == 15.6
    assert sanitized["valid_str"] == "ST01"
    assert sanitized["valid_none"] is None
    assert sanitized["nested_dict"]["inner_nan"] is None
    assert sanitized["nested_list"] == [1.0, None, None]


def test_live_status_normal():
    """Test 1 — GET /api/live/status returns 200 and valid JSON."""
    response = client.get("/api/live/status")
    assert response.status_code == 200
    json_data = response.json()
    assert "collector_status" in json_data
    assert "latest_telemetry" in json_data
    assert "latest_anomalies" in json_data


def test_live_status_nan_metric():
    """Test 2 — Inject float('nan') metric into live status; returns HTTP 200 with null in JSON."""
    with live_service_instance._lock:
        live_service_instance.latest_telemetry = [
            {"station_id": "ST01", "temperature": float("nan"), "pressure": 1012.5, "humidity": 65.0}
        ]

    response = client.get("/api/live/status")
    assert response.status_code == 200
    json_data = response.json()
    telemetry = json_data["latest_telemetry"]
    assert len(telemetry) >= 1
    assert telemetry[0]["temperature"] is None


def test_live_status_positive_infinity():
    """Test 3 — Inject float('inf') metric into live status; returns HTTP 200 with null in JSON."""
    with live_service_instance._lock:
        live_service_instance.latest_telemetry = [
            {"station_id": "ST01", "temperature": 25.0, "pressure": float("inf"), "humidity": 50.0}
        ]

    response = client.get("/api/live/status")
    assert response.status_code == 200
    json_data = response.json()
    telemetry = json_data["latest_telemetry"]
    assert telemetry[0]["pressure"] is None


def test_live_status_negative_infinity():
    """Test 4 — Inject float('-inf') metric into live status; returns HTTP 200 with null in JSON."""
    with live_service_instance._lock:
        live_service_instance.latest_anomalies = [
            {"station_id": "ST02", "anomaly_score": float("-inf"), "attribution": "Sensor fault"}
        ]

    response = client.get("/api/live/status")
    assert response.status_code == 200
    json_data = response.json()
    anomalies = json_data["latest_anomalies"]
    assert anomalies[0]["anomaly_score"] is None


def test_live_status_numpy_values():
    """Test 5 — Inject NumPy scalar types into live status; returns HTTP 200 with valid JSON types."""
    with live_service_instance._lock:
        live_service_instance.latest_telemetry = [
            {
                "station_id": "ST03",
                "temperature": np.float64(31.2),
                "pressure": np.float32(1008.4),
                "humidity": np.nan,
                "reading_count": np.int64(105),
            }
        ]

    response = client.get("/api/live/status")
    assert response.status_code == 200
    json_data = response.json()
    t = json_data["latest_telemetry"][0]
    assert t["temperature"] == 31.2
    assert t["pressure"] == pytest.approx(1008.4, rel=1e-3)
    assert t["humidity"] is None
    assert t["reading_count"] == 105


def test_live_status_empty_state():
    """Test 6 — Empty live state (no readings/buffers); returns HTTP 200 and valid empty structures."""
    isolated_service = LivePollingService(seed_history=False)
    status = isolated_service.get_status()
    assert status["station_count"] == 0
    assert status["latest_telemetry"] == []
    assert status["latest_anomalies"] == []


def test_live_status_partial_station_data():
    """Test 7 — Partial station data with missing metrics returns nulls for missing attributes."""
    with live_service_instance._lock:
        live_service_instance.latest_telemetry = [
            {
                "station_id": "ST04",
                "timestamp": "2026-09-05T12:00:00",
                "temperature": 28.0,
                "pressure": None,
                "humidity": float("nan"),
            }
        ]

    response = client.get("/api/live/status")
    assert response.status_code == 200
    json_data = response.json()
    t = json_data["latest_telemetry"][0]
    assert t["pressure"] is None
    assert t["humidity"] is None


def test_email_not_configured(capsys):
    """Email Test 1 — SendGrid API key missing -> clear warning logged, no crash."""
    with patch.dict(os.environ, {"SENDGRID_API_KEY": ""}, clear=True):
        alerts.API_KEY = ""
        res = alerts.send_email("Test Alert", "<p>Test</p>")
        assert res is False
        captured = capsys.readouterr()
        assert "EMAIL ALERT: NOT CONFIGURED" in captured.out


def test_sendgrid_mock_send(capsys):
    """Email Test 2 — SendGrid configuration present, mock API client -> send attempt and success logged."""
    env_vars = {
        "SENDGRID_API_KEY": "SG.mock_key_1234567890",
        "SENDGRID_FROM_EMAIL": "alerts@testskyguard.com",
        "ALERT_EMAIL_TO": "operator@testskyguard.com",
    }
    with patch.dict(os.environ, env_vars):
        with patch("alerts.SendGridAPIClient") as mock_sg:
            mock_response = MagicMock()
            mock_response.status_code = 202
            mock_sg.return_value.send.return_value = mock_response

            res = alerts.send_email("CRITICAL ALERT TEST", "<h2>Anomaly detected</h2>")
            assert res is True
            captured = capsys.readouterr()
            assert "EMAIL ALERT: SENDING" in captured.out
            assert "EMAIL ALERT: SENT" in captured.out


def test_sendgrid_api_failure(capsys):
    """Email Test 3 — SendGrid API error -> failure logged, pipeline continues without crash."""
    env_vars = {
        "SENDGRID_API_KEY": "SG.mock_key_invalid",
        "SENDGRID_FROM_EMAIL": "alerts@testskyguard.com",
        "ALERT_EMAIL_TO": "operator@testskyguard.com",
    }
    with patch.dict(os.environ, env_vars):
        with patch("alerts.SendGridAPIClient") as mock_sg:
            mock_sg.return_value.send.side_effect = Exception("401 Unauthorized - Invalid API Key")

            res = alerts.send_email("CRITICAL ALERT TEST", "<h2>Anomaly detected</h2>")
            assert res is False
            captured = capsys.readouterr()
            assert "EMAIL ALERT: FAILED" in captured.out


def test_alert_cooldown(capsys):
    """Email Test 4 — Alert cooldown suppresses duplicate emails within cooldown window."""
    service = LivePollingService(seed_history=False)
    anomaly_reading = {
        "station_id": "ST99",
        "timestamp": "2026-09-05T12:00:00",
        "attribution": "Sensor fault",
        "confidence_%": 90.0,
        "alert_priority": "CRITICAL - High Confidence Anomaly",
    }

    env_vars = {
        "SENDGRID_API_KEY": "SG.mock_key",
        "SENDGRID_FROM_EMAIL": "alerts@test.com",
        "ALERT_EMAIL_TO": "operator@test.com",
    }

    with patch.dict(os.environ, env_vars):
        with patch("alerts.SendGridAPIClient") as mock_sg:
            mock_response = MagicMock()
            mock_response.status_code = 202
            mock_sg.return_value.send.return_value = mock_response

            # First dispatch -> triggers send
            service._handle_alert_dispatch(anomaly_reading, None)
            captured = capsys.readouterr()
            assert "EMAIL ALERT: SENDING" in captured.out

            # Immediate second dispatch -> should be suppressed by cooldown
            service._handle_alert_dispatch(anomaly_reading, None)
            captured2 = capsys.readouterr()
            assert "EMAIL ALERT: COOLDOWN" in captured2.out


def test_critical_anomaly_email_trigger():
    """Email Test 5 — Critical anomaly triggers email alert logic."""
    import pandas as pd

    df = pd.DataFrame([
        {
            "station_id": "ST01",
            "timestamp": "2026-09-05T12:00:00",
            "attribution": "Sensor fault",
            "confidence_%": 85.0,
            "alert_priority": "CRITICAL - High Confidence Anomaly",
        }
    ])

    with patch("alerts.send_email") as mock_send:
        mock_send.return_value = True
        alerts.dispatch_alerts(df)
        assert mock_send.called
        call_args = mock_send.call_args[0]
        assert "CRITICAL" in call_args[0]
