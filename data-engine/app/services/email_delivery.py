"""Envio de alertas por correo SMTP (stdlib: smtplib + email.message).

Canal "email" del outbox de alertas (NotificationService). Sin SMTP_HOST,
SMTP_FROM o ALERT_EMAIL_TO el canal sigue cayendo al webhook de correo, como
antes. El resultado se clasifica con la misma semantica del outbox:

* ``delivered``: el servidor acepto el mensaje (si rechazo a parte de los
  destinatarios se anota cuantos en ``error``).
* ``pending``: la conexion nunca se establecio (rechazada, DNS, timeout al
  conectar): no salio nada y el reconciliador puede reintentar sin riesgo.
* ``failed``: rechazo permanente (credenciales, respuesta 5xx, STARTTLS no
  soportado, error TLS): reintentar el mismo envio solo repite el rechazo.
* ``throttled``: respuesta 4xx (el servidor pide esperar).
* ``unknown``: timeout o corte una vez iniciada la sesion SMTP: el servidor
  pudo aceptar el mensaje, asi que nunca se reintenta en caliente.

Nunca se registra la contrasena ni el cuerpo: el error persistido es solo la
clase de la excepcion (y el codigo SMTP cuando lo hay).
"""

from __future__ import annotations

import smtplib
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any


@dataclass(frozen=True)
class EmailContent:
    subject: str
    text: str
    html: str | None = None


def recipients(settings: Any) -> list[str]:
    raw = getattr(settings, "alert_email_to", None) or ""
    seen: list[str] = []
    for part in str(raw).replace(";", ",").split(","):
        address = part.strip()
        if address and address not in seen:
            seen.append(address)
    return seen


def smtp_configured(settings: Any) -> bool:
    """True si hay servidor, remitente y al menos un destinatario."""
    return bool(
        (getattr(settings, "smtp_host", None) or "").strip()
        and (getattr(settings, "smtp_from", None) or "").strip()
        and recipients(settings)
    )


def build_message(settings: Any, content: EmailContent) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = content.subject
    message["From"] = str(settings.smtp_from).strip()
    message["To"] = ", ".join(recipients(settings))
    message["Date"] = formatdate(localtime=False, usegmt=True)
    domain = str(settings.smtp_from).rsplit("@", 1)[-1].strip(" >") or None
    message["Message-ID"] = make_msgid(domain=domain)
    message.set_content(content.text)
    if content.html:
        message.add_alternative(content.html, subtype="html")
    return message


def _result(status: str, error: str | None = None) -> dict:
    return {"status": status, "error": error}


def _classify(exc: BaseException, *, session_started: bool) -> dict:
    name = type(exc).__name__
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return _result("failed", f"{name} {exc.smtp_code}")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return _result("failed", name)
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return _result("failed", name)
    if isinstance(exc, smtplib.SMTPConnectError):
        # El servidor contesto al conectar con un codigo de error: no salio nada.
        return _result("pending", f"{name} {exc.smtp_code}")
    if isinstance(exc, smtplib.SMTPResponseException):
        code = int(exc.smtp_code or 0)
        if 400 <= code < 500:
            return _result("throttled", f"{name} {code}")
        if code >= 500:
            return _result("failed", f"{name} {code}")
        return _result("unknown", f"{name} {code}")
    if isinstance(exc, ssl.SSLError):
        return _result("failed", name)
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return _result("unknown" if session_started else "pending", name)
    if isinstance(exc, TimeoutError):
        return _result("unknown" if session_started else "pending", name)
    if isinstance(exc, (ConnectionRefusedError, socket.gaierror)) and not session_started:
        return _result("pending", name)
    if isinstance(exc, OSError) and not session_started:
        return _result("pending", name)
    return _result("unknown", name)


SmtpFactory = Callable[..., smtplib.SMTP]


def send_email(
    settings: Any,
    content: EmailContent,
    *,
    smtp_factory: SmtpFactory | None = None,
    smtp_ssl_factory: SmtpFactory | None = None,
) -> dict:
    """Envia ``content`` a ALERT_EMAIL_TO. Devuelve ``{"status", "error"}``.

    No lanza: cualquier excepcion se clasifica. Las factorias son inyectables
    para los tests (por defecto ``smtplib.SMTP`` / ``smtplib.SMTP_SSL``).
    """
    if not smtp_configured(settings):
        return _result("not_configured", "SMTP sin configurar")
    host = str(settings.smtp_host).strip()
    port = int(settings.smtp_port)
    timeout = float(settings.smtp_timeout_seconds)
    use_ssl = bool(settings.smtp_ssl)
    message = build_message(settings, content)
    session_started = False
    client: smtplib.SMTP | None = None
    try:
        if use_ssl:
            factory = smtp_ssl_factory or smtplib.SMTP_SSL
            client = factory(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            factory = smtp_factory or smtplib.SMTP
            client = factory(host, port, timeout=timeout)
        client.ehlo()
        if not use_ssl and settings.smtp_starttls:
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        username = (settings.smtp_username or "").strip()
        if username:
            client.login(username, settings.smtp_password or "")
        # A partir de aqui el servidor puede haber aceptado el mensaje aunque
        # la respuesta no llegue: cualquier corte es ambiguo.
        session_started = True
        refused = client.send_message(message)
    except Exception as exc:  # noqa: BLE001 - se clasifica, nunca se propaga
        outcome = _classify(exc, session_started=session_started)
    else:
        outcome = _result(
            "delivered",
            f"Rechazados {len(refused)} destinatarios" if refused else None,
        )
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:  # noqa: BLE001 - el cierre no cambia el resultado
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass
    return outcome


def generic_alert_content(payload: dict) -> EmailContent:
    """Correo sencillo para alertas sin plantilla propia."""
    from html import escape

    severity = str(payload.get("severity") or "").upper()
    en = payload.get("language") == "en"
    title = str(payload.get("title") or ("Alert" if en else "Alerta"))
    message = str(payload.get("message") or "")
    ticker = payload.get("ticker")
    footer = "Open GerarAI to see the alert details." if en else "Abre GerarAI para ver el detalle de la alerta."
    subject = f"[GerarAI] {title}"
    lines = [f"[{severity}] {title}", "", message]
    if ticker:
        lines += ["", f"Ticker: {ticker}"]
    lines += ["", footer]
    html = (
        "<div style=\"font-family:Arial,Helvetica,sans-serif;color:#111\">"
        f"<p style=\"font-size:12px;color:#555\">{escape(severity)}</p>"
        f"<h2 style=\"margin:0 0 8px\">{escape(title)}</h2>"
        f"<p style=\"white-space:pre-line\">{escape(message)}</p>"
        + (f"<p>Ticker: <strong>{escape(str(ticker))}</strong></p>" if ticker else "")
        + f"<p style=\"font-size:12px;color:#555\">{escape(footer)}</p>"
        "</div>"
    )
    return EmailContent(subject=subject[:250], text="\n".join(lines), html=html)
