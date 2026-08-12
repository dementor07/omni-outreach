"""Standard transactional email (workspace invites, system notices).

Deliberately separate from campaign sending: campaigns go through per-workspace
connections + the Rust muscle; this is the app's OWN system mailer over standard
SMTP (e.g. Gmail smtp.gmail.com:587 STARTTLS), configured via the SMTP_* env vars.

Uses stdlib ``smtplib`` on a worker thread so it needs no extra dependency and
never blocks the event loop. Raises ``MailerError`` when SMTP isn't configured or
the send fails, so callers can surface a clear message instead of dropping mail.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.config import settings

log = logging.getLogger(__name__)


class MailerError(RuntimeError):
    """Raised when the transactional mailer cannot send (unconfigured or SMTP error)."""


def _send_sync(to: str, subject: str, html: str | None, text: str | None) -> None:
    if not settings.smtp_configured():
        raise MailerError(
            "transactional email is not configured — set SMTP_HOST / SMTP_USER / SMTP_PASSWORD"
        )
    from_addr = settings.smtp_from or settings.smtp_user
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.smtp_from_name or "", from_addr))
    msg["To"] = to
    msg.set_content(text or " ")
    if html:
        msg.add_alternative(html, subtype="html")

    ctx = ssl.create_default_context()
    host, port = settings.smtp_host, settings.smtp_port
    if port == 465:  # implicit TLS
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
            s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    else:  # STARTTLS (Gmail 587)
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)


async def send_email(to: str, subject: str, *, html: str | None = None, text: str | None = None) -> None:
    """Send one transactional email. Raises MailerError on failure."""
    try:
        await asyncio.to_thread(_send_sync, to, subject, html, text)
    except MailerError:
        raise
    except Exception as e:  # noqa: BLE001 — normalise every SMTP/socket error
        raise MailerError(f"SMTP send failed: {e}") from e
    log.info("transactional email sent to %s (%s)", to, subject)


def invite_email(*, accept_url: str, workspace_name: str, inviter: str | None, role: str) -> tuple[str, str, str]:
    """Build (subject, html, text) for a workspace-invite email."""
    who = f"{inviter} " if inviter else ""
    subject = f"You've been invited to {workspace_name} on Outbound Marketing Hub"
    text = (
        f"{who}invited you to join the '{workspace_name}' workspace as {role}.\n\n"
        f"Accept your invitation:\n{accept_url}\n\n"
        "This link expires in 14 days. If you weren't expecting this, you can ignore it."
    )
    html = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;color:#0f172a">
  <h2 style="margin:0 0 12px;font-size:18px">You've been invited to <b>{workspace_name}</b></h2>
  <p style="margin:0 0 20px;font-size:14px;line-height:1.5;color:#334155">
    {who}invited you to join the <b>{workspace_name}</b> workspace as <b>{role}</b> on Outbound Marketing Hub.
  </p>
  <a href="{accept_url}" style="display:inline-block;background:#4f46e5;color:#fff;text-decoration:none;padding:10px 20px;border-radius:8px;font-size:14px;font-weight:600">Accept invitation</a>
  <p style="margin:20px 0 0;font-size:12px;color:#94a3b8">
    Or paste this link into your browser:<br><span style="word-break:break-all">{accept_url}</span>
  </p>
  <p style="margin:16px 0 0;font-size:12px;color:#94a3b8">This link expires in 14 days. If you weren't expecting this, you can ignore this email.</p>
</div>"""
    return subject, html, text
