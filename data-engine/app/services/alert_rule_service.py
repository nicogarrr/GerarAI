from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AlertRule,
    Company,
    EarningsRun,
    FinancialFact,
    MarketPrice,
    NewsEvent,
    Position,
    ResearchAlert,
)
from app.services.notification_service import NotificationService
from app.services.portfolio_ledger_service import trade_price_fallbacks
from app.services.price_freshness import close_is_stale
from app.services.price_units import close_in_company_currency, listing_price
from app.services.review_alert_service import ReviewAlertService
from app.services.trading_sessions import missing_sessions

# Operators the evaluator understands. `create()` did not validate the operator,
# so a rule created with "!=" (which the screener's comparator table does accept)
# could never fire and always reported `matched: false`.
_OPERATORS = frozenset({">", "<", ">=", "<=", "==", "!="})

_NUMERIC_RULE_TYPES = frozenset({"price_above", "price_below", "price_change"})


def _numeric_threshold(value: Any) -> float | None:
    """Umbral numérico finito o None. Rechaza texto («abc»), separadores de miles
    ambiguos («1,234»), booleanos y NaN/Infinity."""
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    result = float(number)
    if not math.isfinite(result):
        # «1e400» es un Decimal finito pero no cabe en un float: «avisar si baja
        # de 1e400» se cumplía siempre (y «si sube» nunca).
        return None
    return result


def _is_non_finite(value: Any) -> bool:
    """True for NaN/Infinity (float or its string form). Non-numeric text is not
    judged here: equality on text keeps its existing meaning in ``_matches``."""
    try:
        return not Decimal(str(value).strip()).is_finite()
    except (InvalidOperation, ValueError):
        return False


_EVENT_KINDS = frozenset({"news_event", "earnings_run"})


class AlertRuleService:
    def create(
        self,
        db: Session,
        company: Company,
        *,
        rule_type: str,
        operator: str,
        value: float | str,
        cooldown_seconds: int = 3600,
    ) -> AlertRule:
        if rule_type in {"news", "earnings"}:
            operator, value = ">", 0
        elif operator not in _OPERATORS:
            # A rule created with an unknown operator can never fire and always
            # reports `matched: false`, which reads as "the threshold was not
            # reached" rather than "this rule is broken".
            raise ValueError(
                f"Unsupported alert operator: {operator!r}. "
                f"Expected one of {sorted(_OPERATORS)}."
            )
        elif _is_non_finite(value):
            # NaN/Infinity parse as Decimal but ordering comparisons with NaN raise
            # InvalidOperation inside evaluate_all and one such rule would abort the
            # whole evaluation pass; a threshold that is not a finite number is
            # meaningless for every operator.
            raise ValueError(f"Alert threshold must be a finite number: {value!r}")
        if rule_type in _NUMERIC_RULE_TYPES and _numeric_threshold(value) is None:
            # Un umbral de texto en una regla de precio/cambio nunca puede
            # cumplirse (``_matches`` no ordena texto): se rechaza al crearla.
            raise ValueError(f"Alert threshold must be a number: {value!r}")
        name = f"{company.ticker}: {rule_type} {operator} {value}"[:300]
        target = self._target(rule_type)
        rule = db.scalar(
            select(AlertRule).where(
                AlertRule.company_id == company.id,
                AlertRule.name == name,
            )
        )
        if rule is None:
            rule = AlertRule(company_id=company.id, name=name)
            db.add(rule)
        rule.rule_type = rule_type
        rule.condition = {"operator": operator, "value": value}
        rule.target = target
        rule.severity = "medium"
        rule.channels = ["in_app"]
        settings = get_settings()
        if settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id:
            rule.channels.append("telegram")
        rule.active = True
        rule.cooldown_seconds = max(0, cooldown_seconds)
        rule.metadata_ = {"ticker": company.ticker, "source": "user"}
        db.commit()
        db.refresh(rule)
        return rule

    def evaluate_all(self, db: Session) -> list[dict[str, Any]]:
        # Los criterios medibles de las tesis entran como reglas
        # `thesis_invalidation` antes de la pasada: mismo evaluador, mismo
        # cooldown y misma entrega por canales que el resto de reglas.
        from app.services.thesis_invalidation_rules import sync_all_thesis_rules

        sync_all_thesis_rules(db)
        rules = list(
            db.scalars(
                select(AlertRule)
                .where(AlertRule.active.is_(True))
                .order_by(AlertRule.id)
            ).all()
        )
        results = [self.evaluate(db, rule, commit=False) for rule in rules]
        db.commit()
        return results

    def evaluate(
        self, db: Session, rule: AlertRule, *, commit: bool = True
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        company = db.get(Company, rule.company_id)
        if company is None:
            rule.active = False
            result = {"rule_id": rule.id, "status": "disabled_missing_company"}
            rule.last_result = result
            if commit:
                db.commit()
            return result

        observed, observation = self._observe(db, rule)
        event_kind = observation.get("kind") in _EVENT_KINDS
        stale_observation = observation.get("status") == "stale"
        session_gap = observation.get("status") == "session_gap"
        matched = False if stale_observation or session_gap else self._matches(
            observed,
            str((rule.condition or {}).get("operator") or "=="),
            (rule.condition or {}).get("value"),
        )
        cooldown_until = (
            self._aware(rule.last_triggered_at)
            + timedelta(seconds=rule.cooldown_seconds)
            if rule.last_triggered_at
            else None
        )
        cooldown_active = bool(cooldown_until and cooldown_until > now)
        triggered = bool(matched and not cooldown_active)
        # Triage Jev de la alerta: 1 sola llamada por alerta DISPARADA (nunca por
        # evaluación). Coste ~$0.042/MTok in. Fallback: sin TYPESAFE_API_KEY o
        # ante cualquier error, la alerta se emite igual sin `jev_urgency`.
        jev_urgency: dict | None = None
        if triggered:
            alert_message = (
                f"{company.ticker}: se cumplió la regla «{rule.name}» "
                f"(valor observado: {observed})."
            )
            if observation.get("kind") == "thesis_metric":
                from app.services.thesis_invalidation_rules import (
                    alert_message as thesis_alert_message,
                )

                alert_message = thesis_alert_message(company, rule, observed)
            news_event = None
            if observation.get("kind") == "news_event" and observation.get("news_event_id"):
                news_event = db.get(NewsEvent, observation["news_event_id"])
            if news_event is not None:
                # La alerta cita la noticia concreta (titular de la fuente), no "valor observado: 1".
                alert_message = (
                    f"{company.ticker}: noticia nueva para la regla «{rule.name}»: "
                    f"{news_event.title.strip()}"
                )
            try:
                from app.services.jev_triage_service import (
                    classify_urgency_sync,
                    jev_metadata,
                )

                jev_urgency = jev_metadata(classify_urgency_sync(alert_message))
            except Exception:  # noqa: BLE001 — Jev best-effort, nunca rompe alertas
                jev_urgency = None
            alert_metadata: dict[str, Any] = {
                "alert_rule_id": rule.id,
                "condition": rule.condition,
                "target": rule.target,
                "observation": observation,
            }
            if news_event is not None:
                alert_metadata["news_event_id"] = news_event.id
                if news_event.url:
                    alert_metadata["source_url"] = news_event.url
            # Correlación para el digest visual. No suprime la entrega:
            # una similitud de texto no prueba que dos fuentes sean idénticas.
            # nosemgrep: gerarai-broad-except-pass -- marca opcional de Jev (best-effort); no decide la alerta
            try:
                from app.services.jev_gates import DIGEST_CRITERIA, mark_only
                previous = db.scalar(select(ResearchAlert).where(
                    ResearchAlert.company_id == company.id,
                    ResearchAlert.status == "open",
                    ResearchAlert.created_at >= now - timedelta(days=1),
                ).order_by(ResearchAlert.created_at.desc()).limit(1))
                if previous:
                    mark = mark_only("alert_digest", f"CURRENT: {alert_message}\nPREVIOUS: {previous.message}",
                        "Are these the same dated fact or distinct facts? Tag only; never suppress an alert.",
                        DIGEST_CRITERIA)
                    if mark:
                        alert_metadata["jev_digest"] = {**mark, "related_alert_id": previous.id}
            except Exception:  # noqa: BLE001
                pass
            if jev_urgency is not None:
                alert_metadata["jev_urgency"] = jev_urgency
            alert = ReviewAlertService().emit_alert(
                db,
                company_id=company.id,
                alert_type=rule.rule_type,
                severity=rule.severity,
                title=rule.name,
                message=alert_message,
                fingerprint_parts=[
                    "alert_rule",
                    str(rule.id),
                    # Una huella por ocurrencia: tras el cooldown, un nuevo cruce
                    # crea una alerta nueva y se entrega otra vez.
                    str((rule.trigger_count or 0) + 1),
                ],
                channels=rule.channels,
                metadata=alert_metadata,
            )
            # Deliver on the channels the rule asked for. `emit_alert` only
            # records the alert; the only caller of `NotificationService
            # .dispatch` was the manual `POST /alerts/{id}/dispatch` endpoint,
            # so a user who configured Telegram for their rules never received
            # anything until they found the alert in the UI and pressed
            # "dispatch" by hand. Two implementations of the same "deliver on
            # these channels" contract existed and only one was wired.
            deliveries = NotificationService().dispatch(db, alert)
            alert_metadata["deliveries"] = deliveries
            alert.metadata_ = {**(alert.metadata_ or {}), "deliveries": deliveries}
            rule.last_triggered_at = now
            rule.trigger_count += 1
        result = {
            "rule_id": rule.id,
            "status": (
                "triggered"
                if triggered
                else "skipped_stale_observation"
                if stale_observation
                else "skipped_session_gap"
                if session_gap
                else "evaluated"
            ),
            "matched": bool(matched),
            "cooldown_active": cooldown_active,
            "observed": self._json_value(observed),
            "observation": observation,
            "jev_urgency": jev_urgency,
        }
        if event_kind:
            self._advance_event_cursor(
                rule, now, observation, pending=bool(matched and not triggered)
            )
        rule.last_evaluated_at = now
        rule.last_value = None if observed is None else str(observed)[:160]
        rule.last_result = result
        if commit:
            db.commit()
            db.refresh(rule)
        return result

    @staticmethod
    def _listing(db: Session, rule: AlertRule) -> tuple[str | None, str | None]:
        """(bolsa, ticker) de la empresa de la regla, para la hora de cierre."""
        company = db.get(Company, rule.company_id) if rule.company_id is not None else None
        return (company.exchange, company.ticker) if company is not None else (None, None)

    def _observe(self, db: Session, rule: AlertRule) -> tuple[Any, dict[str, Any]]:
        kind = str((rule.target or {}).get("kind") or "")
        if kind == "market_price":
            prices = list(
                db.scalars(
                    select(MarketPrice)
                    .where(MarketPrice.company_id == rule.company_id)
                    .order_by(desc(MarketPrice.date))
                    .limit(2)
                ).all()
            )
            if prices:
                age_days = (date.today() - prices[0].date).days
                # El umbral se pide «en <divisa de la empresa>» (ficha): el
                # cierre va a esa misma unidad. TSCO.L cotiza en GBp y reporta
                # en GBP: comparar 250,5 peniques con «3 GBP» disparaba al
                # instante. Otra divisa sin tipo FX: sin observacion.
                observed = self._price_in_threshold_unit(
                    db, rule, Decimal(prices[0].close), unit=prices[0].quote_currency, on=prices[0].date
                )
                if observed is None:
                    return None, {"kind": kind, "status": "mixed_units", "date": prices[0].date.isoformat()}
                return observed, {
                    "kind": kind,
                    "market_price_id": prices[0].id,
                    "date": prices[0].date.isoformat(),
                    "age_days": age_days,
                    "status": (
                        "stale"
                        if close_is_stale(
                            prices[0].date,
                            self._listing(db, rule)[0],
                            get_settings().market_price_max_age_days,
                            ticker=self._listing(db, rule)[1],
                        )
                        else "fresh"
                    ),
                }
            position = db.scalar(
                select(Position)
                .where(
                    Position.company_id == rule.company_id,
                    Position.valuation_hold_reason.is_(None),
                )
                .order_by(desc(Position.as_of))
                .limit(1)
            )
            if position is not None and position.company_id in trade_price_fallbacks(
                db, [position], tenant_id=position.tenant_id
            ):
                # Sin cotización real: el «precio» de la posición es el de tu
                # propia compra/venta (auditoría A3), no un precio de mercado.
                # Con él, «avísame si baja de 13» saltaba nada más comprar a 12,50.
                return None, {"kind": kind, "status": "missing", "position_id": position.id}
            position_price = (
                self._price_in_threshold_unit(
                    db, rule, Decimal(position.market_price), unit=position.currency, on=position.as_of
                )
                if position and position.market_price is not None
                else None
            )
            if position and position.market_price is not None and position_price is None:
                return None, {"kind": kind, "status": "mixed_units", "position_id": position.id}
            return (
                (
                    position_price,
                    {
                        "kind": kind,
                        "position_id": position.id,
                        "date": position.as_of.isoformat(),
                        "age_days": (date.today() - position.as_of).days,
                        "status": (
                            "stale"
                            if close_is_stale(
                                position.as_of,
                                self._listing(db, rule)[0],
                                get_settings().market_price_max_age_days,
                                ticker=self._listing(db, rule)[1],
                            )
                            else "fresh"
                        ),
                    },
                )
                if position and position.market_price is not None
                else (None, {"kind": kind, "status": "missing"})
            )
        if kind == "price_change_percent":
            prices = list(
                db.scalars(
                    select(MarketPrice)
                    .where(MarketPrice.company_id == rule.company_id)
                    .order_by(desc(MarketPrice.date))
                    .limit(2)
                ).all()
            )
            if len(prices) < 2:
                return None, {"kind": kind, "status": "missing_two_prices"}
            latest, previous = prices
            company = db.get(Company, rule.company_id)
            # La regla es una variacion de UNA sesion: si entre los dos ultimos
            # cierres guardados falta alguna sesion de la bolsa (no un festivo),
            # el cociente es un movimiento de varias sesiones presentado como
            # diario. Sin observacion hasta tener dos sesiones consecutivas.
            gap = missing_sessions(db, company, previous.date, latest.date)
            if gap:
                return None, {
                    "kind": kind,
                    "status": "session_gap",
                    "latest_date": latest.date.isoformat(),
                    "previous_date": previous.date.isoformat(),
                    "missing_sessions": [day.isoformat() for day in gap],
                }
            # Cierres ajustados cuando ambas filas los traen: un split o una
            # distribución entre las dos sesiones no es un movimiento de precio
            # (200 -> 110 tras un split 2:1 es +10 %, no -45 %). Mismo criterio
            # que el digest de cartera (portfolio_moves_service). Sin ajuste en
            # alguna fila se usa el cierre cotizado, como hasta ahora.
            if (
                latest.adj_close is not None
                and previous.adj_close is not None
                and latest.adj_close > 0
                and previous.adj_close > 0
            ):
                current_value, previous_value = latest.adj_close, previous.adj_close
                basis = "adj_close"
            else:
                current_value, previous_value = latest.close, previous.close
                basis = "close"
            if previous_value is None or current_value is None or previous_value == 0:
                return None, {"kind": kind, "status": "missing_two_prices"}
            # Cada cierre en la divisa principal de SU cotizacion (70 GBp y
            # 0,71 GBP son 0,70 y 0,71 GBP): mezclar peniques y libras daba
            # -99 % o +9.900 % y disparaba la alerta. Dos monedas distintas
            # no son un movimiento de precio.
            # Misma etiqueta de unidad (o ambas sin etiqueta, filas legacy): el
            # cociente no depende de la unidad y se usa tal cual.
            if company is not None and latest.quote_currency != previous.quote_currency:
                current_listed = listing_price(
                    Decimal(current_value), quote_currency=latest.quote_currency, company=company
                )
                previous_listed = listing_price(
                    Decimal(previous_value), quote_currency=previous.quote_currency, company=company
                )
                if (
                    current_listed is None
                    or previous_listed is None
                    or current_listed[1] != previous_listed[1]
                ):
                    return None, {"kind": kind, "status": "mixed_units", "basis": basis}
                current_value, previous_value = current_listed[0], previous_listed[0]
                if previous_value == 0:
                    return None, {"kind": kind, "status": "missing_two_prices"}
            change = (Decimal(current_value) / Decimal(previous_value) - 1) * 100
            age_days = (date.today() - prices[0].date).days
            return change, {
                "kind": kind,
                "price_ids": [prices[0].id, prices[1].id],
                "latest_date": prices[0].date.isoformat(),
                "basis": basis,
                "age_days": age_days,
                "status": (
                    "stale"
                    if close_is_stale(
                        prices[0].date,
                        company.exchange if company is not None else None,
                        get_settings().market_price_max_age_days,
                        ticker=company.ticker if company is not None else None,
                    )
                    else "fresh"
                ),
            }
        # Los eventos usan un cursor propio: avanzar last_evaluated_at durante el
        # cooldown consumia el evento sin avisar de el.
        since = (
            self._event_cursor(rule)
            or self._aware(rule.last_evaluated_at)
            or self._aware(rule.created_at)
        )
        if kind == "news_event":
            statement = (
                select(NewsEvent)
                .where(NewsEvent.company_id == rule.company_id,
                       NewsEvent.event_type != "ownership_disclosure")
                .order_by(desc(NewsEvent.created_at))
                .limit(1)
            )
            if since:
                statement = statement.where(NewsEvent.created_at > since)
            event = db.scalar(statement)
            # Sin titular verificable no hay nada que citar: no dispara.
            has_title = bool(event and (event.title or "").strip())
            if has_title:
                from app.services.news_identity import equivalent_news_alert

                if equivalent_news_alert(
                    db, company_id=rule.company_id, url=event.url, title=event.title
                ) is not None:
                    # Otra vía ya avisó de esta noticia: no se duplica el aviso.
                    return 0, {"kind": kind, "news_event_id": None, "suppressed": "duplicate_news"}
            return (1 if has_title else 0), {
                "kind": kind,
                "news_event_id": event.id if has_title else None,
            }
        if kind == "earnings_run":
            statement = (
                select(EarningsRun)
                .where(EarningsRun.company_id == rule.company_id)
                .order_by(desc(EarningsRun.created_at))
                .limit(1)
            )
            if since:
                statement = statement.where(EarningsRun.created_at > since)
            run = db.scalar(statement)
            return (1 if run else 0), {
                "kind": kind,
                "earnings_run_id": run.id if run else None,
            }
        if kind == "thesis_metric":
            from app.services.thesis_invalidation_rules import observe

            return observe(db, rule)
        if kind == "financial_metric":
            metric = str((rule.target or {}).get("metric") or "")
            fact = db.scalar(
                select(FinancialFact)
                .where(
                    FinancialFact.company_id == rule.company_id,
                    FinancialFact.metric == metric,
                )
                .order_by(desc(FinancialFact.fiscal_year), desc(FinancialFact.created_at))
                .limit(1)
            )
            return (
                (Decimal(fact.value), {"kind": kind, "financial_fact_id": fact.id})
                if fact
                else (None, {"kind": kind, "status": "missing"})
            )
        return None, {"kind": kind, "status": "unsupported_target"}

    @staticmethod
    def _price_in_threshold_unit(
        db: Session, rule: AlertRule, value: Decimal, *, unit: str | None, on: date
    ) -> Decimal | None:
        """Precio en la divisa de la empresa, la unidad en la que se pide el umbral.

        Sin unidad declarada (filas legacy) o con la misma unidad, tal cual.
        """
        if not unit:
            return value
        company = db.get(Company, rule.company_id)
        if company is None:
            return value
        return close_in_company_currency(db, value, quote_currency=unit, company=company, on=on)

    @staticmethod
    def _matches(observed: Any, operator: str, expected: Any) -> bool:
        if observed is None:
            return False
        if operator not in _OPERATORS:
            return False
        try:
            left = Decimal(str(observed))
            right = Decimal(str(expected))
        except (InvalidOperation, TypeError, ValueError):
            # Not comparable as a number. Equality on the string form is
            # meaningful; ordering is not. The previous fallback compared
            # strings for every operator, so "1,234" < "1000" was decided by
            # ASCII order (',' is 0x2C, '0' is 0x30) and the SIGN of the
            # comparison silently inverted for any non-numeric value.
            if operator == "==":
                return str(observed) == str(expected)
            if operator == "!=":
                return str(observed) != str(expected)
            return False
        if not (left.is_finite() and right.is_finite()):
            # Legacy rows (created before the threshold was validated) or a
            # non-finite observation: ordering with NaN raises InvalidOperation.
            # Not comparable -> no match, never an exception for the whole pass.
            return False
        operations = {
            ">": lambda: left > right,
            "<": lambda: left < right,
            ">=": lambda: left >= right,
            "<=": lambda: left <= right,
            "==": lambda: left == right,
            "!=": lambda: left != right,
        }
        return bool(operations[operator]())

    @staticmethod
    def _target(rule_type: str) -> dict[str, Any]:
        return {
            "price_above": {"kind": "market_price"},
            "price_below": {"kind": "market_price"},
            "price_change": {"kind": "price_change_percent"},
            "news": {"kind": "news_event"},
            "earnings": {"kind": "earnings_run"},
        }[rule_type]

    @staticmethod
    def _event_cursor(rule: AlertRule) -> datetime | None:
        raw = (rule.metadata_ or {}).get("event_cursor")
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(str(raw))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def _advance_event_cursor(
        self, rule: AlertRule, now: datetime, observation: dict[str, Any], *, pending: bool
    ) -> None:
        """Mueve el cursor de eventos solo si no queda un evento pendiente.

        Pendiente = coincide pero el cooldown impidio avisar: el cursor se queda
        donde estaba (o en el ultimo instante conocido) para verlo al acabar.
        """
        current = self._event_cursor(rule)
        if pending:
            if current is None:
                current = self._aware(rule.last_evaluated_at) or self._aware(rule.created_at)
            new = current
        else:
            new = now
        if new is None:
            return
        rule.metadata_ = {**(rule.metadata_ or {}), "event_cursor": new.isoformat()}

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value
