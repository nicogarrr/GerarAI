"""Doble coincidencia SEC + proveedor para abrir ficha de un ticker desconocido."""

from app.services.company_identity_verification import (
    compare_identities,
    is_us_exchange,
    names_compatible,
)

BWMX_SEC = {"cik_str": 1823744, "ticker": "BWMX", "title": "Betterware de Mexico, S.A.P.I. de C.V."}
BWMX_PROVIDER = {
    "ticker": "BWMX",
    "name": "Betterware de Mexico SAPI de CV",
    "exchange": "NASDAQ NMS - GLOBAL MARKET",
    "country": "MX",
    "currency": "USD",
}


def test_double_match_verifies_bwmx():
    verdict = compare_identities("BWMX", BWMX_SEC, BWMX_PROVIDER)
    assert verdict.verified is True
    assert verdict.reasons == []
    assert verdict.sec["cik"] == "1823744"
    assert verdict.provider["exchange"] == "NASDAQ NMS - GLOBAL MARKET"


def test_negative_sec_has_no_record():
    verdict = compare_identities("BWMX", None, BWMX_PROVIDER)
    assert verdict.verified is False
    assert any(r.startswith("sec_sin_registro") for r in verdict.reasons)


def test_negative_provider_has_no_profile():
    verdict = compare_identities("BWMX", BWMX_SEC, {})
    assert verdict.verified is False
    assert any(r.startswith("proveedor_sin_perfil") for r in verdict.reasons)


def test_negative_name_mismatch():
    # El proveedor conoce el símbolo como otro emisor: jamás se adopta.
    provider = {**BWMX_PROVIDER, "name": "Almonty Industries Inc"}
    verdict = compare_identities("BWMX", BWMX_SEC, provider)
    assert verdict.verified is False
    assert any(r.startswith("nombre_no_coincide") for r in verdict.reasons)


def test_negative_non_us_market():
    # Cotiza en bolsa no estadounidense: la SEC no puede contrastarla.
    provider = {**BWMX_PROVIDER, "exchange": "BOLSA MEXICANA DE VALORES"}
    verdict = compare_identities("BWMX", BWMX_SEC, provider)
    assert verdict.verified is False
    assert any(r.startswith("mercado_no_sec") for r in verdict.reasons)


def test_negative_currency_missing_is_never_assumed():
    # Sin divisa declarada no se crea la ficha: la moneda nunca se inventa (N/D).
    provider = {**BWMX_PROVIDER, "currency": ""}
    verdict = compare_identities("BWMX", BWMX_SEC, provider)
    assert verdict.verified is False
    assert any(r.startswith("moneda_desconocida") for r in verdict.reasons)


def test_negative_ticker_mismatch():
    sec = {**BWMX_SEC, "ticker": "BWMX2"}
    verdict = compare_identities("BWMX", sec, BWMX_PROVIDER)
    assert verdict.verified is False
    assert any(r.startswith("ticker_no_coincide") for r in verdict.reasons)


def test_name_compatibility_rules():
    assert names_compatible("Betterware de Mexico, S.A.P.I. de C.V.", "Betterware de Mexico SAPI de CV")
    assert names_compatible("Apple Inc.", "APPLE INC")
    # La clase de acción no rompe la compatibilidad: "class" no es distintivo de emisor aquí,
    # el lado corto («alphabet») está contenido en el largo.
    assert names_compatible("Alphabet Inc.", "Alphabet Inc Class A")
    assert not names_compatible("Almirall SA", "Almonty Industries Inc")
    assert not names_compatible("", "Anything Inc")
    assert not names_compatible("AB SA", "AC SA")


def test_us_exchange_detection():
    assert is_us_exchange("NASDAQ NMS - GLOBAL MARKET")
    assert is_us_exchange("NEW YORK STOCK EXCHANGE, INC.")
    assert not is_us_exchange("BOLSA MEXICANA DE VALORES")
    assert not is_us_exchange("LONDON STOCK EXCHANGE")
    assert not is_us_exchange(None)
