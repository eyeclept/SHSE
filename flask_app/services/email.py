"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Outbound email helper. Wraps smtplib to send plain-text messages.
    Silently disabled (returns False with a warning log) when SMTP_HOST
    is not configured in the environment.
"""
# Imports
import logging
import smtplib
from email.mime.text import MIMEText

from flask_app.config import Config

# Globals
logger = logging.getLogger(__name__)


# Functions
def send_email(to: str, subject: str, body: str) -> bool:
    """
    Input: recipient address, subject line, plain-text body
    Output: True on success, False on failure or when SMTP is unconfigured
    Details:
        Reads SMTP credentials from Config (sourced from environment).
        Uses STARTTLS when SMTP_TLS=true; falls back to plain SMTP otherwise.
        Always returns False without raising so the caller can degrade gracefully.
    """
    if not Config.SMTP_HOST:
        logger.warning("send_email: SMTP_HOST not configured — email suppressed")
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = Config.SMTP_FROM
    msg["To"] = to
    try:
        if Config.SMTP_TLS:
            with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT) as server:
                server.starttls()
                if Config.SMTP_USER:
                    server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
                server.sendmail(Config.SMTP_FROM, [to], msg.as_string())
        else:
            with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT) as server:
                if Config.SMTP_USER:
                    server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
                server.sendmail(Config.SMTP_FROM, [to], msg.as_string())
        return True
    except Exception:
        logger.exception("send_email: failed to send email to %s", to)
        return False


if __name__ == "__main__":
    pass
