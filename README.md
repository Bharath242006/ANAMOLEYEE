# SIH26073 - AI/ML-Based Intelligent Anomaly Detection for Automatic Weather Stations

Ministry of Earth Sciences | Smart India Hackathon 2026 | Disaster Management

## What this is

A layered detection system for Automatic Weather Station (AWS) data that
doesn't just flag "wrong values" - it identifies WHY a reading is wrong
(sensor fault, physics-impossible combination, tampering, or a genuine
extreme-weather event), how confident it is, who should be notified, and
what to do about it.

Built to address two real, documented Indian problems that existing
international systems (Hong Kong Observatory, China's MDC/EOF methods,
Belgium's rule-based QC, DeepQC/LSTM) don't specifically solve:
- Stations going silent for weeks unnoticed (Gurugram, 2018 - missed
  128mm of rainfall because the AWS had been dead for 20-25 days)
- Sensor tampering for crop-insurance fraud (Maharashtra - now monitored
  with 2,092 CCTV cameras instead of software detection)

## Architecture

```
Data --> [Rules | Physics | Neighbor-compare | ML model] (parallel)
              --> Fusion (attribution + confidence + trust state)
              --> Health scores + Role-based alert routing
```

## Three data sources, on purpose

| Source | Command | Why |
|---|---|---|
| Synthetic (default) | `python main.py` | Fully fake, no internet needed. Has 5 KNOWN, planted faults - proves detection accuracy (we can measure recall because we know the right answer) |
| Real (Open-Meteo) | `python real_data_fetcher.py` then `python main.py --data real` | 50 representative Indian locations, 365 days hourly, 8 parameters. No known faults exist in real weather data, so recall/precision can't be measured - the pipeline says so honestly instead of faking a number. Proves the pipeline runs cleanly on real-world data. |
| **Hybrid (strongest test)** | `python real_data_fetcher.py` then `python main.py --data hybrid` | Real weather as the baseline (realistic correlations between temperature/humidity/pressure/etc.) + the SAME 5 known faults injected on top (`hybrid_data.py`). Gives us both realism AND a known ground truth - the most credible accuracy claim we can honestly make. |

Dew point is calculated locally (not fetched) using the Sonntag/Magnus
formula, and `validate_dew_point.py` checks our calculation against
Open-Meteo's own `dew_point_2m` field to confirm accuracy (run it to see
the mean/median/max error - typically well under 0.5C).

## Why we didn't add a separate radar/satellite layer

We researched free options (NASA GPM IMERG - satellite precipitation,
free via Google Earth Engine). Open-Meteo's archive API already blends
satellite (GPM) and ground-station data internally, so we get
satellite-corrected precipitation accuracy without needing a second,
separate integration. This is documented honestly rather than claimed
as a from-scratch radar integration.

## Project structure

```
config.py                  All thresholds in one place (tunable per region/season)
data_simulation.py         Synthetic AWS data generator (10 stations, 5 planted faults)
real_data_fetcher.py       Real historical weather from Open-Meteo (50 locations, 365 days, hourly)
validate_dew_point.py      Validates our physics formula against Open-Meteo's own dew point
detection/
    rules.py                 Layer 1: range, flatline, silent-station checks (seasonal thresholds)
    physics.py                 Dew-point + rolling-deviation physical consistency checks
    neighbor.py                  Layer 2: spatial cross-check + tampering + corrected value
    ml_model.py                   Layer 3: Isolation Forest + concept-drift check
fusion.py                  Combines all layers: attribution, confidence %, trust state
health_score.py             Multi-factor health scoring + remaining-life prediction
notifications.py            Role-based alert routing (Admin/Regional Operator/Field Tech/Forecaster)
alerts.py                    Priority-based SendGrid alerts (critical vs digest vs log-only)
utils/buffering.py            Local buffering for offline/connectivity gaps
api.py                       Backend API for the dashboard (FastAPI) - login,
                              role-filtered anomalies, health scores, system status
static/index.html             The dashboard itself (login + 4 tabs) - self-contained
                               HTML/JS, no build step, served by api.py
main.py                     Runs the full detection pipeline end-to-end (--data synthetic|real|hybrid)
```

## Running it (backend + frontend, one app)

```bash
pip install -r requirements.txt

# Step 1: Generate data and run detection (choose one)
python main.py                    # synthetic (default)
python real_data_fetcher.py && python main.py --data real     # real Open-Meteo data
python real_data_fetcher.py && python main.py --data hybrid   # real baseline + known faults

# Step 2: Start the dashboard (backend API + frontend + live polling service, all served by api.py)
python api.py
```

## Live Open-Meteo Integration (Phase 2)

SkyGuard AI continuously ingests and analyzes real-time live weather parameters:
- **Live Parameters**: Temperature (°C), Atmospheric Pressure (hPa), Relative Humidity (%)
- **Historical Archive**: `real_data_fetcher.py` remains available for training & historical evaluation.
- **Background Polling Service**: `live_service.py` runs automatically when `api.py` starts (`LIVE_METEO_ENABLED=True`).
- **Configurable Settings**:
  - `LIVE_POLL_INTERVAL_SECONDS = 300` (5-minute poll interval)
  - `OPEN_METEO_TIMEOUT_SECONDS = 10`
  - `LIVE_ALERT_COOLDOWN_SECONDS = 1800` (30-minute alert cooldown per station & fault category)
- **Live Endpoints**:
  - `GET /api/live/status`: Exposes collector status, last fetch time, error logs, and recent telemetry.
  - `POST /api/live/poll`: Triggers an immediate live weather fetch cycle on demand.


Then open **http://localhost:8000** in a browser. Demo logins (role-based):

| Username | Password | Role |
|---|---|---|
| admin | admin123 | Deputy Director General (sees everything) |
| operator | operator123 | Regional Officer (south region stations only) |
| technician | tech123 | Field Technician (maintenance issues only) |
| forecaster | forecast123 | Forecaster (weather-pattern flags only) |
| viewer | viewer123 | Public/researcher (summary only) |

The dashboard has 4 tabs: **Overview** (KPI cards + top anomalies), **Anomalies**
(full filtered table with confidence and trust-state badges), **Station Health**
(multi-factor scores + remaining-life predictions), and **About/Research**
(comparison against existing international systems).

No `npm`/Node.js needed - the frontend is a single self-contained HTML file
(`static/index.html`) using Tailwind via CDN, served directly by the same
Python backend (`api.py`, built with FastAPI).

## Role-based access (matches real IMD/MoES structure)

Researched actual IMD organizational hierarchy (Director General of
Meteorology, Regional Meteorological Centres headed by Deputy Director
Generals, Instrumentation Division, Forecasting Offices) and mapped our
system roles to it, instead of inventing generic "Admin/User" labels:

| Our Role | Maps To | Gets Notified About |
|---|---|---|
| Admin | Deputy Director General / Regional Head | Everything |
| Regional Operator | State Meteorological Centre Officer | Their region's stations only |
| Field Technician | Instrumentation Division staff | Maintenance/sensor-fault issues only |
| Forecaster | Forecasting Office staff | Weather-pattern-relevant flags only |
| Viewer | Public/researcher | Dashboard read-only, no alerts |

## Honest limitations (documented, not hidden)

- Precision cannot be honestly computed on real data without real
  IMD ground-truth fault records - only recall on our own synthetic
  planted faults is reported, and the code says so explicitly.
- No live radar integration - see "Why we didn't add a separate
  radar/satellite layer" above; Open-Meteo already blends this.
- Dashboard (React), login UI, and multi-language support are a
  separate frontend layer, not covered by this backend pipeline.
- Full production hardening (server redundancy, encrypted DB, audit
  logging, legal/DPDP Act compliance review) is future-deployment scope,
  not a hackathon-week deliverable - flagged honestly rather than
  claimed as done.

## Team module ownership (suggested for a 6-person team)

| Member | Owns |
|---|---|
| 1 | `data_simulation.py`, `real_data_fetcher.py`, `config.py` |
| 2 | `detection/rules.py`, `detection/physics.py`, `validate_dew_point.py` |
| 3 | `detection/neighbor.py`, `detection/ml_model.py` |
| 4 | `fusion.py`, `health_score.py` |
| 5 | Dashboard (React) - login, confidence/trust-state display |
| 6 | `alerts.py`, `notifications.py`, `utils/buffering.py`, integration lead (GitHub, `main.py`, testing) |
