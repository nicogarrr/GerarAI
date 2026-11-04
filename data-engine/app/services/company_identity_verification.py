"""Verificación de identidad de un ticker fuera del maestro por doble coincidencia.

Política: un ticker desconocido solo abre ficha cuando DOS fuentes
independientes coinciden en la identidad del emisor y no hay homónimo
conocido con otra identidad en el maestro:

1. SEC EDGAR (`company_tickers.json`): el ticker existe y su razón social es
   compatible con el nombre que da el proveedor de mercado.
2. Proveedor de mercado (Finnhub `/stock/profile2`): el símbolo existe, tiene
   nombre propio y cotiza en una bolsa de EE. UU. (la SEC solo cubre emisores
   que presentan ante ella, incluidos los foreign private issuers 20-F/6-K
   como BWMX en Nasdaq).

Sin doble coincidencia NO se crea identidad: se devuelve el veredicto con la
evidencia de cada fuente y el motivo, y la ficha sigue bloqueada con un
estado honesto. Nunca se adoptan datos de una sola fuente como identidad.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Marcadores de bolsas de EE. UU. tal como los devuelve Finnhub profile2
# (campo `exchange`, p. ej. "NASDAQ NMS - GLOBAL MARKET", "NEW YORK STOCK EXCHANGE").
_US_EXCHANGE_MARKERS = ("NASDAQ", "NYSE", "NEW YORK STOCK", "NYSE AMERICAN", "NYSE ARCA", "BATS", "CBOE", "IEX")

# Coletillas societarias sin valor distintivo, en varios idiomas.
_LEGAL_SUFFIXES = {
    "inc", "corp", "corporation", "co", "company", "ltd", "llc", "lp", "plc",
    "sa", "saa", "sab", "sapi", "cv", "se", "nv", "ag", "spa", "srl", "bv",
    "de", "the", "group", "holdings", "holding", "international", "intl",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _norm_text(value: str) -> str:
    """Minúsculas sin acentos ni puntuación, para comparar razones sociales."""
    ascii_form = (
        unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    )
    return " ".join(_TOKEN_RE.findall(ascii_form.lower()))


def _distinctive_tokens(name: str) -> set[str]:
    return {t for t in _norm_text(name).split() if t not in _LEGAL_SUFFIXES and len(t) > 1}


def names_compatible(sec_name: str, provider_name: str) -> bool:
    """Compatibilidad conservadora de razón social entre SEC y proveedor.

    Exige que TODOS los tokens distintivos del nombre más corto estén en el
    otro (Betterware de Mexico ⊆ Betterware de Mexico SAPI de CV) o que el
    solape cubra al menos dos tercios de ambos lados con 2+ tokens. Cualquier
    otra cosa se trata como NO coincidente (fail closed).
    """
    a, b = _distinctive_tokens(sec_name), _distinctive_tokens(provider_name)
    if not a or not b:
        return False
    overlap = a & b
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if shorter and shorter <= longer:
        return True
    return bool(overlap) and len(overlap) >= 2 and len(overlap) >= (2 * min(len(a), len(b)) + 2) // 3


def is_us_exchange(exchange: str | None) -> bool:
    value = (exchange or "").upper()
    return any(marker in value for marker in _US_EXCHANGE_MARKERS)


@dataclass(frozen=True)
class IdentityVerdict:
    ticker: str
    verified: bool
    reasons: list[str] = field(default_factory=list)
    sec: dict | None = None
    provider: dict | None = None


def compare_identities(
    ticker: str,
    sec_entry: dict | None,
    provider_profile: dict | None,
) -> IdentityVerdict:
    """Veredicto de doble coincidencia. Puro y determinista: testeable sin red.

    ``sec_entry``: fila de company_tickers.json (cik_str, ticker, title).
    ``provider_profile``: respuesta de Finnhub /stock/profile2.
    """
    wanted = ticker.strip().upper()
    reasons: list[str] = []
    sec_evidence = None
    provider_evidence = None

    if sec_entry is not None:
        sec_evidence = {
            "cik": str(sec_entry.get("cik_str", "")),
            "ticker": str(sec_entry.get("ticker", "")).upper(),
            "name": str(sec_entry.get("title", "")),
        }
    if provider_profile is not None:
        provider_evidence = {
            "ticker": str(provider_profile.get("ticker", "")).upper(),
            "name": str(provider_profile.get("name", "") or ""),
            "exchange": str(provider_profile.get("exchange", "") or ""),
            "country": str(provider_profile.get("country", "") or ""),
            "currency": str(provider_profile.get("currency", "") or ""),
        }

    if sec_evidence is None:
        reasons.append("sec_sin_registro: el ticker no presenta ante la SEC")
    if provider_evidence is None or not provider_evidence["name"].strip():
        reasons.append("proveedor_sin_perfil: el proveedor no conoce el símbolo")
        provider_evidence = provider_evidence or None
    if sec_evidence is None or provider_evidence is None:
        return IdentityVerdict(ticker=wanted, verified=False, reasons=reasons,
                               sec=sec_evidence, provider=provider_evidence)

    if sec_evidence["ticker"] != wanted or provider_evidence["ticker"] != wanted:
        reasons.append("ticker_no_coincide: SEC/proveedor no usan el símbolo exacto")
    if not provider_evidence["currency"].strip():
        # La moneda nunca se asume (nada de USD por defecto): sin evidencia del
        # proveedor la ficha no se crea y la UI la muestra como N/D.
        reasons.append("moneda_desconocida: el proveedor no declara la divisa del listado")
    if not is_us_exchange(provider_evidence["exchange"]):
        reasons.append(
            f"mercado_no_sec: la bolsa del proveedor ({provider_evidence['exchange'] or 'desconocida'}) "
            "no es de EE. UU.; la SEC no puede contrastar esa identidad"
        )
    if not names_compatible(sec_evidence["name"], provider_evidence["name"]):
        reasons.append(
            f"nombre_no_coincide: SEC «{sec_evidence['name']}» vs proveedor «{provider_evidence['name']}»"
        )

    return IdentityVerdict(
        ticker=wanted,
        verified=not reasons,
        reasons=reasons,
        sec=sec_evidence,
        provider=provider_evidence,
    )


# Bolsas de EE. UU. donde el ticker de la SEC identifica al emisor. Más amplio
# que _US_EXCHANGE_MARKERS (que decide si se ABRE una ficha nueva): aquí solo
# se decide si hace falta contrastar la razón social, y un OTC/AMEX de EE. UU.
# sigue siendo un ticker de la SEC.
_SEC_TICKER_EXCHANGE_MARKERS = (*_US_EXCHANGE_MARKERS, "OTC", "AMEX", "NYSE MKT")


def is_foreign_listing(exchange: str | None) -> bool:
    """La ficha cotiza en una bolsa CONOCIDA que no es de EE. UU.

    Sin bolsa declarada no se presume nada (False): el comportamiento previo
    sigue intacto para fichas sin ese dato.
    """
    listing = (exchange or "").strip().upper()
    if not listing:
        return False
    return not any(marker in listing for marker in _SEC_TICKER_EXCHANGE_MARKERS)


def sec_identity_mismatch(
    *,
    company_name: str | None,
    exchange: str | None,
    sec_entity_name: str | None,
) -> str | None:
    """Motivo por el que una entidad de la SEC NO es el emisor de la ficha, o None.

    El ticker de EDGAR es un símbolo de EE. UU.: fuera de su bolsa un mismo
    ticker es OTRO emisor (PRIM en BME vs Perimeter Solutions en NYSE, ambos
    «PRM»). Con listado no estadounidense la razón social de la SEC tiene que
    casar con la de la ficha (``names_compatible``); un foreign private issuer
    que sí presenta ante la SEC (20-F) casa por nombre. En una bolsa de EE. UU.,
    o sin bolsa o sin razón social que contrastar, no hay nada que objetar y
    el comportamiento no cambia.
    """
    sec_name = (sec_entity_name or "").strip()
    if not sec_name or not is_foreign_listing(exchange):
        return None
    if names_compatible(sec_name, company_name or ""):
        return None
    return (
        f"la entidad de la SEC «{sec_name}» no es el emisor de la ficha "
        f"«{company_name or ''}» (cotiza en {exchange}): mismo ticker, otro emisor"
    )
