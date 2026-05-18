import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger(__name__)


async def send_email(
    from_name: str,
    from_email: str,
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    smtp_use_tls: bool,
    to_email: str,
    subject: str,
    body_html: str,
) -> dict:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg.attach(MIMEText(body_html, "html"))

    context = ssl.create_default_context()

    # Run synchronous smtplib in a thread-safe way
    import asyncio

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, _send_sync, smtp_host, smtp_port, smtp_username, smtp_password, smtp_use_tls, context, msg
    )

    log.info("[email] sent to=%s subject=%s", to_email, subject)
    return {"to": to_email, "subject": subject}


def _send_sync(host, port, username, password, use_tls, context, msg):
    if use_tls:
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(username, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(host, port, context=context) as server:
            server.login(username, password)
            server.send_message(msg)
