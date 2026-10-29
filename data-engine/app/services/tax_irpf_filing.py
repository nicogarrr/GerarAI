"""Capa de declaración IRPF (Modelo 100) sobre el informe fiscal existente.

Convierte los agregados del :class:`TaxReportService` (dividendos, ventas
FIFO, retenciones) en las casillas del Modelo 100 y en la deducción por
doble imposición internacional (art. 80 LIRPF).

Referencia de enfoque: DeclaRenta (GPL-3.0, github.com/GeiserX/DeclaRenta).
El diseño de casillas se ha verificado contra el anexo del Modelo 100 en la
propia Orden HAC/277/2026 (BOE-A-2026-7041): 0326/0327 emisora-denominación,
0328 importe global de transmisiones, 0331 adquisición global, 0336/0338
resultados por fila, 0339/0340 sumas; 0029 dividendos; 0588 doble imposición
internacional; 0597 retenciones por rendimientos del capital mobiliario;
1626/1633/1637/1640 y 0385/0386 otros elementos patrimoniales.
Aquí se reimplementa en Python el MAPEO NORMATIVO (números de casilla de la
Orden HAC/277/2026 para la Renta 2025, escala del ahorro, límites del
art. 80 LIRPF); no se copia código fuente. Los números de casilla son
hechos normativos publicados en el BOE.

Alcance deliberado (honesto, sin verde falso):
- El mapeo de casillas verificado es el de la Renta 2025 (Orden HAC/277/2026,
  BOE-A-2026-7041). Para otros ejercicios el bloque ``casillas`` se devuelve
  con ``available=False`` y el motivo, no con números de otro año.
- Todas las ventas del ledger son acciones/ETF cotizados (el importador IBKR
  solo crea operaciones de acciones), así que todo va al bloque de "acciones
  negociadas" (pág. 14 III, art. 37.1.a LIRPF). Opciones/cripto no entran en
  GerarAI; si algún día se importan, hay que enrutarlas a "otros elementos"
  (pág. 17 I, casillas 1626/1633/1637/1640) antes de usar esto.
- El país de retención se aproxima con ``Company.domicile_country`` (el
  ledger no guarda país de retención por pago). Si falta, el país es
  "desconocido": NO se calcula deducción para ese bloque y se marca para
  revisión manual. Con ISIN (pendiente) se podrá afinar por prefijo.
- Dividendos especiales (REIT, retorno de capital, payment in lieu) y
  préstamo de acciones NO se clasifican: se listan como ``manual_review``
  cuando el tipo de pago no es dividendo ordinario + retención.
- Sigue siendo un informe ORIENTATIVO (ver ``summary.fiscal_disclaimer``):
  una ayuda de cálculo para contrastar con los extractos oficiales, no una
  declaración lista para presentar.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# --- Escala del ahorro (base del ahorro) -----------------------------------
# Historial del tipo del ahorro:
#  - 2021-2022: 19 / 21 / 23 / 26 (tramo superior > 200.000)
#  - 2023-2024: 19 / 21 / 23 / 27 / 28 (RDL 13/2022: 27% entre 200k-300k, 28% >300k)
#  - 2025+:     19 / 21 / 23 / 27 / 30 (Ley 7/2024 sube el tramo >300.000 al 30%)
# Cada banda es (desde, hasta, tipo); el tramo superior usa hasta=None.

_BRACKETS_2007 = ((0, None, Decimal("0.18")),)
_BRACKETS_2010 = ((0, 6_000, Decimal("0.19")), (6_000, None, Decimal("0.21")))
_BRACKETS_2012 = ((0, 6_000, Decimal("0.21")), (6_000, 24_000, Decimal("0.25")),
                  (24_000, None, Decimal("0.27")))
_BRACKETS_2015 = ((0, 6_000, Decimal("0.195")), (6_000, 50_000, Decimal("0.215")),
                  (50_000, None, Decimal("0.235")))
_BRACKETS_2016 = ((0, 6_000, Decimal("0.19")), (6_000, 50_000, Decimal("0.21")),
                  (50_000, None, Decimal("0.23")))
_BRACKETS_2021 = ((0, 6_000, Decimal("0.19")), (6_000, 50_000, Decimal("0.21")),
                  (50_000, 200_000, Decimal("0.23")), (200_000, None, Decimal("0.26")))
_BRACKETS_2023 = ((0, 6_000, Decimal("0.19")), (6_000, 50_000, Decimal("0.21")),
                  (50_000, 200_000, Decimal("0.23")), (200_000, 300_000, Decimal("0.27")),
                  (300_000, None, Decimal("0.28")))
_BRACKETS_2025 = ((0, 6_000, Decimal("0.19")), (6_000, 50_000, Decimal("0.21")),
                  (50_000, 200_000, Decimal("0.23")), (200_000, 300_000, Decimal("0.27")),
                  (300_000, None, Decimal("0.30")))

# Mapeo de casillas verificado: Renta 2025 (Orden HAC/277/2026).
CASILLAS_BASIS = "orden-hac-277-2026-renta-2025"
# Version legible para la UI: el slug interno no se muestra a personas.
CASILLAS_BASIS_DISPLAY = "Orden HAC/277/2026 (Renta 2025)"
CASILLAS_YEARS = {2025}

# Casilla 0029: ingresos íntegros de rendimientos del capital mobiliario
# (dividendos). Casilla 0597: retenciones a cuenta españolas. Casilla 0588:
# deducción por doble imposición internacional (art. 80 LIRPF).
CASILLA_DIVIDENDOS = "0029"
CASILLA_RETENCIONES_ES = "0597"
CASILLA_DOBLE_IMPOSICION = "0588"

# Tope de convenio: España solo acredita la retención extranjera hasta el
# tipo del convenio de doble imposición; el exceso se reclama en origen.
# SOLO tipos verificados contra el texto del convenio (BOE). Sin tipo por
# defecto: un país sin convenio/tasa documentados va a revisión manual —
# aplicar un 15% genérico podría acreditar impuesto no permitido o recortar
# de más.
TREATY_DIVIDEND_RATES = {
    # España-EE.UU. (BOE-A-1990-30940, art. 10.2.b): 15% para persona física
    # minorista (el 5% del art. 10.2.a exige sociedad con >=10% del capital).
    "US": Decimal("0.15"),
    # España-China 2018 (BOE-A-2021-4911, art. 10.2.b): 10% "en todos los
    # demás casos" (el 5% del art. 10.2.a exige sociedad con >=25%).
    # Ojo: muchos ADR chinos (BABA, BIDU…) son sociedades de las Islas
    # Caimán; si el domicilio del emisor es KY no hay convenio y va a
    # revisión manual.
    "CN": Decimal("0.10"),
    # España-Reino Unido 2013 (BOE-A-2014-5171, art. 10.2.a.i): 10%. El 15%
    # del art. 10.2.a.ii (vehículos inmobiliarios tipo REIT) no se distingue
    # aquí. El Reino Unido no retiene en origen sobre dividendos ordinarios,
    # así que lo normal es retención 0 y deducción 0.
    "GB": Decimal("0.10"),
    # España-Canadá (BOE-A-1981-2731, texto consolidado con el Protocolo de
    # 2014, BOE-A-2015-10793, art. X.2.b): 15% "en todos los demás casos"
    # (el 5% del art. X.2.a exige sociedad con >=10% del capital).
    "CA": Decimal("0.15"),
    # España-Hong Kong 2011 (BOE-A-2012-5039, art. 10.2.b): 10% "en todos los
    # demás casos" (el 0% del art. 10.2.a exige sociedad con >=25% del capital,
    # no una persona física minorista). Hong Kong no retiene en origen sobre
    # dividendos ordinarios, así que lo normal es retención 0 y deducción 0;
    # el tope solo acota una retención aplicada por error del bróker. Ojo: los
    # ADR/acciones chinas tipo BABA son sociedades de Caimán (KY), no HK.
    "HK": Decimal("0.10"),
}
TREATY_RATE_SOURCES = {
    "US": "BOE-A-1990-30940 art. 10.2.b (convenio España-EE.UU.)",
    "CN": "BOE-A-2021-4911 art. 10.2.b (convenio España-China 2018)",
    "GB": "BOE-A-2014-5171 art. 10.2.a.i (convenio España-Reino Unido)",
    "CA": "BOE-A-1981-2731 art. X.2.b (convenio España-Canadá)",
    "HK": "BOE-A-2012-5039 art. 10.2.b (convenio España-Hong Kong 2011)",
}

UNKNOWN_COUNTRY = "??"

# Tipos de pago especiales (en la acción cruda del bróker) que NO son un
# dividendo ordinario: su tratamiento fiscal difiere (payment in lieu,
# retorno de capital, ingresos por préstamo de valores, scrip/dividendo
# flexible). Nunca entran en la deducción 0588 automática: revisión manual.
# Scrip: el criterio (acciones liberadas vs venta de derechos vs efectivo) NO
# está implementado; la fila se marca "no calculado, revisar" y queda fuera de
# la casilla 0029 en vez de contarse como dividendo en efectivo.
SPECIAL_PAYMENT_TOKENS = (
    "lieu",               # payment in lieu of dividends
    "return of capital",
    "capital return",
    "lending",            # stock lending income
    "loan",
    "substitute payment",
    "scrip",              # scrip dividend / scrip: efectivo vs acciones sin distinguir
    "dividendo flexible",
    "dividendo opcional",
)


def savings_bands(year: int) -> tuple:
    """Escala del ahorro vigente en ``year`` (tuplas desde/hasta/tipo).

    Tipo total (estatal + autonomico). Fuentes:
    - 2021-2022: Ley 11/2020 (BOE-A-2020-17339), tramo del 26 % desde 200.000.
    - 2016-2020: Ley 26/2014 (BOE-A-2014-12327), arts. 66 y 76 LIRPF: 19/21/23.
    - 2015: RDL 9/2015 (BOE-A-2015-7765), escala de 2015: 19,5/21,5/23,5.
    - 2012-2014: RDL 20/2011 (BOE-A-2011-20638), gravamen complementario: 21/25/27.
    - 2010-2011: Ley 26/2009 (PGE 2010): 19/21.
    - 2007-2009: Ley 35/2006: tipo unico del 18 %.

    Fail-closed: sin escala verificada para el ejercicio se lanza
    ValueError, nunca se aplica la de otro periodo en silencio (antes un
    ejercicio < 2007 heredaba el 18 % de 2007-2009 como si fuera vigente).
    """
    if year < 2007:
        raise ValueError(
            f"Escala del ahorro no verificada para el ejercicio {year}: "
            "solo estan documentadas las escalas de 2007 en adelante."
        )
    if year >= 2025:
        return _BRACKETS_2025
    if year >= 2023:
        return _BRACKETS_2023
    if year >= 2021:
        return _BRACKETS_2021
    if year >= 2016:
        return _BRACKETS_2016
    if year == 2015:
        return _BRACKETS_2015
    if year >= 2012:
        return _BRACKETS_2012
    if year >= 2010:
        return _BRACKETS_2010
    return _BRACKETS_2007


def calculate_savings_tax(income: Decimal, year: int) -> Decimal:
    """Cuota del ahorro progresiva sobre ``income`` (EUR) para ``year``."""
    if income <= 0:
        return Decimal("0")
    tax = Decimal("0")
    for lower, upper, rate in savings_bands(year):
        width = None if upper is None else Decimal(upper - lower)
        taxable = income - Decimal(lower)
        if taxable <= 0:
            break
        if width is not None:
            taxable = min(taxable, width)
        tax += taxable * rate
        if width is None or taxable < width:
            break
    return tax


def _money(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_casillas(dividends: list[dict], realized: list[dict], fiscal_year: int) -> dict:
    """Mapeo a casillas del Modelo 100 (Renta 2025, Orden HAC/277/2026).

    Solo ganancias/pérdidas por transmisión de acciones negociadas y
    dividendos; el resto de bloques del modelo no se tocan.

    Las ventas entran con su resultado COMPUTABLE del año (gain_base ya neto
    de la pérdida bloqueada por la regla de los 2 meses: lo bloqueado no es
    pérdida computable del ejercicio, se difiere al lote recomprado).
    Totales None cuando falta FX en algún componente (un total parcial
    parecería definitivo y sería incorrecto).
    """
    if fiscal_year not in CASILLAS_YEARS:
        return {
            "available": False,
            "basis": None,
            "unavailable_reason": (
                f"Mapeo de casillas verificado solo para la Renta 2025 "
                f"({CASILLAS_BASIS_DISPLAY}); el ejercicio {fiscal_year} usa otra "
                "orden ministerial y no se muestran números sin verificar."
            ),
        }

    rows = []
    transmission = Decimal("0")
    acquisition = Decimal("0")
    gains = Decimal("0")
    losses = Decimal("0")
    incomplete = False
    for bucket in realized:
        for sale in bucket["sales"]:
            gain_base = sale["gain_base"]
            # Transmision/adquisicion convertidas con el tipo de la fecha de
            # venta, calculado en el motor FIFO (nunca derivado del resultado:
            # la regla de los 2 meses rompe la proporcionalidad).
            proceeds_base = sale.get("proceeds_base")
            cost_base = sale.get("cost_base")
            over_sell = bool(sale.get("over_sell"))
            # Venta sin compras que la cubran: el remanente se valora a coste
            # cero, así que la base de adquisición no se conoce y la fila da
            # N/D en adquisición y resultado (nunca el importe con el coste
            # inventado). La transmisión sí es un dato observado y se conserva.
            if over_sell:
                cost_base = None
                gain_base = None
            if gain_base is None or proceeds_base is None or cost_base is None:
                incomplete = True
            rows.append({
                "ticker": bucket["ticker"],
                "date": sale["date"],
                "transmission_base": _money(Decimal(str(proceeds_base))) if proceeds_base is not None else None,
                "acquisition_base": _money(Decimal(str(cost_base))) if cost_base is not None else None,
                "gain_base": _money(Decimal(str(gain_base))) if gain_base is not None else None,
                "over_sell": over_sell,
            })
            if proceeds_base is not None:
                transmission += Decimal(str(proceeds_base))
            if cost_base is not None:
                acquisition += Decimal(str(cost_base))
            if gain_base is not None:
                if gain_base >= 0:
                    gains += Decimal(str(gain_base))
                else:
                    losses += abs(Decimal(str(gain_base)))

    dividends_total = sum(
        # nosemgrep: gerarai-money-none-to-zero -- el total se publica como None si algun bloque es incompleto (dividend_incomplete, abajo)
        (Decimal(str(b["dividends_base"] or 0)) for b in dividends), Decimal("0")
    )
    dividend_incomplete = any(
        b["missing_fx"] or b.get("ambiguous_cash") for b in dividends
    )
    special_tickers = sorted(
        b["ticker"] for b in dividends if b.get("special_payments")
    )

    return {
        "available": True,
        "basis": CASILLAS_BASIS,
        "acciones_negociadas": {
            "pagina": "14 III (art. 37.1.a LIRPF)",
            "rows": rows,
            "0328_transmision_global": None if incomplete else _money(transmission),
            "0331_adquisicion_global": None if incomplete else _money(acquisition),
            "0339_suma_ganancias": None if incomplete else _money(gains),
            "0340_suma_perdidas": None if incomplete else _money(losses),
            "incomplete": incomplete,
        },
        "dividendos": {
            # Los pagos especiales (payment in lieu, return of capital,
            # lending) NO entran en la 0029: no son dividendos ordinarios y
            # su tratamiento difiere; se listan para revisión manual.
            "0029_ingresos_integros": None if dividend_incomplete else _money(dividends_total),
            "incomplete": dividend_incomplete,
            "special_payment_tickers": special_tickers,
        },
        "notas": [
            "Todas las transmisiones del ledger se tratan como acciones "
            "negociadas en mercados regulados; opciones, cripto y fondos no "
            "cotizados irían a 'otros elementos patrimoniales' "
            "(1626/1633/1637) y no están soportados.",
            "La casilla 0327 es la denominación de los valores (texto), no "
            "un importe: en Renta Web se cumplimenta una fila por valor con "
            "los datos de 'rows'.",
        ],
    }


def _treaty_creditable(bucket: dict, gross: Decimal, withheld: Decimal, rate: Decimal) -> Decimal:
    """Retención acreditable con el tope del convenio aplicado DIVIDENDO A DIVIDENDO.

    El convenio limita la retención exigible al tipo del convenio sobre el
    importe bruto de CADA dividendo (España-EE.UU., BOE-A-1990-30940, art.
    10.2.b: "15 por 100 del importe bruto de los dividendos"), y el art. 80.1.a
    LIRPF solo deja deducir el impuesto "efectivamente satisfecho" que el
    convenio permite: el exceso se reclama en origen. Por eso el tope es
    Σ_i min(retención_i, tipo × bruto_i), nunca min(Σ retención, tipo × Σ
    bruto): sumado por país, la retención baja de un valor (p. ej. 10 %)
    "hace hueco" al exceso de otro (30 % sin W-8BEN) y la deducción sale inflada.

    Dividendo = pago del bloque (ticker) en una fecha, a partir de las filas
    ``payments``. Una retención sin dividendo ese día (ajuste o reversión
    posterior) se imputa al dividendo anterior más cercano del mismo valor (o
    al primero si no hay anterior). Si las filas no concilian con los totales
    del bloque (falta un importe, fila ambigua o sin filas), el tope se aplica
    por valor (bloque), que es la granularidad más fina disponible.
    """
    block_cap = min(max(withheld, Decimal("0")), gross * rate)
    gross_by_date: dict[str, Decimal] = {}
    withheld_by_date: dict[str, Decimal] = {}
    for payment in bucket.get("payments") or []:
        kind = payment.get("type")
        if kind not in {"dividend", "withholding"}:
            continue
        amount = payment.get("amount_base")
        if amount is None or payment.get("ambiguous") or not payment.get("date"):
            return block_cap
        target = gross_by_date if kind == "dividend" else withheld_by_date
        day = str(payment["date"])
        target[day] = target.get(day, Decimal("0")) + Decimal(str(amount))
    if not gross_by_date:
        return block_cap
    tolerance = Decimal("0.01") * (len(gross_by_date) + len(withheld_by_date))
    if (
        abs(sum(gross_by_date.values(), Decimal("0")) - gross) > tolerance
        or abs(sum(withheld_by_date.values(), Decimal("0")) - withheld) > tolerance
    ):
        return block_cap
    dates = sorted(gross_by_date)
    assigned = dict.fromkeys(dates, Decimal("0"))
    for day, amount in withheld_by_date.items():
        if day in assigned:
            assigned[day] += amount
            continue
        prior = [d for d in dates if d < day]
        assigned[prior[-1] if prior else dates[0]] += amount
    result = sum(
        (min(max(assigned[d], Decimal("0")), gross_by_date[d] * rate) for d in dates),
        Decimal("0"),
    )
    if any(assigned[d] < 0 for d in dates):
        # Reversion/ajuste que no cabe en el dividendo al que la fecha lo
        # imputa: recortar con max(., 0) EVAPORA el negativo sobrante y la
        # deduccion sale inflada (se acredita impuesto ya devuelto). La fecha
        # no dice a que dividendo pertenece la reversion: suelo conservador,
        # nunca por encima del neto retenido del bloque ni del tope por valor.
        return min(result, block_cap)
    return result


def build_double_taxation(
    dividends: list[dict],
    country_by_ticker: dict[str, str | None],
    fiscal_year: int,
    tme: Decimal | None = None,
) -> dict:
    """Deducción por doble imposición internacional (art. 80 LIRPF, casilla 0588).

    La deducción es el MENOR de:
      (a) la retención extranjera soportada, con tope en el tipo del convenio
          sobre el íntegro de CADA dividendo (Σ min(retención_i, tipo ×
          bruto_i); solo países con tipo verificado en el BOE), y
      (b) la cuota que correspondería en España, calculada con el TIPO MEDIO
          EFECTIVO DE GRAVAMEN (TME) de la declaración COMPLETA: cuota
          íntegra estatal y autonómica ×100 / base liquidable del ahorro,
          expresado con dos decimales (Manual Renta 2025, cap. 18).

    El TME exige la declaración entera (bases general y del ahorro, cuotas),
    que GerarAI no tiene: sin ``tme`` la deducción queda
    ``status="pendiente_tme"`` con ``deduction_base=None`` y se muestra solo
    el TOPE POR CONVENIO (límite superior), nunca una deducción final
    aparentemente verificada. Con ``tme`` (introducido por el usuario desde
    su borrador) se calcula la deducción como min(tope convenio, bruto×TME).

    La retención de emisores españoles NO es deducible aquí: es un pago a
    cuenta doméstico (casilla 0597) y se devuelve aparte.
    País desconocido o sin tipo de convenio verificado: ``manual_review``,
    sin deducción calculada.
    """
    by_country: dict[str, dict] = {}
    manual_review = []
    # La casilla 0597 suma retenciones ESPAÑOLAS. Si un bloque que podria ser
    # espanol (pais ES o desconocido) no se puede convertir o revisar, o no trae
    # la retencion, el total no es verificable: se publica null, nunca un 0.
    es_incomplete = False
    for bucket in dividends:
        gross = bucket["dividends_base"]
        withheld = bucket["withholding_base"]
        bucket_country = (country_by_ticker.get(bucket["ticker"]) or "").strip().upper()
        may_be_es = bucket_country in {"", UNKNOWN_COUNTRY, "ES"}
        if may_be_es and (
            bucket["missing_fx"]
            or bucket.get("ambiguous_cash")
            or (bucket_country == "ES" and withheld is None and gross)
            or (bucket_country == "ES" and gross is None and withheld)
        ):
            es_incomplete = True
        if bucket["missing_fx"]:
            manual_review.append({
                "ticker": bucket["ticker"],
                "reason": "Sin tipo de cambio para convertir el dividendo o la retención; no entra en la deducción.",
            })
            continue
        if bucket.get("ambiguous_cash"):
            manual_review.append({
                "ticker": bucket["ticker"],
                "reason": "Fila de caja ambigua (quantity fuera de {0, 1}) sin resolver; el bloque no entra en la deducción hasta revisarla.",
            })
            continue
        if not gross and not withheld:
            continue
        special = sorted({
            token
            for payment in (bucket.get("payments") or [])
            for token in SPECIAL_PAYMENT_TOKENS
            if token in str(payment.get("raw_action") or "").lower()
        })
        if special:
            if may_be_es:
                es_incomplete = True
            manual_review.append({
                "ticker": bucket["ticker"],
                "reason": (
                    "Tipo de pago especial (" + ", ".join(special) + "): no es "
                    "un dividendo ordinario y su tratamiento fiscal difiere; "
                    "no entra en la deducción automática."
                ),
            })
            continue
        bucket_payments = bucket.get("payments") or []
        has_reversal = any(
            payment.get("type") == "withholding"
            and payment.get("amount_base") is not None
            and Decimal(str(payment["amount_base"])) < 0
            for payment in bucket_payments
        )
        dividend_dates = {
            str(payment["date"])
            for payment in bucket_payments
            if payment.get("type") == "dividend" and payment.get("date")
        }
        if has_reversal and len(dividend_dates) > 1:
            # Reversion (p. ej. devolucion del exceso de retencion) con varios
            # dividendos en el ejercicio: la fecha no identifica el dividendo
            # al que se aplica y una atribucion por proximidad infla o recorta
            # la deduccion. Revision manual, nunca una cifra con pinta de exacta.
            if may_be_es:
                es_incomplete = True
            manual_review.append({
                "ticker": bucket["ticker"],
                "reason": (
                    "Reversion o ajuste de retencion con varios dividendos en el "
                    "ejercicio: no se puede atribuir por fecha al dividendo que la "
                    "origino; imputa la reversion a su dividendo y recalcula la "
                    "deduccion a mano."
                ),
            })
            continue
        country = (country_by_ticker.get(bucket["ticker"]) or "").strip().upper()
        if country in {"", UNKNOWN_COUNTRY}:
            es_incomplete = True
            manual_review.append({
                "ticker": bucket["ticker"],
                "reason": "País de retención desconocido (sin domicilio del emisor); no se calcula deducción para este bloque.",
            })
            continue
        if country != "ES" and country not in TREATY_DIVIDEND_RATES:
            manual_review.append({
                "ticker": bucket["ticker"],
                "reason": (
                    f"Sin tipo de convenio verificado para {country}: la "
                    "retención se revisa a mano contra el convenio aplicable "
                    "(un tipo genérico podría acreditar de más o de menos)."
                ),
            })
            continue
        entry = by_country.setdefault(
            country, {"gross": Decimal("0"), "withheld": Decimal("0"), "creditable": Decimal("0")}
        )
        # nosemgrep: gerarai-money-none-to-zero -- None solo con missing_fx/ambiguous_cash, que ya salieron del bucle con revision manual (lineas 384-401)
        gross_d = Decimal(str(gross or 0))
        # nosemgrep: gerarai-money-none-to-zero -- None solo con missing_fx/ambiguous_cash, que ya salieron del bucle con revision manual (lineas 384-401)
        withheld_d = Decimal(str(withheld or 0))
        entry["gross"] += gross_d
        entry["withheld"] += withheld_d
        if country != "ES":
            # Tope del convenio por DIVIDENDO (no por país): art. 10.2.b del
            # convenio y art. 80.1.a LIRPF; ver _treaty_creditable.
            entry["creditable"] += _treaty_creditable(
                bucket, gross_d, withheld_d, TREATY_DIVIDEND_RATES[country]
            )

    countries = []
    total_deduction = Decimal("0")
    spanish_withholding = Decimal("0")
    any_excess = False
    for country in sorted(by_country):
        data = by_country[country]
        if country == "ES":
            # Retención a cuenta doméstica → casilla 0597, nunca crédito 0588.
            spanish_withholding += data["withheld"]
            continue
        if data["withheld"] <= 0:
            continue
        treaty_rate = TREATY_DIVIDEND_RATES[country]
        creditable = data["creditable"]
        if data["withheld"] > creditable:
            any_excess = True  # hay exceso reclamable en origen: se señala
        if tme is not None:
            deduction = min(creditable, data["gross"] * tme)
            status = "calculada_con_tme_manual"
        else:
            deduction = None
            status = "pendiente_tme"
        countries.append({
            "country": country,
            "country_basis": "domicilio_emisor_aproximado",
            "gross_base": _money(data["gross"]),
            "withheld_base": _money(data["withheld"]),
            "treaty_rate": float(treaty_rate),
            "treaty_rate_source": TREATY_RATE_SOURCES[country],
            "treaty_cap_base": _money(creditable),
            "deduction_base": _money(deduction) if deduction is not None else None,
            "status": status,
            "excess_reclaimable_base": _money(data["withheld"] - creditable),
        })
        if deduction is not None:
            total_deduction += deduction

    # Total solo cuando es COMPLETO y computable: con revisión manual
    # pendiente (país desconocido, FX ausente, tipo de pago especial o sin
    # convenio verificado) un total parcial parecería definitivo.
    partial = bool(manual_review)
    publish_total = tme is not None and not partial
    return {
        "casilla": CASILLA_DOBLE_IMPOSICION,
        "basis": "art-80-lirpf",
        "status": "calculada_con_tme_manual" if tme is not None else "pendiente_tme",
        "partial": partial,
        "countries": countries,
        "total_deduction_base": _money(total_deduction) if publish_total else None,
        "spanish_withholding_base": {
            "casilla": CASILLA_RETENCIONES_ES,
            "amount": None if es_incomplete else _money(spanish_withholding),
            "status": "SIN_DATOS" if es_incomplete else "calculada",
            "reason": (
                "Hay dividendos de emisor español o de país desconocido sin tipo de cambio, "
                "retención o revisión: el total de retenciones españolas no es verificable."
                if es_incomplete
                else None
            ),
        },
        "excess_withholding_reclaimable": any_excess,
        "manual_review": manual_review,
        "notas": [
            "La deducción final (0588) es el menor entre el tope de convenio "
            "y la cuota española calculada con el TIPO MEDIO EFECTIVO de la "
            "base liquidable del ahorro (cuota líquida total entre base liquidable, "
            "Manual Renta 2025, cap. 18; distinto del TME de la base general): ese tipo "
            "necesita bases y cuotas de toda la declaración, que no están en "
            "este informe. Introduce el TME de la base liquidable del AHORRO de tu borrador para "
            "calcularla; hasta entonces el importe mostrado es solo el tope "
            "por convenio (límite superior).",
            "El exceso de retención sobre el tipo de convenio no lo devuelve "
            "Hacienda: se reclama al fisco del país de origen (devolución del "
            "exceso de retención en origen).",
            "País de retención aproximado por el domicilio del emisor; con "
            "ISIN por valor se podrá verificar por prefijo.",
        ],
    }


# --- Compensación de pérdidas de ejercicios anteriores (art. 49 LIRPF) ------
#
# Mecánica verificada en el anexo del Modelo 100 de la Orden HAC/277/2026
# (BOE-A-2026-7041, pág. 19, "Base imponible del ahorro"):
#   1. Saldo neto del año en GyP del ahorro (0424 si positivo): las pérdidas
#      de los 4 ejercicios anteriores se integran primero aquí, hasta su
#      importe (Renta 2025: 0439/0440/0441/0442 para 2021/2022/2023/2024).
#   2. El resto se aplica contra el saldo neto positivo de rendimientos del
#      capital mobiliario (0429) con el límite CONJUNTO del 25% de 0429
#      (Renta 2025: 0453/0454/0455/0448, junto con la 0446).
#   3. Lo que quede sigue arrastrando a los ejercicios siguientes (máx. 4).
CARRYFORWARD_WINDOW_YEARS = 4
CROSS_COMPENSATION_LIMIT = Decimal("0.25")

# Renta 2025: ejercicio de origen → (casilla integración en 0424, casilla
# resto al 25% de 0429). Solo verificado para la declaración de 2025.
_CASILLAS_PRIOR_2025 = {
    2021: ("0439", "0453"),
    2022: ("0440", "0454"),
    2023: ("0441", "0455"),
    2024: ("0442", "0448"),
}


def build_loss_compensation(
    prior_year_nets: list[dict],
    current_gyp_net_base: Decimal | None,
    current_rcm_net_base: Decimal | None,
    fiscal_year: int,
    declared_pending: dict[int, Decimal] | None = None,
) -> dict:
    """Compensación de saldos negativos de los 4 ejercicios anteriores.

    ``prior_year_nets``: lista de ``{"year", "net_gyp_base", "net_rcm_base",
    "incomplete"}`` con el resultado neto COMPUTABLE de cada ejercicio previo
    según el libro (``net_rcm_base``: dividendos + intereses, opcional).
    ``declared_pending``: saldos pendientes a 1 de enero por ejercicio de
    origen, copiados del ANEXO C.3 de la última declaración presentada
    (fuente manual autoritativa, almacenada por tenant).

    Mecánica (anexo del Modelo 100, Orden HAC/277/2026, pág. 19):
      1. El saldo neto negativo del PROPIO ejercicio (0425) cruza primero
         contra rendimientos del capital mobiliario (0429) como casilla 0446,
         dentro del límite CONJUNTO del 25% de 0429.
      2. Los saldos negativos de ejercicios anteriores se integran en el
         saldo positivo de GyP del año (0424; Renta 2025: 0439-0442).
      3. Su resto cruza contra 0429 SOLO con la capacidad del 25% que quede
         tras la 0446 (Renta 2025: 0453/0454/0455/0448): el límite es
         conjunto, como imprime el BOE.
      4. Lo que quede sigue arrastrando (máx. 4 ejercicios).

    Honestidad:
    - Los saldos pendientes REALES los fija la última declaración presentada
      (anexo C.3), no el libro: puede haber compensaciones ya aplicadas u
      orígenes fuera del libro. Con ``declared_pending`` la fuente es
      ``anexo-c3-manual`` y se publican casillas. Sin él, los saldos se
      derivan del libro y se etiquetan ``estimativo=True`` SIN casillas: una
      estimación no es trasladable a la declaración.
    - Ejercicio previo con FX incompleto → excluido y marcado.
    """
    window_start = fiscal_year - CARRYFORWARD_WINDOW_YEARS
    estimativo = declared_pending is None
    pending = []
    excluded = []
    if declared_pending is not None:
        # Fuente autoritativa: lo declarado (anexo C.3). Los ejercicios sin
        # entrada se tratan como saldo cero declarado.
        for year in sorted(declared_pending):
            if year < window_start or year >= fiscal_year:
                continue
            amount = Decimal(str(declared_pending[year]))
            if amount <= 0:
                continue
            casillas = _CASILLAS_PRIOR_2025.get(year) if fiscal_year == 2025 else None
            pending.append({
                "year": year,
                "pending": amount,
                "source": "anexo-c3-manual",
                "casilla_integracion": casillas[0] if casillas else None,
                "casilla_resto": casillas[1] if casillas else None,
            })
    else:
        # Simulación cronológica del arrastre (art. 49.1.b LIRPF): cada
        # ejercicio intermedio con saldo positivo de GyP ya compensó los
        # saldos negativos anteriores (el más antiguo primero), y el 25 % de
        # sus rendimientos del capital mobiliario absorbió parte del resto
        # (primero su propia pérdida, casilla 0446). Arrastrar la pérdida
        # ENTERA, como si nada la hubiera consumido, sobrestimaba lo
        # pendiente y compensaba de más en el ejercicio actual.
        for entry in sorted(prior_year_nets, key=lambda e: e["year"]):
            year = entry["year"]
            if year < window_start or year >= fiscal_year:
                continue  # fuera de la ventana de 4 ejercicios (expirado)
            if entry.get("incomplete") or entry.get("net_gyp_base") is None:
                excluded.append({
                    "year": year,
                    "reason": "Ejercicio con conversión de divisa incompleta: saldo no aprovechable en este informe.",
                })
                continue
            net = Decimal(str(entry["net_gyp_base"]))
            rcm_raw = entry.get("net_rcm_base")
            # Sin rendimientos conocidos no se resta nada por el 25 %: no
            # se inventa una compensación que quizá no hubo.
            year_cross = (
                max(Decimal("0"), Decimal(str(rcm_raw))) * CROSS_COMPENSATION_LIMIT
                if rcm_raw is not None else Decimal("0")
            )
            own_negative = abs(net) if net < 0 else Decimal("0")
            own_cross = min(own_negative, year_cross)
            year_cross -= own_cross
            year_gains = net if net > 0 else Decimal("0")
            for item in pending:
                if year - item["year"] > CARRYFORWARD_WINDOW_YEARS:
                    continue  # ya expirado en ese ejercicio
                take = min(item["pending"], year_gains)
                item["pending"] -= take
                year_gains -= take
                take = min(item["pending"], year_cross)
                item["pending"] -= take
                year_cross -= take
            if own_negative - own_cross > 0:
                pending.append({
                    "year": year,
                    "pending": own_negative - own_cross,
                    "source": "libro-estimativo",
                    "casilla_integracion": None,
                    "casilla_resto": None,
                })
        pending = [item for item in pending if item["pending"] > 0]

    incomplete = False
    saldo_gyp = None
    if current_gyp_net_base is not None:
        saldo_gyp = max(Decimal("0"), Decimal(str(current_gyp_net_base)))
    else:
        incomplete = True
    saldo_rcm = None
    if current_rcm_net_base is not None:
        saldo_rcm = max(Decimal("0"), Decimal(str(current_rcm_net_base)))
    else:
        incomplete = True

    # Límite cruzado conjunto: 25% del saldo neto positivo de rendimientos
    # del capital mobiliario (0429), compartido con la casilla 0446.
    cross_limit = (
        (saldo_rcm * CROSS_COMPENSATION_LIMIT)
        if saldo_rcm is not None else Decimal("0")
    )

    # 0) La pérdida del PROPIO ejercicio (0425 → 0446) consume primero el
    # límite conjunto: si no se reserva, se duplica la compensación.
    current_negative = (
        abs(Decimal(str(current_gyp_net_base)))
        if current_gyp_net_base is not None and current_gyp_net_base < 0
        else Decimal("0")
    )
    applied_0446 = min(current_negative, cross_limit)
    remaining_cross = cross_limit - applied_0446

    # 1) Integración de saldos previos en el saldo de GyP del año (0424).
    remaining_capacity = saldo_gyp if saldo_gyp is not None else Decimal("0")
    for item in pending:
        take = min(item["pending"], remaining_capacity)
        item["applied_gyp"] = take
        item["pending"] -= take
        remaining_capacity -= take
    applied_gyp_total = sum((i["applied_gyp"] for i in pending), Decimal("0"))

    # 2) Resto contra rendimientos con la capacidad del 25% NO usada por 0446.
    for item in pending:
        take = min(item["pending"], remaining_cross)
        item["applied_rcm"] = take
        item["pending"] -= take
        remaining_cross -= take
    applied_rcm_total = sum((i["applied_rcm"] for i in pending), Decimal("0"))

    return {
        "basis": "art-49-lirpf" + ("+orden-hac-277-2026" if fiscal_year == 2025 and not estimativo else ""),
        "window_years": CARRYFORWARD_WINDOW_YEARS,
        "estimativo": estimativo,
        "estimativo_reason": (
            "Saldos derivados SOLO del libro: no reflejan compensaciones ya "
            "aplicadas en declaraciones presentadas ni orígenes fuera del "
            "libro. NO trasladable a casillas. Introduce los saldos del "
            "anexo C.3 de tu última declaración en la metadata del tenant "
            "(clave 'tax_prior_losses_pending') para publicar casillas."
            if estimativo else None
        ),
        "prior_losses": [
            {
                "year": i["year"],
                "source": i["source"],
                "pending_start_base": _money(i["pending"] + i["applied_gyp"] + i["applied_rcm"]),
                "applied_to_gains_base": _money(i["applied_gyp"]),
                "applied_to_income_base": _money(i["applied_rcm"]),
                "remaining_base": _money(i["pending"]),
                "casilla_integracion": i["casilla_integracion"],
                "casilla_resto": i["casilla_resto"],
            }
            for i in pending
        ],
        "excluded_years": excluded,
        "current_gyp_net_base": None if saldo_gyp is None and current_gyp_net_base is None else _money(Decimal(str(current_gyp_net_base))),
        "current_rcm_net_base": None if saldo_rcm is None else _money(saldo_rcm),
        "current_year_cross": {
            "negative_gyp_base": _money(current_negative),
            "applied_to_income_base": _money(applied_0446),
            "casilla": "0446" if fiscal_year == 2025 else None,
        },
        "applied_to_gains_total_base": _money(applied_gyp_total),
        "cross_limit_base": _money(cross_limit),
        "cross_used_by_current_year_base": _money(applied_0446),
        "applied_to_income_total_base": _money(applied_rcm_total),
        "remaining_to_carry_base": _money(sum((i["pending"] for i in pending), Decimal("0"))),
        "incomplete": incomplete,
        "notas": [
            "Los saldos pendientes reales los fija la última declaración "
            "presentada (anexo C.3); Renta Web los arrastra automáticamente. "
            "Si difieren del libro, manda lo declarado.",
            "El límite del 25% sobre rendimientos del capital mobiliario es "
            "CONJUNTO entre la pérdida del propio ejercicio (0446) y el "
            "arrastre de ejercicios anteriores (0453-0455/0448 en Renta 2025): "
            "aquí se reserva primero la 0446.",
            "No se computan saldos negativos de rendimientos del capital "
            "mobiliario (dividendos IBKR no los generan en la práctica).",
        ],
    }


# --- Intereses (rendimientos del capital mobiliario, base del ahorro) -------
#
# Casilla 0027 (Renta 2025): "Intereses de cuentas, depósitos y de activos
# financieros en general" — incluye los intereses que el bróker abona por el
# efectivo de la cuenta (art. 25.2 LIRPF; Manual de ayuda Renta 2025, apdo.
# 7.2.3.1). Para intereses de cuentas y depósitos "en ningún caso podrán
# computarse gastos deducibles" (mismo apartado): los intereses PAGADOS por
# el margen (préstamo del bróker) no restan ni de estos intereses ni de los
# dividendos (art. 26.1.a LIRPF solo admite gastos de administración y
# depósito de valores). Para una persona física que no ejerce actividad
# económica, el interés del margen no es deducible en el IRPF.
CASILLA_INTERESES = "0027"


def build_interest(misc_rows: list[dict], fiscal_year: int) -> dict:
    """Intereses cobrados (casilla 0027) e intereses de margen pagados (no deducibles).

    ``misc_rows`` son las filas ``misc`` del informe (tipo ``interest``,
    ``fee`` o ``cash_misc``). Una fila ``interest`` con importe positivo es un
    interés cobrado; con importe negativo, un interés pagado (margen). Si una
    fila de interés no tiene importe en EUR (falta FX o fila ambigua), el
    total de la casilla queda en ``None`` y la fila va a revisión manual:
    nunca se publica un total parcial con pinta de exacto.
    """
    received = Decimal("0")
    paid = Decimal("0")
    received_rows = 0
    paid_rows = 0
    manual_review: list[dict] = []
    for row in misc_rows:
        if row.get("type") != "interest":
            continue
        native = row.get("amount_native")
        amount = row.get("amount_base")
        if amount is None or native is None or row.get("ambiguous"):
            manual_review.append({
                "date": row.get("date"),
                "currency": row.get("currency"),
                "amount_native": native,
                "reason": (
                    "Interés sin importe en EUR (falta el tipo de cambio de su "
                    "fecha o la fila es ambigua): revisar a mano."
                ),
            })
            continue
        value = Decimal(str(amount))
        if value >= 0:
            received += value
            received_rows += 1
        else:
            paid += -value
            paid_rows += 1
    incomplete = bool(manual_review)
    casilla_ok = fiscal_year in CASILLAS_YEARS
    return {
        "basis": "art-25.2-y-26.1.a-lirpf",
        "received": {
            "casilla": CASILLA_INTERESES if casilla_ok else None,
            "amount_base": None if incomplete else _money(received),
            "rows": received_rows,
            "status": "SIN_DATOS" if incomplete else "calculada",
        },
        "margin_interest_paid": {
            "amount_base": None if incomplete else _money(paid),
            "rows": paid_rows,
            "deductible": False,
            "reason": (
                "Los intereses pagados por el margen no son gasto deducible en "
                "el IRPF de una persona física: para intereses de cuentas no se "
                "admite ningún gasto y para dividendos solo los de "
                "administración y depósito (art. 26.1.a LIRPF; Manual de ayuda "
                "Renta 2025, apdo. 7.2.3.1). No los restes en la declaración."
            ),
        },
        "manual_review": manual_review,
        "incomplete": incomplete,
        "notas": [
            "IBKR (Irlanda) no practica retención española sobre los "
            "intereses: la casilla de retenciones de este bloque suele ir a "
            "cero. Contrasta el importe con el informe anual del bróker.",
            "Los intereses entran en el saldo de rendimientos del capital "
            "mobiliario del ahorro (0029 + 0027 …), que también fija el "
            "límite del 25 % para compensar pérdidas patrimoniales.",
        ],
    }
