"""Proyección mes a mes de dividendos de la cartera con escenario fiscal.

INFERIDO: réplica mecánica de los dividendos YA declarados e ingeridos en los
últimos 12 meses (ex_date <= hoy), con la misma cantidad por acción y las
fechas desplazadas +N años según el horizonte. No modela crecimientos ni
recortes: es la foto de "si repiten lo ya declarado", etiquetada como
inferencia, nunca como compromiso de la empresa. Los dividendos declarados
con ex_date futuro se reportan aparte (``declared_future``), no alimentan la
réplica.

Escenario fiscal (HIPÓTESIS, condicionado, nunca "neto final"):

- Residencia fiscal española asumida; W-8BEN vigente asumido para US.
- Retención de origen: US 15 % (convenio España-EE.UU.; AEAT, Anexo III de
  límites de imposición en convenios,
  https://www3.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/manual-tributacion-no-residentes/anexos/limites-imposicion-convenios.html,
  consultado 2026-10-11). ES 19 %: pago a cuenta, NO impuesto extranjero.
  Cualquier otro domicilio (incluido GB: HMRC puede retener según categoría,
  p.ej. PID/REIT, https://www.gov.uk/hmrc-internal-manuals/investment-funds/ifm28125)
  sale como ``None`` = sin datos, nunca 0 %.
- IRPF: escala del ahorro de :mod:`app.services.tax_irpf_filing`
  (Orden HAC/277/2026, Renta 2025). Aplicada a años futuros es ESCENARIO
  (tipos vigentes a fecha de cálculo, sujetos a cambio legislativo).
  Progresiva sobre el acumulado anual de la cartera; condicionada a que
  estos dividendos sean la única renta del ahorro del año.
- Deducción por doble imposición internacional (solo impuesto extranjero):
  por posición y año, el MENOR entre el impuesto soportado en origen y el
  tipo medio efectivo de gravamen aplicado a la base extranjera (AEAT,
  deducción por doble imposición internacional,
  https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-ayuda-presentacion/irpf-2025/8-cumplimentacion-irpf/8_7-cuota-liquida-cuota-resultante-autoliquidacion/8_7_3-cuota-resultante-autoliquidacion/8_7_3_1-deduccion-doble-imposicion-internacional.html,
  consultado 2026-10-11). El tipo medio se calcula sobre el total anual del
  escenario.
- Fiscal solo si la divisa base es EUR; con otra base, IRPF/neto = None.

Honestidad de cobertura: solo posiciones largas abiertas (quantity > 0);
posiciones sin dividendos declarados van a ``coverage.sin_datos`` (nunca
0,00); sin tipo de cambio a ``coverage.fx_missing``; domicilio sin tipo
verificado a ``coverage.unknown_source_withholding``. Los totales mensuales
solo agregan posiciones fiscalmente cubiertas y declaran
``covered_tickers``/``excluded_tickers`` por mes: son un subconjunto
explícito, no el total de la cartera.
"""

from __future__ import annotations

import calendar
import math
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Company, DividendRecord, Position
from app.services.dividend_records import (
    records_in_position_currency,
    resolve_cross_provider_events,
    resolve_yahoo_events,
)
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.tax_irpf_filing import calculate_savings_tax

# Retención en origen verificada (consultado 2026-10-11). Solo entradas
# verificadas: US 15 % (convenio, W-8BEN; AEAT Anexo III) y ES 19 % (pago a
# cuenta, no impuesto extranjero). GB queda fuera a propósito: HMRC puede
# retener según la categoría del dividendo (IFM28125), así que sin dato por
# empresa es "sin datos", nunca 0 %.
_SOURCE_WITHHOLDING: dict[str, Decimal] = {
    "US": Decimal("0.15"),
    "ES": Decimal("0.19"),
}

# Tipos TECHO de convenio por jurisdiccion del EMISOR, usados SOLO cuando el
# emisor esta verificado en ``_VERIFIED_PAYERS`` (no por el domicilio de la BD
# ni por el mercado de cotizacion). Un techo de convenio no es la retencion
# efectiva: sin NR301/declaracion al pagador Canada aplica 25 % (CRA, Part XIII).
# CA 15 %: art. X.2.b del Convenio ES-CA (Protocolo 2014; 5 % solo sociedad con
# >=10 % directo, no aplica a una persona fisica) y Anexo III AEAT.
_TREATY_CEILING_WITHHOLDING: dict[str, Decimal] = {
    "CA": Decimal("0.15"),
}

# Emisor verificado contra fuente primaria (consultado 2026-10-26). Clave: ticker.
# ``jurisdiction`` = jurisdiccion de constitucion del pagador del dividendo.
# Cualquier ticker ausente conserva el comportamiento anterior (domicilio BD,
# solo US/ES con tipo; el resto "sin verificar").
# Jurisdicciones del emisor con ESCENARIO "sin retencion en origen por ley del
# emisor". KY: 20-F de Alibaba (FY2026) Item 10.E, asesor Maples: los pagos de
# dividendos de ADS/acciones "will not be subject to taxation in the Cayman Islands
# and no withholding will be required". Es la ley del pais del emisor: NO es la
# retencion efectiva del broker ni cubre China (ver ``scenario_conditions``).
_NO_SOURCE_TAX_SCENARIO: dict[str, Decimal] = {"KY": Decimal("0")}

# Condiciones visibles junto al importe de cada escenario (misma fuente: 20-F).
_SCENARIO_CONDITIONS: dict[str, str] = {
    "KY": (
        "Escenario 0 % = solo ley de Islas Caimán (20-F Item 10.E): sin retención en Caimán. "
        "Condiciones: Alibaba no cree ser residente fiscal en China, pero si las autoridades "
        "chinas la trataran como tal podría aplicarse 20 % de IIT a un tenedor persona física "
        "no residente, con reducción por convenio incierta para ADS. Comisiones del depositario "
        "aparte. Retención efectiva del broker: NO verificada."
    ),
}

_VERIFIED_PAYERS: dict[str, dict[str, str]] = {
    "BN": {
        "jurisdiction": "CA",
        "source": "sec_bn_40f",
        "reason_if_unrated": "",
    },
    "BABA": {
        "jurisdiction": "KY",
        "source": "sec_baba_20f",
        "reason_if_unrated": (
            "Emisor constituido en Islas Caimán (ADS en NYSE; la sede en Hong Kong es la que "
            "figura como domicilio en la base de datos). Sin tipo de retención verificado."
        ),
    },
}

_FOREIGN_WITHHOLDING = {"US", "CA", "KY"}  # ES es pago a cuenta nacional, no deducible como impuesto extranjero

_SOURCE_URLS = {
    "aeat_convenios": "https://www3.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/manual-tributacion-no-residentes/anexos/limites-imposicion-convenios.html",
    "aeat_doble_imposicion": "https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-ayuda-presentacion/irpf-2025/8-cumplimentacion-irpf/8_7-cuota-liquida-cuota-resultante-autoliquidacion/8_7_3-cuota-resultante-autoliquidacion/8_7_3_1-deduccion-doble-imposicion-internacional.html",
    "canada_part_xiii_rates": "https://www.canada.ca/en/revenue-agency/services/tax/international-non-residents/payments-non-residents/nr4-part-xiii-tax/part-xiii-withholding-tax/rates-part-xiii-tax.html",
    "convenio_es_ca_protocolo_2014": "https://www.canada.ca/en/department-finance/programs/tax-policy/tax-treaties/country/spain-protocol-2014.html",
    "sec_bn_40f": "https://www.sec.gov/Archives/edgar/data/1001085/000100108526000006/bn-20251231.htm",
    "sec_baba_20f": "https://www.sec.gov/Archives/edgar/data/1577552/000119312526231755/baba-20260331.htm",
    "hmrc_property_income_distributions": "https://www.gov.uk/hmrc-internal-manuals/investment-funds/ifm28125",
}

_METHOD_NOTE = (
    "INFERIDO: réplica mecánica de los dividendos declarados en los últimos 12 "
    "meses desplazados +N años según horizonte (sin crecimiento ni recortes). "
    "Fiscal: ESCENARIO condicionado a residencia fiscal ES, W-8BEN vigente (US) "
    "y a que estos dividendos sean la única renta del ahorro del año; escala del "
    "ahorro de la Renta 2025 (Orden HAC/277/2026) aplicada a años futuros como "
    "hipótesis. Deducción por doble imposición: menor entre impuesto extranjero "
    "soportado y tipo medio efectivo sobre la base extranjera (AEAT). Fuentes y "
    "condiciones en `sources`. No es el neto final: ignora otras rentas, "
    "ganancias/pérdidas y el resto de la base anual."
)

_FISCAL_CONDITIONS = [
    "Residencia fiscal en España asumida.",
    "W-8BEN vigente asumido para dividendos US (sin W-8BEN el tipo sería 30 %).",
    "Tipo de dividendo ordinario asumido: no se verifica la categoría (REIT, ADR, ETF, PID pueden tener tratamiento distinto) y no se deduce del domicilio.",
    "Los tipos de retención son escenario (Anexo III AEAT: convenio US 0/15 según condiciones), no verificación particular de cada pago.",
    "Única renta del ahorro del año asumida; el IRPF real depende del resto de la base.",
    "Escala del ahorro de la Renta 2025 aplicada a años futuros (hipótesis, sujeta a cambio legislativo).",
    "La retención ES del 19 % es pago a cuenta, no impuesto extranjero ni deducción por doble imposición.",
    "Canadá (p. ej. BN): se usa el techo del convenio ES-CA (15 %) como escenario; Canadá retiene 25 % si el broker no aplica el convenio (CRA, Part XIII), y la retención efectiva no está verificada.",
    "Emisor en Islas Caimán (p. ej. BABA): escenario 0 % = solo ley de Caimán (20-F Item 10.E); NO es la retención efectiva del broker y no cubre una posible retención china (20 % IIT condicional, convenio incierto para ADS). Las condiciones se muestran junto al importe.",
    "Emisor verificado por ticker (BN: Ontario; BABA: Islas Caimán). Domicilio de la base de datos o mercado de cotización no determinan la retención.",
    "Domicilios sin tipo verificado (p.ej. GB: HMRC IFM28125 distingue categorías) salen como sin datos.",
]


def _shift_year(d: date, years: int = 1) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 de febrero -> 28 en años no bisiestos
        return d.replace(month=2, day=28, year=d.year + years)


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


class DividendProjectionService:
    def project(self, db: Session, months: int = 12) -> dict[str, Any]:
        today = date.today()
        cutoff = _shift_year(today, -1)
        # Horizonte exacto por fechas: [today, today + months meses], ambos
        # inclusive. Los buckets mensuales cubren desde el mes actual hasta
        # el mes del fin (pueden ser months+1 buckets en la frontera).
        end_year = today.year + (today.month + months - 1) // 12
        end_mon = (today.month + months - 1) % 12 + 1
        end = date(end_year, end_mon, min(today.day, calendar.monthrange(end_year, end_mon)[1]))
        window: list[str] = []
        y, m = today.year, today.month
        while (y, m) <= (end.year, end.month):
            window.append(f"{y:04d}-{m:02d}")
            m += 1
            if m > 12:
                m, y = 1, y + 1
        window_set = set(window)
        years_in_horizon = math.ceil(months / 12)

        fx = PortfolioFXService()
        base_currency = fx.base_currency(db)
        fiscal_ok = base_currency.upper() == "EUR"

        rows = list(
            db.execute(
                select(Position, Company)
                .join(Company, Position.company_id == Company.id)
                .where(Position.quantity > 0)
            ).all()
        )
        company_ids = [company.id for _, company in rows]
        all_records, uncertain_events = resolve_cross_provider_events(
            *resolve_yahoo_events(
                db.scalars(
                    select(DividendRecord).where(DividendRecord.company_id.in_(company_ids))
                ).all()
                if company_ids
                else [],
            )
        )
        uncertain_by_company = {event.company_id for event in uncertain_events}
        records_by_company: dict[int, list[DividendRecord]] = defaultdict(list)
        for record in all_records:
            records_by_company[record.company_id].append(record)
        fx_table = fx.fx_table(
            db,
            currencies={position.currency for position, _ in rows},
            base_currency=base_currency,
            as_of_max=today,
        )

        per_position: list[dict[str, Any]] = []
        sin_datos: list[str] = []
        uncertain_dividends: list[str] = []
        fx_missing: list[str] = []
        unknown_country: list[str] = []
        unverified_reasons: dict[str, str] = {}
        declared_future: list[dict[str, Any]] = []
        # month -> agregado solo de posiciones fiscalmente cubiertas
        month_totals: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "gross_base": Decimal("0"),
                "source_base": Decimal("0"),
                "covered": set(),
                "excluded": set(),
                "unverified": Decimal("0"),
            }
        )
        # (year, ticker) -> gross_base anual proyectado (para IRPF + deducción)
        yearly_position_gross: dict[tuple[int, str], Decimal] = defaultdict(lambda: Decimal("0"))
        yearly_source: dict[tuple[int, str], Decimal] = defaultdict(lambda: Decimal("0"))
        yearly_foreign_gross: dict[tuple[int, str], Decimal] = defaultdict(lambda: Decimal("0"))
        yearly_a_cuenta: dict[tuple[int, str], Decimal] = defaultdict(lambda: Decimal("0"))

        for position, company in rows:
            # Misma moneda en otra unidad (dividendo en GBX, posicion en GBp
            # o GBP): se convierte sin FX; otra moneda se descarta, como antes.
            records = records_in_position_currency(
                records_by_company.get(company.id, []), position.currency
            )
            trailing = [r for r in records if cutoff < r.ex_date <= today]
            future = [r for r in records if r.ex_date > today]
            for record in future:
                declared_future.append(
                    {
                        "ticker": company.ticker,
                        "ex_date": record.ex_date.isoformat(),
                        "pay_date": record.pay_date.isoformat() if record.pay_date else None,
                        "amount_per_share": float(record.amount),
                        "currency": record.currency,
                        "label": "INGESTADO",
                        "source": record.source,
                        "projection_as_of": today.isoformat(),
                        "note": "Declarado con ex_date futura según el proveedor de datos "
                                "(no verificado contra fuente primaria); no alimenta la réplica.",
                    }
                )
            if company.id in uncertain_by_company and any(
                cutoff < e.ex_date <= today for e in uncertain_events if e.company_id == company.id
            ):
                # Evento Yahoo con importes distintos sin evidencia de split: NO es
                # «sin dividendos», es dato incierto; se excluye y se senala aparte.
                uncertain_dividends.append(company.ticker)
                continue
            if not trailing:
                sin_datos.append(company.ticker)
                continue

            quantity = Decimal(str(position.quantity))
            rate = fx.rate_from_table(
                fx_table,
                quote_currency=position.currency,
                base_currency=base_currency,
                as_of=today,
            )
            if rate is None:
                fx_missing.append(company.ticker)

            country = (company.domicile_country or "").upper() or None
            payer = _VERIFIED_PAYERS.get((company.ticker or "").upper())
            basis = "domicilio_bd"
            unverified_reason: str | None = None
            if payer is not None:
                # Emisor verificado: manda la jurisdiccion del pagador, no la BD.
                country = payer["jurisdiction"]
                basis = "emisor_verificado"
                source_rate = _SOURCE_WITHHOLDING.get(country)
                if source_rate is None:
                    source_rate = _TREATY_CEILING_WITHHOLDING.get(country)
                if source_rate is None:
                    source_rate = _NO_SOURCE_TAX_SCENARIO.get(country)
                if source_rate is None:
                    unverified_reason = payer["reason_if_unrated"] or (
                        f"Emisor en {country} sin tipo de retención verificado."
                    )
            else:
                source_rate = _SOURCE_WITHHOLDING.get(country) if country else None
                if source_rate is None:
                    unverified_reason = (
                        f"Domicilio en base de datos: {country}; sin tipo de retención verificado "
                        "para ese país (no se deduce del mercado ni se asume 0 %)."
                        if country
                        else "Sin domicilio ni emisor verificado; retención no verificada."
                    )
            if source_rate is None:
                unknown_country.append(company.ticker)
                unverified_reasons[company.ticker] = unverified_reason or ""
            fiscally_covered = rate is not None and source_rate is not None

            month_entries: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
            for record in trailing:
                # Ex-date ya pasada y pago aun pendiente: ese cobro es real y cae
                # dentro del horizonte (offset 0). Antes solo se replicaba a un
                # ano vista y el trimestre declarado se perdia (3 de 4 pagos).
                # Sin pay_date no hay pago pendiente que contar: solo replicas.
                first_offset = 0 if record.pay_date and record.pay_date > today else 1
                for year_offset in range(first_offset, years_in_horizon + 1):
                    projected = _shift_year(record.pay_date or record.ex_date, year_offset)
                    if projected < today or projected > end:
                        continue
                    key = _month_key(projected)
                    if key in window_set:
                        month_entries[key] += record.amount * quantity

            gross_native_total = sum(month_entries.values(), Decimal("0"))
            gross_base_total: Decimal | None = None
            source_base_total: Decimal | None = None
            if rate is not None:
                gross_base_total = gross_native_total * rate
                if source_rate is not None:
                    source_base_total = gross_base_total * source_rate
            for key, amount_native in month_entries.items():
                bucket = month_totals[key]
                if fiscally_covered and rate is not None:
                    gross_base = amount_native * rate
                    year = int(key[:4])
                    yearly_position_gross[(year, company.ticker)] += gross_base
                    if country in _FOREIGN_WITHHOLDING:
                        yearly_foreign_gross[(year, company.ticker)] += gross_base
                        yearly_source[(year, company.ticker)] += gross_base * source_rate
                    elif country == "ES":
                        yearly_a_cuenta[(year, company.ticker)] += gross_base * source_rate
                    bucket["gross_base"] += gross_base
                    bucket["source_base"] += gross_base * source_rate
                    bucket["covered"].add(company.ticker)
                else:
                    bucket["excluded"].add(company.ticker)
                    if rate is not None:
                        # Bruto con FX conocido pero retencion en origen NO verificada:
                        # se muestra aparte y etiquetado; nunca entra en neto/IRPF.
                        bucket["unverified"] += amount_native * rate

            per_position.append(
                {
                    "ticker": company.ticker,
                    "currency": position.currency,
                    "quantity": float(quantity),
                    "frequency_last_year": len(trailing),
                    "gross_native": float(gross_native_total),
                    "gross_base": (
                        float(gross_base_total) if gross_base_total is not None else None
                    ),
                    "domicile_country": country,
                    "withholding_basis": basis,
                    "withholding_kind": (
                        None
                        if source_rate is None
                        else "sin_impuesto_origen_escenario" if basis == "emisor_verificado" and country in _NO_SOURCE_TAX_SCENARIO
                        else "techo_convenio" if country in _TREATY_CEILING_WITHHOLDING and basis == "emisor_verificado"
                        else "escenario_convenio"
                    ),
                    "unverified_reason": unverified_reason,
                    "scenario_conditions": (
                        _SCENARIO_CONDITIONS.get(country)
                        if source_rate is not None
                        and basis == "emisor_verificado"
                        and country in _NO_SOURCE_TAX_SCENARIO
                        else None
                    ),
                    "source_withholding_rate": (
                        float(source_rate) if source_rate is not None else None
                    ),
                    "source_withheld_base": (
                        float(source_base_total) if source_base_total is not None else None
                    ),
                    "months": {
                        key: float(amount) for key, amount in sorted(month_entries.items())
                    },
                }
            )

        # Escenario fiscal anual: IRPF progresivo por ano natural sobre la
        # cartera y deduccion por doble imposicion por posicion. Solo
        # posiciones fiscalmente cubiertas; excluidas se listan y su parte
        # queda N/D, nunca agregada como cero.
        fiscal_years: dict[int, dict[str, Any]] = {}
        # Tickers excluidos por ano (con dividendo proyectado pero sin fx o
        # sin retencion verificada): se recogen de los buckets mensuales.
        excluded_by_year: dict[int, set] = defaultdict(set)
        for key, bucket in month_totals.items():
            for t in bucket["excluded"]:
                excluded_by_year[int(key[:4])].add(t)
        all_years = sorted(
            {year for year, _ in yearly_position_gross}
            | {year for year, _ in yearly_a_cuenta}
            | set(excluded_by_year)
        )
        for year in all_years:
            tickers = [t for y, t in yearly_position_gross if y == year]
            year_gross = sum(yearly_position_gross[(year, t)] for t in tickers)
            excluded = sorted(excluded_by_year.get(year, set()))
            if year_gross <= 0 and excluded:
                fiscal_years[year] = {
                    "gross_base": None,
                    "irpf_scenario": None,
                    "source_withheld_foreign": None,
                    "retencion_a_cuenta_es": None,
                    "double_tax_deduction": None,
                    "cuota_pendiente_estimada": None,
                    "net_scenario": None,
                    "covered_tickers": [],
                    "excluded_tickers": excluded,
                    "note": "Sin datos: todas las posiciones con dividendo proyectado "
                            "este año carecen de tipo de cambio o de retención verificada (N/D, no cero).",
                }
                continue
            if not fiscal_ok or year_gross <= 0:
                fiscal_years[year] = {
                    "gross_base": float(year_gross),
                    "irpf_scenario": None,
                    "source_withheld_foreign": None,
                    "retencion_a_cuenta_es": None,
                    "double_tax_deduction": None,
                    "cuota_pendiente_estimada": None,
                    "net_scenario": None,
                    "covered_tickers": sorted(tickers),
                    "excluded_tickers": excluded,
                    "note": "Sin datos" if year_gross <= 0 else
                            "Escenario fiscal no disponible: la divisa base no es EUR.",
                }
                continue
            irpf_total = calculate_savings_tax(year_gross, year)
            avg_rate = irpf_total / year_gross
            deduction_total = Decimal("0")
            source_total = Decimal("0")
            a_cuenta_total = Decimal("0")
            per_position_fiscal = {}
            for t in tickers:
                gross_t = yearly_position_gross[(year, t)]
                source_t = yearly_source.get((year, t), Decimal("0"))
                a_cuenta_t = yearly_a_cuenta.get((year, t), Decimal("0"))
                foreign_gross_t = yearly_foreign_gross.get((year, t), Decimal("0"))
                source_total += source_t
                a_cuenta_total += a_cuenta_t
                # Deduccion DI: menor entre impuesto extranjero soportado y
                # tipo medio efectivo sobre la base extranjera de ESA posicion
                # (AEAT, separando rentas). ES no aplica: es pago a cuenta.
                deduction_t = min(
                    source_t if foreign_gross_t > 0 else Decimal("0"),
                    (avg_rate * foreign_gross_t).quantize(Decimal("0.0001")),
                )
                deduction_total += deduction_t
                per_position_fiscal[t] = {
                    "gross_base": float(gross_t),
                    "source_withheld_foreign_base": float(source_t),
                    "retencion_a_cuenta_base": float(a_cuenta_t),
                    "double_tax_deduction_base": float(deduction_t),
                }
            # Cuota pendiente de ingresar: IRPF menos deduccion por doble
            # imposicion y menos lo ya retenido a cuenta (ES). Puede salir
            # negativo (devolucion estimada).
            cuota_pendiente = irpf_total - deduction_total - a_cuenta_total
            # Neto = bruto - impuesto total soportado. El pago a cuenta ES no
            # es un impuesto adicional: es anticipo de la cuota IRPF, asi que
            # el coste fiscal total es IRPF + extranjero - deduccion DI.
            net = year_gross - irpf_total - source_total + deduction_total
            note = "Escenario condicionado (ver «Supuestos fiscales y fuentes»); no es el neto final."
            if excluded:
                note = ("Subconjunto cubierto: hay posiciones excluidas sin tipo de cambio o sin "
                        "retención verificada (sin datos, no cero). " + note)
            fiscal_years[year] = {
                "gross_base": float(year_gross),
                "irpf_scenario": float(irpf_total),
                "source_withheld_foreign": float(source_total),
                "retencion_a_cuenta_es": float(a_cuenta_total),
                "double_tax_deduction": float(deduction_total),
                "cuota_pendiente_estimada": float(cuota_pendiente),
                "net_scenario": float(net),
                "effective_avg_rate": float(avg_rate),
                "per_position": per_position_fiscal,
                "covered_tickers": sorted(tickers),
                "excluded_tickers": excluded,
                "note": note,
            }

        months_out = []
        for key in window:
            bucket = month_totals[key]
            months_out.append(
                {
                    "month": key,
                    "gross_base": float(bucket["gross_base"]),
                    "source_withheld_base": float(bucket["source_base"]),
                    "gross_unverified_base": float(bucket["unverified"]),
                    "gross_total_base": float(bucket["gross_base"] + bucket["unverified"]),
                    "covered_tickers": sorted(bucket["covered"]),
                    "excluded_tickers": sorted(bucket["excluded"]),
                    "note": (
                        "Subconjunto cubierto: hay posiciones con dividendo proyectado "
                        "sin tipo de cambio o sin retención verificada; sus importes no "
                        "se agregan (sin datos, no cero)."
                        if bucket["excluded"]
                        else None
                    ),
                }
            )

        return {
            "as_of": today.isoformat(),
            "base_currency": base_currency,
            "horizon_months": months,
            "label": "INFERIDO",
            "method": _METHOD_NOTE,
            "fiscal_conditions": _FISCAL_CONDITIONS,
            "sources": _SOURCE_URLS,
            "months": months_out,
            "fiscal_by_year": {str(year): data for year, data in sorted(fiscal_years.items())},
            "positions": per_position,
            "gross_summary": {
                "label": "BRUTO, retención en origen no verificada en las posiciones sin tipo conocido",
                "gross_total_base": float(
                    sum((b["gross_base"] + b["unverified"] for b in (month_totals[k] for k in window)), Decimal("0"))
                ),
                "gross_unverified_base": float(
                    sum((month_totals[k]["unverified"] for k in window), Decimal("0"))
                ),
                "net_irpf": "N/D salvo posiciones con retención verificada",
                # El total es PARCIAL si falta algún tipo de cambio o hay
                # posiciones sin dividendos conocidos: nunca es "la cartera".
                "excluded_no_fx": sorted(set(fx_missing)),
                "excluded_no_dividends": sorted(sin_datos),
                "excluded_uncertain_dividends": sorted(uncertain_dividends),
                "complete": not (set(fx_missing) or set(sin_datos) or set(uncertain_dividends)),
            },
            "declared_future": declared_future,
            "coverage": {
                "with_data": len(per_position),
                "sin_datos": sorted(sin_datos),
                "uncertain_dividends": sorted(uncertain_dividends),
                "fx_missing": sorted(set(fx_missing)),
                "unknown_source_withholding": sorted(set(unknown_country)),
                "unverified_reasons": dict(sorted(unverified_reasons.items())),
            },
        }
