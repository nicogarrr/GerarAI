"""Errores de API que la UI muestra verbatim (i18n B4).

Decision del carril B: SOLO migran a este modulo los ``detail=`` redactados
en espanol natural, porque el frontend los ensena tal cual (lib/types/errors.ts
propaga ``detail`` al usuario). Los identificadores tecnicos en ingles
(``"Company not found"``, ``"plan_currency_required"``, ``detail=str(exc)`` y
los errores del API de operaciones ``workflows``) son errores INTERNOS de API:
no se traducen y la interfaz no los muestra en crudo.

El espanol queda byte a byte identico al literal anterior; el ingles se usa
cuando el idioma activo de la peticion es "en" (flag I18N_GENERATION_ENABLED
+ cabecera/tenant), y sin flag todo sale en espanol como antes.
"""
from __future__ import annotations

from fastapi import HTTPException

from app.core.i18n import current_language

_MESSAGES: dict[str, dict[str, str]] = {
    "verified_identity_required": {
        "es": "Se requiere una identidad verificada",
        "en": "A verified identity is required",
    },
    "symbol_not_recognized": {
        "es": "Símbolo no reconocido: {ticker}. Comprueba que exista en bolsa.",
        "en": "Symbol not recognized: {ticker}. Check that it is listed on an exchange.",
    },
    "chat_link_required": {
        "es": "Vincula y confirma este chat con Asistenta antes de activarlo",
        "en": "Link and confirm this chat with Asistenta before enabling it",
    },
    "subscription_owner_only": {
        "es": "Solo el propietario puede cambiar esta suscripción",
        "en": "Only the owner can change this subscription",
    },
    "push_not_configured": {
        "es": "Las notificaciones push no están configuradas en el servidor",
        "en": "Push notifications are not configured on the server",
    },
    "push_endpoint_unsupported": {
        "es": "Endpoint de notificaciones no admitido",
        "en": "Notification endpoint not supported",
    },
    "device_belongs_to_other": {
        "es": "Este dispositivo pertenece a otro usuario",
        "en": "This device belongs to another user",
    },
    "enable_notifications_first": {
        "es": "Activa las notificaciones en este dispositivo antes de elegir tipos",
        "en": "Enable notifications on this device before choosing types",
    },
    "feed_not_found": {
        "es": "Feed no encontrado",
        "en": "Feed not found",
    },
    "company_not_found": {
        "es": "Empresa no encontrada",
        "en": "Company not found",
    },
    "company_not_found_dot": {
        "es": "Empresa no encontrada.",
        "en": "Company not found.",
    },
    "company_not_found_ticker": {
        "es": "Empresa no encontrada: {ticker}",
        "en": "Company not found: {ticker}",
    },
    "company_not_registered": {
        "es": "Empresa no registrada",
        "en": "Company not registered",
    },
    "research_identity_required": {
        "es": "Se requiere una identidad de Research",
        "en": "A Research identity is required",
    },
    "unsupported_language": {
        "es": "Idioma no soportado: {language!r}. Soportados: {supported}.",
        "en": "Unsupported language: {language!r}. Supported: {supported}.",
    },
    "saved_key_unreadable": {
        "es": "No se pudo leer la clave guardada; vuelve a introducirla.",
        "en": "The saved key could not be read; enter it again.",
    },
    "deletion_request_failed": {
        "es": "No se pudo procesar la solicitud de borrado.",
        "en": "The deletion request could not be processed.",
    },
    "no_candles_available": {
        "es": "Sin velas disponibles",
        "en": "No candles available",
    },
    "no_quote_available": {
        "es": "Sin cotización disponible",
        "en": "No quote available",
    },
    "quotes_batch_too_large": {
        "es": "Demasiados símbolos en el lote (máx. 30)",
        "en": "Too many symbols in the batch (max 30)",
    },
    "proposal_not_found": {
        "es": "Propuesta no encontrada",
        "en": "Proposal not found",
    },
    "no_real_price_to_close": {
        "es": "Sin precio real reciente para cerrar",
        "en": "No recent real price to close",
    },
    "missing_quote_after_entry": {
        "es": "Falta una cotización posterior a la entrada",
        "en": "Missing a quote after the entry",
    },
    "proposal_rejected": {
        "es": "Propuesta rechazada: {reason}",
        "en": "Proposal rejected: {reason}",
    },
    "ibkr_account_not_configured": {
        "es": "Falta configurar la cuenta IBKR esperada.",
        "en": "The expected IBKR account is not configured.",
    },
    "flex_import_disabled": {
        "es": "La importación Flex no está habilitada para esta cuenta.",
        "en": "Flex import is not enabled for this account.",
    },
    "invalid_ticker": {
        "es": "Ticker no válido",
        "en": "Invalid ticker",
    },
    "ticker_invalid": {
        "es": "Ticker inválido",
        "en": "Invalid ticker",
    },
    "encryption_keys_unavailable": {
        "es": "El cifrado de claves no esta disponible; no se ha guardado nada.",
        "en": "Key encryption is not available; nothing was saved.",
    },
    "encryption_keys_not_configured": {
        "es": "El cifrado de claves no esta configurado (LLM_SETTINGS_ENCRYPTION_KEY); no se ha guardado nada.",
        "en": "Key encryption is not configured (LLM_SETTINGS_ENCRYPTION_KEY); nothing was saved.",
    },
    "encryption_unavailable_token": {
        "es": "El cifrado no está disponible. No se ha guardado el token.",
        "en": "Encryption is not available. The token was not saved.",
    },
    "model_unavailable": {
        "es": "El modelo no está disponible ahora; reintenta más tarde.",
        "en": "The model is not available right now; try again later.",
    },
    "debate_timeout": {
        "es": "El debate tardó demasiado; vuelve más tarde",
        "en": "The debate took too long; come back later",
    },
    "llm_budget_exhausted": {
        "es": "Presupuesto LLM agotado, vuelve más tarde",
        "en": "LLM budget exhausted, come back later",
    },
    "debate_invalid_response": {
        "es": "El debate devolvió una respuesta no válida; vuelve más tarde",
        "en": "The debate returned an invalid response; come back later",
    },
    "user_context_required": {
        "es": "Se necesita el contexto del usuario.",
        "en": "User context is required.",
    },
    "ticker_not_in_watchlist": {
        "es": "Ese ticker no está en tu watchlist",
        "en": "That ticker is not in your watchlist",
    },
    "ticker_not_in_watchlist_or_portfolio": {
        "es": "El ticker no está en tu watchlist ni en tu cartera",
        "en": "The ticker is not in your watchlist or your portfolio",
    },
    "ownership_scope_limited": {
        "es": "{ticker} no esta en la watchlist ni en la cartera; la ingesta SC 13D/13G esta acotada a emisores seguidos",
        "en": "{ticker} is not in the watchlist or the portfolio; SC 13D/13G ingestion is limited to followed issuers",
    },
    "account_identity_required_bg": {
        "es": "Se requiere identidad de cuenta para ejecutar en segundo plano.",
        "en": "Account identity is required to run in the background.",
    },
    "single_run_unavailable": {
        "es": "No se puede asegurar una ejecución única ahora.",
        "en": "A single run cannot be guaranteed right now.",
    },
    "dca_evaluation_in_progress": {
        "es": "Ya hay una evaluación DCA en curso en tu cuenta.",
        "en": "A DCA evaluation is already in progress on your account.",
    },
    "run_confirmation_failed": {
        "es": "No se pudo confirmar la ejecución; revisa su estado antes de repetir.",
        "en": "The run could not be confirmed; check its status before retrying.",
    },
    "run_not_found": {
        "es": "Ejecución no encontrada en tu cuenta.",
        "en": "Run not found in your account.",
    },
    "ticker_without_dca_signal": {
        "es": "Ticker sin señal DCA evaluada (añádelo a watchlist o cartera)",
        "en": "Ticker without an evaluated DCA signal (add it to your watchlist or portfolio)",
    },
    "start_after_end": {
        "es": "El inicio va después del final",
        "en": "The start is after the end",
    },
    "history_download_failed": {
        "es": "No se pudo descargar el histórico de {key}",
        "en": "Could not download the history for {key}",
    },
    "flow_topic_not_configured": {
        "es": "Tema de flujo no configurado",
        "en": "Flow topic not configured",
    },
    "export_failed": {
        "es": "No se pudo generar la exportación. No se ha enviado ningún dato; inténtalo de nuevo.",
        "en": "The export could not be generated. No data was sent; try again.",
    },
    "deletion_residue": {
        "es": "No se pudo completar el borrado: quedan datos en el almacenamiento externo y no se ha borrado nada en la base de datos. Vuelve a intentarlo.",
        "en": "The deletion could not be completed: data remains in external storage and nothing was deleted from the database. Try again.",
    },
    "deletion_failed": {
        "es": "No se pudo borrar la cuenta. No se ha confirmado ningún borrado parcial; vuelve a intentarlo.",
        "en": "The account could not be deleted. No partial deletion was confirmed; try again.",
    },
    "fmp_plan_market_uncovered": {
        "es": "El plan gratuito de FMP no cubre este mercado. Para emisores europeos usa la fuente ESEF y para americanos la SEC.",
        "en": "The free FMP plan does not cover this market. For European issuers use the ESEF source and for US issuers the SEC.",
    },
}


def ui_error(status_code: int, key: str, /, **fmt: object) -> HTTPException:
    """HTTPException cuyo ``detail`` sigue el idioma activo (defecto: espanol).

    El espanol es siempre la cadena original byte a byte; sin flag i18n el
    idioma activo es "es" y nada cambia para los clientes actuales.
    """
    messages = _MESSAGES[key]
    template = messages.get(current_language()) or messages["es"]
    return HTTPException(
        status_code=status_code,
        detail=template.format(**fmt) if fmt else template,
    )
