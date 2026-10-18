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
  CavaAI; si algún día se importan, hay que enrutarlas a "otros elementos"
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
}
TREATY_RATE_SOURCES = {
    "US": "BOE-A-1990-30940 art. 10.2.b (convenio España-EE.UU.)",
}

UNKNOWN_COUNTRY = "??"

# Tipos de pago especiales (en la acción cruda del bróker) que NO son un
# dividendo ordinario: su tratamiento fiscal difiere (payment in lieu,
# retorno de capital, ingresos por préstamo de valores). Nunca entran en la
# deducción 0588 automática: revisión manual.
SPECIAL_PAYMENT_TOKENS = (
    "lieu",               # payment in lieu of dividends
    "return of capital",
    "capital return",
    "lending",            # stock lending income
    "loan",
    "substitute payment",
)


def savings_bands(year: int) -> tuple:
    """Escala del ahorro vigente en ``year`` (tuplas desde/hasta/tipo)."""
    if year >= 2025:
        return _BRACKETS_2025
    if year >= 2023:
        return _BRACKETS_2023
    return _BRACKETS_2021


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
                f"({CASILLAS_BASIS}); el ejercicio {fiscal_year} usa otra "
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
            # Venta sin compras que la cubran: el remanente se valora a coste
            # cero, así que las casillas de ganancia no son fiables.
            if gain_base is None or proceeds_base is None or cost_base is None or sale.get("over_sell"):
                incomplete = True
            rows.append({
                "ticker": bucket["ticker"],
                "date": sale["date"],
                "transmission_base": _money(Decimal(str(proceeds_base))) if proceeds_base is not None else None,
                "acquisition_base": _money(Decimal(str(cost_base))) if cost_base is not None else None,
                "gain_base": _money(Decimal(str(gain_base))) if gain_base is not None else None,
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


def build_double_taxation(
    dividends: list[dict],
    country_by_ticker: dict[str, str | None],
    fiscal_year: int,
    tme: Decimal | None = None,
) -> dict:
    """Deducción por doble imposición internacional (art. 80 LIRPF, casilla 0588).

    La deducción es el MENOR de:
      (a) la retención extranjera soportada, con tope en el tipo del convenio
          sobre el íntegro (solo países con tipo verificado en el BOE), y
      (b) la cuota que correspondería en España, calculada con el TIPO MEDIO
          EFECTIVO DE GRAVAMEN (TME) de la declaración COMPLETA: cuota
          íntegra estatal y autonómica ×100 / base liquidable del ahorro,
          expresado con dos decimales (Manual Renta 2025, cap. 18).

    El TME exige la declaración entera (bases general y del ahorro, cuotas),
    que CavaAI no tiene: sin ``tme`` la deducción queda
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
        entry = by_country.setdefault(country, {"gross": Decimal("0"), "withheld": Decimal("0")})
        entry["gross"] += Decimal(str(gross or 0))
        entry["withheld"] += Decimal(str(withheld or 0))

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
        creditable = min(data["withheld"], data["gross"] * treaty_rate)
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

    ``prior_year_nets``: lista de ``{"year", "net_gyp_base", "incomplete"}``
    con el resultado neto COMPUTABLE de cada ejercicio previo según el libro.
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
            if net < 0:
                pending.append({
                    "year": year,
                    "pending": abs(net),
                    "source": "libro-estimativo",
                    "casilla_integracion": None,
                    "casilla_resto": None,
                })

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
