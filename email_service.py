"""Secure email service for sending the management report.

SMTP credentials are NEVER hard-coded. They can be supplied either:
  1) via environment variables (SMTP_HOST, SMTP_PORT, SMTP_USERNAME,
     SMTP_PASSWORD, SMTP_FROM), or
  2) interactively through the Streamlit SMTP settings form, in which
     case the values live only in memory/session state for the send.

You can send to ANY recipient email address — the recipient is always
typed by the user in the UI and never restricted.
"""

from __future__ import annotations

import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

REQUIRED_KEYS = ["host", "port", "username", "password", "from_addr"]


def default_smtp_from_env() -> dict[str, str]:
    return {
        "host": os.getenv("SMTP_HOST", ""),
        "port": os.getenv("SMTP_PORT", "587"),
        "username": os.getenv("SMTP_USERNAME", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from_addr": os.getenv("SMTP_FROM", ""),
    }


def env_status() -> dict[str, bool]:
    cfg = default_smtp_from_env()
    return {k: bool(v) for k, v in cfg.items()}


def is_configured(cfg: dict[str, str] | None = None) -> bool:
    if cfg is None:
        cfg = default_smtp_from_env()
    for key in REQUIRED_KEYS:
        if not cfg.get(key, "").strip():
            return False
    try:
        int(cfg.get("port", "0"))
    except (TypeError, ValueError):
        return False
    return True


def build_email_message(
    to_email: str,
    subject: str,
    body_text: str,
    attachments: list[tuple[str, bytes]] | None = None,
    from_addr: str = "",
) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = from_addr or os.getenv("SMTP_FROM", "")
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    for fname, payload in attachments or []:
        part = MIMEApplication(payload, _subtype="pdf")
        part.add_header(
            "Content-Disposition", "attachment", filename=("utf-8", "", fname)
        )
        msg.attach(part)

    return msg


def send_email(
    to_email: str,
    subject: str,
    body_text: str,
    attachments: list[tuple[str, bytes]] | None = None,
    smtp_config: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Send the email to any recipient address. Returns (success, message).

    `smtp_config` optionally carries {host, port, username, password,
    from_addr}. When omitted, environment variables are used.
    """
    cfg = smtp_config or default_smtp_from_env()
    if not is_configured(cfg):
        return (
            False,
            "SMTP is not configured. Enter your SMTP settings in the form (or set SMTP_HOST, "
            "SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM as environment variables) "
            "before sending emails.",
        )

    try:
        from_addr = cfg.get("from_addr", "")
        msg = build_email_message(
            to_email, subject, body_text, attachments, from_addr=from_addr
        )
        host = cfg.get("host", "").strip()
        port = int(cfg.get("port", "587"))
        username = cfg.get("username", "").strip()
        password = cfg.get("password", "")

        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(username, password)
            server.sendmail(from_addr, [to_email], msg.as_string())
        return True, f"Email sent successfully to {to_email}."
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP authentication failed. Check SMTP username and password."
    except smtplib.SMTPRecipientsRefused as e:
        return False, f"Recipient refused by server: {e}"
    except Exception as e:  # noqa: BLE001
        return False, f"Email sending failed: {str(e)}"


def build_email_body(
    metrics: dict[str, Any],
    risk_level: str,
    decision_text: str,
    decision_reason: str,
    project_name: str,
) -> str:
    def money(v):
        return f"${v:,.0f}" if v is not None else "N/A"

    def pct(v):
        return f"{v:.2f}%" if v is not None else "N/A"

    lines = [
        f"Dear recipient,",
        "",
        f"Please find attached the Financial Engineering Investment Decision Report for {project_name}.",
        "",
        "Summary of the analysis:",
        f"- Net Present Value (NPV): {money(metrics.get('npv'))}",
        f"- Internal Rate of Return (IRR): {pct(metrics.get('irr'))}",
        f"- Modified Internal Rate of Return (MIRR): {pct(metrics.get('mirr'))}",
        f"- Return on Investment (ROI): {pct(metrics.get('roi'))}",
        f"- Payback Period: {metrics.get('payback') if metrics.get('payback') is not None else 'N/A'} years",
        f"- Risk Level: {risk_level}",
        "",
        f"FINAL DECISION: {decision_text}",
        f"Main reason: {decision_reason}",
        "",
        "This email was generated automatically by the Financial Engineering Investment Decision Agent.",
    ]
    return "\n".join(lines)