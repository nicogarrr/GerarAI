from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.tenancy import tenant_filters
from app.models import AlertDelivery, Company, NewsEvent, ResearchAlert
from app.services.email_delivery import generic_alert_content, send_email, smtp_configured

# Un claim 'sending' mas viejo que esto se considera abandonado (worker muerto
# entre el envio y el commit del resultado) y vuelve a ser reclamable. Es el
# unico residuo at-least-once: si el envio original si llego, la recuperacion
# puede repetir ESE canal una vez pasado el TTL.
STALE_CLAIM_SECONDS = 600

# Retry-After se honra hasta este cap: valores mayores se truncan (no se
# afirma cumplimiento del header por encima del cap). Se aplica fijando la
# elegibilidad del claim (updated_at en el futuro), sin columna dedicada.
RETRY_AFTER_CAP_SECONDS = 3600


def record_in_app_delivery(db: Session, alert: ResearchAlert) -> None:
    """Registra la entrega del canal in_app de una alerta creada sin dispatch.

    Una alerta in_app esta entregada en cuanto existe en la app: la fila deja el
    estado real y la UI no muestra "sin registro de entrega". No envia nada
    externo (telegram/correo/push siguen su propio camino) y es idempotente
    (UNIQUE alert_id+canal). No hace commit: va en la transaccion del creador.
    """
    if "in_app" not in (alert.channels or []):
        return
    if alert.id is None:
        db.flush()
    exists = db.scalar(
        select(AlertDelivery.id).where(
            AlertDelivery.alert_id == alert.id,
            AlertDelivery.channel == "in_app",
            *tenant_filters(db, AlertDelivery),
        )
    )
    if exists is not None:
        return
    try:
        with db.begin_nested():
            db.add(
                AlertDelivery(
                    tenant_id=alert.tenant_id,
                    alert_id=alert.id,
                    channel="in_app",
                    status="delivered",
                    attempts=1,
                )
            )
            db.flush()
    except IntegrityError:
        pass


class NotificationService:
    """Dispatch alert channels without coupling research logic to one vendor."""

    def dispatch(self, db: Session, alert: ResearchAlert) -> dict:
        settings = get_settings()
        deliveries: dict[str, dict] = {}
        # Score Jev adjuntado por el emisor (alert_rule_service, best-effort):
        # sin TYPESAFE_API_KEY no hay `jev_urgency` y el texto sale sin línea Jev.
        jev_urgency = (alert.metadata_ or {}).get("jev_urgency") or {}
        news_alert = alert.alert_type in ("tracked_news", "news_material_update")
        company = (db.get(Company, alert.company_id) if news_alert and alert.company_id is not None
                   and hasattr(db, "get") else None)
        event_id = (alert.metadata_ or {}).get("news_event_id")
        event = db.get(NewsEvent, event_id) if news_alert and event_id and hasattr(db, "get") else None
        payload = {
            "company_name": company.name if company else None,
            "ticker": company.ticker if company else None,
            "source_url": (alert.metadata_ or {}).get("source_url") or (event.url if event else None),
            "source_headline": (event.metadata_ or {}).get("source_headline") if event else None,
            "event_date": event.date if event and (event.metadata_ or {}).get("date_source") in ("source", "gdelt_first_seen") else None,
            "event_date_source": (event.metadata_ or {}).get("date_source") if event else None,
            "alert_id": alert.id,
            "tenant_id": alert.tenant_id,
            "company_id": alert.company_id,
            "severity": alert.severity,
            "type": alert.alert_type,
            "title": alert.title,
            "message": alert.message,
            "created_at": alert.created_at.isoformat(),
            # Idioma guardado al disparar (solo si no es espanol): Telegram y el
            # correo generico envuelven el aviso en ese idioma.
            **({"language": "en"} if (alert.metadata_ or {}).get("language") == "en" else {}),
            "jev_urgency": jev_urgency,
        }
        from app.services.outbound_alerts import event_type, subscription_for

        category = event_type(db, alert)
        subscription = subscription_for(db, alert) if category else None
        from app.services import web_push

        push_pref = web_push.preference_for(db, alert) if category else None
        channels = list(alert.channels)
        added = [c for c, ok in (("telegram", subscription), ("push", push_pref)) if ok and c not in channels]
        if added:
            channels.extend(added)
            alert.channels = channels
            db.commit()
        for channel in channels:
            if channel == "telegram" and not subscription:
                deliveries[channel] = self._result("skipped", error="Sin consentimiento para este tipo de alerta")
                continue
            self._ensure_delivery_row(db, alert, channel)
            if not self._claim_delivery(db, alert, channel):
                # Otro worker la tiene ('sending') o ya esta entregada: nunca
                # reenviar lo que no se ha reclamado.
                row = self._get_delivery(db, alert, channel)
                deliveries[channel] = self._result(
                    row.status if row is not None else "pending",
                    error=row.last_error if row is not None else None,
                )
                continue
            try:
                if channel == "in_app":
                    result = self._result("delivered")
                elif channel == "telegram":
                    result = self._dispatch_telegram(settings, {**payload, **({"chat_id": subscription.chat_id} if subscription else {})})
                elif channel == "push" and push_pref:
                    result = self._result(**web_push.send_to_user(db, settings, alert))
                elif channel == "email" and smtp_configured(settings):
                    result = self._dispatch_email(settings, alert, payload)
                else:
                    result = self._dispatch_webhook(settings, payload, channel)
            except Exception:
                # El commit del resultado tambien puede fallar: la fila queda
                # en 'sending' y un retry inmediato NO la reclama (sin
                # reenvio). Solo un claim expirado (> STALE_CLAIM_SECONDS)
                # vuelve a ser elegible.
                self._finish_delivery(db, alert, channel, "failed", "dispatch_error")
                deliveries[channel] = self._result("failed", error="dispatch_error")
                continue
            self._finish_delivery(
                db,
                alert,
                channel,
                result["status"],
                result["error"],
                retry_after=result.get("retry_after"),
            )
            deliveries[channel] = result
        # Espejo NO autoritativo en metadata_ para lectores antiguos; el
        # estado real vive en alert_deliveries.
        alert.metadata_ = {**(alert.metadata_ or {}), "deliveries": deliveries}
        db.commit()
        db.refresh(alert)
        return deliveries

    def reconcile_stale_deliveries(
        self,
        db: Session,
        *,
        tenant_id: int | None = None,
        limit: int = 100,
    ) -> dict:
        """Re-despacha entregas atascadas cuyo claim ya expiro.

        Sin este barrido, una fila 'sending'/'unknown'/'throttled' solo se
        reintenta si el emisor original vuelve a invocar dispatch para ESA
        alerta; el TTL solo ayuda si alguien re-entra. Es el cierre del
        residual at-least-once documentado: si el envio original llego, la
        reconciliacion puede repetir ESE canal una vez pasado el TTL.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=STALE_CLAIM_SECONDS)
        statement = (
            select(AlertDelivery.alert_id)
            .where(
                AlertDelivery.status.in_(("pending", "sending", "unknown", "throttled")),
                AlertDelivery.updated_at < cutoff,
            )
            .distinct()
            .limit(limit)
        )
        if tenant_id is not None:
            statement = statement.where(AlertDelivery.tenant_id == tenant_id)
        alert_ids = list(db.execute(statement).scalars())
        redispatched = 0
        errors: list[str] = []
        for alert_id in alert_ids:
            alert = db.get(ResearchAlert, alert_id)
            if alert is None:
                continue
            try:
                self.dispatch(db, alert)
                redispatched += 1
            except Exception:  # noqa: BLE001 - una alerta rota no frena el barrido
                db.rollback()
                errors.append(f"alert_id={alert_id}")
        return {
            "candidates": len(alert_ids),
            "redispatched": redispatched,
            "errors": errors,
        }

    @staticmethod
    def _extract_retry_after(exc: Exception) -> int | None:
        """Segundos de Retry-After de un 429 (entero o HTTP-date), con cap.

        None si no aplica o no se puede interpretar: el cooldown fijo ya
        cubre ese caso. Nunca devuelve mas que RETRY_AFTER_CAP_SECONDS.
        """
        if not isinstance(exc, httpx.HTTPStatusError):
            return None
        if exc.response.status_code != 429:
            return None
        raw = exc.response.headers.get("Retry-After")
        if not raw:
            try:
                raw = str((exc.response.json().get("parameters") or {}).get("retry_after") or "")
            except (ValueError, AttributeError, TypeError):
                return None
        if not raw:
            return None
        seconds: int | None = None
        try:
            seconds = int(raw)
        except ValueError:
            from email.utils import parsedate_to_datetime

            try:
                retry_at = parsedate_to_datetime(raw)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                seconds = int((retry_at - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError):
                seconds = None
        if seconds is None or seconds <= 0:
            return None
        return min(seconds, RETRY_AFTER_CAP_SECONDS)

    @staticmethod
    def _classify_send_error(exc: Exception) -> str:
        """Clasifica el resultado de un envio fallido.

        - 'pending' (ConnectError): la conexion nunca se establecio, no salio
          nada. Reintento inmediato seguro (inequivoco).
        - 'failed' (4xx distinto de 429): el proveedor RECHAZO el mensaje tal
          cual. Permanente: NUNCA se reclama de nuevo (reintentar el mismo
          cuerpo solo repite el rechazo).
        - 'throttled' (429): el proveedor pidio esperar. No es ambiguo (no se
          entrego), pero el reintento inmediato solo empeora el rate limit:
          enfria y vuelve via reconciliador. Retry-After SE respeta hasta
          RETRY_AFTER_CAP_SECONDS fijando la elegibilidad del claim
          (updated_at en el futuro); valores por encima del cap se truncan y
          el reconciliador vuelve a enfriar si el proveedor insiste.
        - 'unknown' (timeout/5xx/otros): ambiguo por definicion - el proveedor
          pudo aceptar y entregar. NUNCA reintento inmediato; reconciliar por
          claim expirado.
        """
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            if status_code == 429:
                return "throttled"
            if status_code < 500:
                return "failed"
            return "unknown"
        if isinstance(exc, httpx.ConnectError):
            # La conexion nunca se establecio: no salio nada.
            return "pending"
        # Timeout, corte a mitad de respuesta, etc.: ambiguo por definicion.
        return "unknown"

    def _dispatch_webhook(self, settings, payload: dict, channel: str) -> dict:
        endpoint = (
            getattr(settings, "alert_email_webhook_url", None)
            if channel == "email"
            else getattr(settings, "alert_push_webhook_url", None)
            if channel == "push"
            else None
        )
        if not endpoint:
            return self._result(
                "not_configured",
                error=f"No webhook configured for {channel}",
            )
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    endpoint,
                    json={**payload, "channel": channel},
                )
                response.raise_for_status()
            return self._result("delivered")
        except Exception as exc:
            # Webhook errors can contain signed URLs, request bodies and
            # provider paths. Persist only the exception class.
            return self._result(
                self._classify_send_error(exc),
                error=type(exc).__name__,
                retry_after=self._extract_retry_after(exc),
            )

    def _dispatch_email(self, settings, alert: ResearchAlert, payload: dict) -> dict:
        """Correo por SMTP. DCA y resultados usan su plantilla; el resto, la generica."""
        dca = (alert.metadata_ or {}).get("dca")
        earnings = (alert.metadata_ or {}).get("earnings")
        if alert.alert_type == "dca_level" and isinstance(dca, dict):
            from app.services.dca_alert_copy import email_content

            content = email_content(dca, str((alert.metadata_ or {}).get("language") or "es"))
        elif alert.alert_type == "earnings_reminder" and isinstance(earnings, dict):
            from app.services.earnings_alert_copy import email_content

            content = email_content(earnings, str((alert.metadata_ or {}).get("language") or "es"))
        else:
            content = generic_alert_content(payload)
        outcome = send_email(settings, content)
        return self._result(outcome["status"], error=outcome.get("error"))

    def _ensure_delivery_row(self, db: Session, alert: ResearchAlert, channel: str) -> None:
        if self._get_delivery(db, alert, channel) is not None:
            return
        db.add(
            AlertDelivery(
                tenant_id=alert.tenant_id, alert_id=alert.id, channel=channel
            )
        )
        try:
            db.commit()
        except IntegrityError:
            # Otro worker creo la fila primero (UNIQUE alert_id+channel).
            db.rollback()

    def _get_delivery(
        self, db: Session, alert: ResearchAlert, channel: str
    ) -> AlertDelivery | None:
        return db.execute(
            select(AlertDelivery).where(
                AlertDelivery.alert_id == alert.id,
                AlertDelivery.channel == channel,
            )
        ).scalar_one_or_none()

    def _claim_delivery(self, db: Session, alert: ResearchAlert, channel: str) -> bool:
        """Claim atomico: un solo UPDATE con la condicion de elegibilidad.

        Dos workers concurrentes: solo uno obtiene fila (RETURNING). Un
        commit fallido tras el envio deja 'sending' reciente -> no elegible
        -> el retry no reenvia. 'sending' expirado (worker muerto) vuelve a
        ser elegible pasado STALE_CLAIM_SECONDS.
        """
        stale_before = datetime.now(UTC) - timedelta(seconds=STALE_CLAIM_SECONDS)
        result = db.execute(
            update(AlertDelivery)
            .where(
                AlertDelivery.alert_id == alert.id,
                AlertDelivery.channel == channel,
                or_(
                    # Inequivoco inmediato: nunca salio nada (pending inicial
                    # o ConnectError). Reintento seguro.
                    AlertDelivery.status == "pending",
                    # Enfriados: 'sending' (commit fallido o worker muerto),
                    # 'unknown' (timeout/5xx: el proveedor pudo aceptar y
                    # entregar) y 'throttled' (429: pidio esperar). NUNCA
                    # reintento inmediato: solo reconciliacion por claim
                    # expirado. Sin idempotency key del proveedor no existe
                    # exactly-once.
                    and_(
                        AlertDelivery.status.in_(("sending", "unknown", "throttled")),
                        AlertDelivery.updated_at < stale_before,
                    ),
                    # 'failed' (4xx != 429: rechazo permanente), 'delivered' y
                    # 'not_configured' NO son elegibles nunca.
                )
            )
            .values(status="sending", attempts=AlertDelivery.attempts + 1, last_error=None)
            .returning(AlertDelivery.id)
        )
        claimed = result.scalar_one_or_none() is not None
        # El claim queda persistido ANTES de enviar.
        db.commit()
        return claimed

    def _finish_delivery(
        self,
        db: Session,
        alert: ResearchAlert,
        channel: str,
        status: str,
        error: str | None,
        retry_after: int | None = None,
    ) -> None:
        values: dict = {"status": status, "last_error": error}
        if (
            status == "throttled"
            and retry_after is not None
            and retry_after > STALE_CLAIM_SECONDS
        ):
            # Retry-After > cooldown: la elegibilidad del claim se fija en el
            # futuro (updated_at = ahora + retry_after - cooldown), de modo que
            # el claim expirado solo la reclama pasado Retry-After. Sin esto
            # el reconciliador reintentaria DENTRO de la ventana del proveedor.
            values["updated_at"] = datetime.now(UTC) + timedelta(
                seconds=retry_after - STALE_CLAIM_SECONDS
            )
        db.execute(
            update(AlertDelivery)
            .where(
                AlertDelivery.alert_id == alert.id,
                AlertDelivery.channel == channel,
            )
            .values(**values)
        )
        db.commit()

    def _dispatch_telegram(self, settings, payload: dict) -> dict:
        token = settings.telegram_bot_token
        chat_id = payload.get("chat_id")
        if not settings.telegram_enabled or not token or not chat_id:
            return self._result(
                "not_configured",
                error="Telegram requiere TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN y un destino verificado",
            )
        text = self._telegram_text(payload)
        endpoint = (
            f"{settings.telegram_api_base_url.rstrip('/')}/bot{token}/sendMessage"
        )
        try:
            with httpx.Client(timeout=settings.telegram_timeout_seconds) as client:
                response = client.post(
                    endpoint,
                    json={"chat_id": chat_id, "text": text},
                )
                response.raise_for_status()
                body = response.json()
                if body.get("ok") is not True:
                    code = body.get("error_code")
                    return self._result(
                        "throttled" if code == 429 else "failed",
                        error="Telegram rechazó el mensaje",
                        retry_after=min(int((body.get("parameters") or {}).get("retry_after") or 600), RETRY_AFTER_CAP_SECONDS) if code == 429 else None,
                    )
            return self._result("delivered")
        except Exception as exc:
            # Never persist upstream exception text: it may contain the bot token,
            # the fully-qualified endpoint, the request body, or a response body.
            return self._result(
                self._classify_send_error(exc),
                error=type(exc).__name__,
                retry_after=self._extract_retry_after(exc),
            )

    @staticmethod
    def _telegram_text(payload: dict) -> str:
        import re
        from urllib.parse import urlsplit

        company = payload.get("company_name") or payload.get("ticker")
        headline = payload.get("source_headline")
        match = re.search(r"\b(10-K|10-Q|8-K|20-F|6-K)\b", headline, re.IGNORECASE) if isinstance(headline, str) else None
        en = payload.get("language") == "en"
        if company and (match or payload.get("type") in ("tracked_news", "news_material_update")):
            kind = match.group(1).upper() if match else ("News" if en else "Noticia")
            date = payload.get("event_date")
            if isinstance(date, datetime):
                # Label a GDELT first-seen as detection, never publication.
                date_label = date.strftime("%d/%m/%Y")
                detected = "detected " if en else "detectada "
                suffix = f" · {detected if payload.get('event_date_source') == 'gdelt_first_seen' else ''}{date_label}"
            else:
                suffix = ""
            if en:
                summary = (f"{kind} filing linked to {company}; check the source before changing the thesis."
                           if match else f"News about {company}; check the source before drawing conclusions.")
            else:
                summary = (f"Documento {kind} asociado a {company}; revisa la fuente antes de cambiar la tesis."
                           if match else f"Noticia sobre {company}; revisa la fuente antes de sacar conclusiones.")
            text = f"{company} · {kind}{suffix}\n{summary}"
            url = payload.get("source_url")
            try:
                parsed = urlsplit(url) if isinstance(url, str) else None
                safe = bool(parsed and parsed.scheme in ("http", "https") and parsed.hostname
                            and not parsed.username and not parsed.password)
            except ValueError:
                safe = False
            ticker = payload.get("ticker")
            if ticker and re.fullmatch(r"[A-Z0-9.\-]{1,20}", ticker):
                text += (f"\nSee affected thesis: {ticker} (in the app)" if en
                         else f"\nVer tesis afectada: {ticker} (en la app)")
            if safe:
                text += f"\nOpen document: {url}" if en else f"\nAbrir documento: {url}"
            # Plain-text delivery has no expandable detail; omit machine traces.
            return text[:4090]
        if payload.get("type") == "dca_level":
            # El mensaje DCA ya va redactado en espanol con titular y metricas.
            return str(payload.get("message") or payload.get("title") or "")[:4090]
        if payload.get("type") == "macro_event":
            # Redactado en espanol con hora, fuente y etiqueta; sin ids tecnicos.
            return f"{payload.get('title') or ''}\n{payload.get('message') or ''}"[:4090]
        if payload.get("type") == "earnings_reminder":
            # Aviso de resultados ya redactado en espanol (fecha, estado de la
            # fecha y fuente); sin ids tecnicos, igual que el recordatorio macro.
            return f"{payload.get('title') or ''}\n{payload.get('message') or ''}"[:4090]
        # Non-filing/non-news alerts retain their established delivery format.
        text = (
            f"[{payload['severity'].upper()}] {payload['title']}\n"
            f"{payload['message']}\n\n"
            f"Ticker/company id: {payload['company_id']}\n"
            f"Alert id: {payload['alert_id']}"
        )
        jev = payload.get("jev_urgency") or {}
        if jev.get("label"):
            try:
                conf = float(jev.get("confidence") or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            text += f"\nJev urgency: {jev['label']} (conf {conf:.2f})"
        return text[:4090]

    def _result(
        self,
        status: str,
        error: str | None = None,
        retry_after: int | None = None,
    ) -> dict:
        result = {
            "status": status,
            "attempted_at": datetime.now(UTC).isoformat(),
            "error": error,
        }
        if retry_after is not None:
            result["retry_after"] = retry_after
        return result
