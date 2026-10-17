from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib

from app.utils.crypto import decrypt


async def send_email(
    host: str,
    port: int,
    security: str,
    username: str,
    password_encrypted: str,
    from_name: str,
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
) -> None:
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    pwd = decrypt(password_encrypted) if password_encrypted else ""
    use_tls = security == "STARTTLS"
    use_ssl = security == "SSL"

    await aiosmtplib.send(
        msg,
        hostname=host,
        port=port,
        username=username or None,
        password=pwd or None,
        use_tls=use_tls,
        use_ssl=use_ssl,
        timeout=15,
    )
