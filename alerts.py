"""
alerts.py - Priority-based alerting via SendGrid (industry-standard
transactional email API, not raw smtplib).
Critical anomalies (high confidence) are sent as an immediate email;
medium-confidence ones are batched into a digest so operators aren't
overwhelmed with low-value notifications (fixes "alert fatigue").
"""

import os
import pandas as pd
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

SENDER_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL", "alerts@yourproject.com")
RECIPIENT_EMAIL = os.environ.get("ALERT_EMAIL_TO", "operator@example.com")
API_KEY = os.environ.get("SENDGRID_API_KEY")


def is_email_configured() -> bool:
    """Returns True if SendGrid API key is set in environment or config."""
    api_key = os.environ.get("SENDGRID_API_KEY") or API_KEY
    sender = os.environ.get("SENDGRID_FROM_EMAIL") or SENDER_EMAIL
    recipient = os.environ.get("ALERT_EMAIL_TO") or RECIPIENT_EMAIL
    return bool(api_key and sender and recipient)


def build_html(df: pd.DataFrame, title: str) -> str:
    if df.empty:
        return f"<p>{title}: no items.</p>"
    rows = "".join(
        f"<tr><td style='padding:6px 12px;border-bottom:1px solid #ddd'>{getattr(r, 'station_id', '-')}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #ddd'>{getattr(r, 'timestamp', '-')}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #ddd'>{getattr(r, 'attribution', '-')}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #ddd'>{getattr(r, 'confidence_pct', getattr(r, 'confidence_%', '-'))}%</td>"
        "</tr>" for r in df.itertuples()
    )
    return f"""
    <h2>{title}</h2>
    <table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif">
        <tr style="background:#0B2E4F;color:white">
            <th style="padding:8px">Station</th><th style="padding:8px">Time</th>
            <th style="padding:8px">Issue</th><th style="padding:8px">Confidence</th>
        </tr>{rows}
    </table>"""


def send_email(subject: str, html_content: str, recipient: str = None) -> bool:
    """
    Sends an email notification via SendGrid. Handles missing config and failures gracefully.
    Returns True if email was sent successfully, False otherwise.
    """
    api_key = os.environ.get("SENDGRID_API_KEY") or API_KEY
    sender = os.environ.get("SENDGRID_FROM_EMAIL") or SENDER_EMAIL
    target_recipient = recipient or RECIPIENT_EMAIL or os.environ.get("ALERT_EMAIL_TO")

    if not api_key:
        print(f"EMAIL ALERT: NOT CONFIGURED - Skipping email '{subject}' (No SENDGRID_API_KEY set)")
        return False
    if not sender or not target_recipient:
        print(f"EMAIL ALERT: NOT CONFIGURED - Skipping email '{subject}' (Sender or recipient email not configured)")
        return False

    print(f"EMAIL ALERT: SENDING - Attempting to send email: '{subject}' to {target_recipient}")
    message = Mail(
        from_email=sender,
        to_emails=target_recipient,
        subject=subject,
        html_content=html_content
    )
    try:
        client = SendGridAPIClient(api_key)
        response = client.send(message)
        if 200 <= response.status_code < 300:
            print(f"EMAIL ALERT: SENT - Email sent successfully ('{subject}'). Status: {response.status_code}")
            return True
        else:
            print(f"EMAIL ALERT: FAILED - SendGrid returned status code {response.status_code} for '{subject}'")
            return False
    except Exception as e:
        print(f"EMAIL ALERT: FAILED - SendGrid email delivery failed for '{subject}': {e}")
        return False


def dispatch_alerts(final_df: pd.DataFrame):
    """Splits by alert_priority (set by fusion.py) so operators get
    immediate emails only for what actually matters."""
    if final_df.empty:
        print("No anomalies to alert on.")
        return

    df = final_df.rename(columns={"confidence_%": "confidence_pct"})

    if "alert_priority" in df.columns:
        prio_str = df["alert_priority"].astype(str)
        critical = df[prio_str.str.startswith("CRITICAL")]
        medium = df[prio_str.str.startswith("MEDIUM")]
        low = df[prio_str.str.startswith("LOW")]
    else:
        critical = df
        medium = pd.DataFrame()
        low = pd.DataFrame()

    if not critical.empty:
        send_email(f"CRITICAL - {len(critical)} high-confidence anomalies",
                    build_html(critical, "Critical Anomalies (immediate action)"))
    if not medium.empty:
        send_email(f"Daily digest - {len(medium)} anomalies to review",
                    build_html(medium, "Medium-Confidence Anomalies (daily digest)"))
    if not low.empty:
        print(f"Logged (not emailed): {len(low)} low-confidence items.")

