"""
notifications.py - Role-based notification routing.

Maps our system's roles (which mirror real IMD organizational
structure - see README) to WHAT each role should be notified about,
so people aren't spammed with alerts irrelevant to their job:

  - Admin (maps to DDG/Regional Head)        -> everything
  - Regional Operator (State Met Centre)      -> their region's stations only
  - Field Technician (Instrumentation Div.)   -> maintenance/health issues only
  - Forecaster (Forecasting Office)           -> genuine-weather-event flags only
  - Viewer (public/researcher)                -> no notifications, dashboard only

This sits on top of alerts.py (which handles the actual SendGrid
sending) - this module decides WHO gets WHAT, alerts.py decides HOW
it's sent.
"""

import pandas as pd
import alerts

# Which station regions each user is responsible for (example - would
# come from a real user database in production)
USERS = [
    {"name": "DDG Delhi", "email": "ddg.delhi@example.gov.in", "role": "admin", "region": None},
    {"name": "Met Officer Chennai", "email": "met.chennai@example.gov.in", "role": "regional_operator", "region": "south"},
    {"name": "Field Tech Team", "email": "fieldtech@example.gov.in", "role": "field_technician", "region": None},
    {"name": "Forecaster Delhi", "email": "forecast.delhi@example.gov.in", "role": "forecaster", "region": None},
]

# Simple station-to-region mapping (matches our 10-station setup)
STATION_REGION = {
    "ST01": "north", "ST10": "north",       # Delhi, Chandigarh
    "ST02": "west", "ST06": "west",          # Mumbai, Ahmedabad
    "ST03": "south", "ST04": "south", "ST09": "south",  # Chennai, Bengaluru, Belagavi
    "ST05": "east",                            # Kolkata
    "ST07": "north",                            # Lucknow
    "ST08": "south",                             # Hyderabad
}

MAINTENANCE_ATTRIBUTIONS = {"Sensor fault", "Silent station", "Physics violation (sensor inconsistency)"}
WEATHER_ATTRIBUTIONS = {"ML-detected anomaly (needs review)", "Possible tampering"}


def _filter_for_role(final_df: pd.DataFrame, user: dict) -> pd.DataFrame:
    """Applies the role-based routing rule for one user."""
    if user["role"] == "admin":
        return final_df  # everything

    if user["role"] == "regional_operator":
        region_stations = [s for s, r in STATION_REGION.items() if r == user["region"]]
        return final_df[final_df["station_id"].isin(region_stations)]

    if user["role"] == "field_technician":
        return final_df[final_df["attribution"].isin(MAINTENANCE_ATTRIBUTIONS)]

    if user["role"] == "forecaster":
        return final_df[final_df["attribution"].isin(WEATHER_ATTRIBUTIONS)]

    return pd.DataFrame(columns=final_df.columns)  # viewer / unknown role: nothing


def route_and_send(final_df: pd.DataFrame, health_df: pd.DataFrame = None):
    """Goes through every user, filters the anomaly list to what's
    relevant for their role, and sends it via alerts.py."""
    if final_df.empty:
        print("No anomalies to route.")
        return

    for user in USERS:
        relevant = _filter_for_role(final_df, user)
        if relevant.empty:
            print(f"[{user['role']}] {user['name']}: nothing relevant to send.")
            continue

        # temporarily point alerts.py at this user's inbox
        original_recipient = alerts.RECIPIENT_EMAIL
        alerts.RECIPIENT_EMAIL = user["email"]

        print(f"[{user['role']}] {user['name']} ({user['email']}): "
              f"{len(relevant)} relevant item(s)")
        alerts.dispatch_alerts(relevant)

        alerts.RECIPIENT_EMAIL = original_recipient  # restore


if __name__ == "__main__":
    # Quick standalone test using whatever final_report.csv already exists
    try:
        final_df = pd.read_csv("final_report.csv")
        route_and_send(final_df)
    except FileNotFoundError:
        print("Run main.py first to generate final_report.csv, then re-run this file.")
