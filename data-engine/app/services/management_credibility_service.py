"""Track dated management promises against later reported outcomes."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.models import (
    CallClaim,
    Company,
    Document,
    FinancialFact,
    ManagementPromise,
    Transcript,
)

OPERATORS = {
    ">": lambda actual, target: actual > target,
    ">=": lambda actual, target: actual >= target,
    "<": lambda actual, target: actual < target,
    "<=": lambda actual, target: actual <= target,
    "==": lambda actual, target: actual == target,
}

# Multiplicadores de magnitud que aparecen tras la cifra en una promesa real
# ("at least $5 billion", "hasta 200 millones"). Sin escalarlos, el objetivo
# quedaba en unidades sueltas (5) y el veredicto contra el hecho en unidades
# brutas (5_000_000_000) salia inventado. OJO: escala del espanol — un billon
# son 10^12 (un "mil millones" es 10^9); en ingles billion es 10^9.
_MAGNITUDES = {
    "mil millones": Decimal("1000000000"),
    "billones": Decimal("1000000000000"),
    "billón": Decimal("1000000000000"),
    "billion": Decimal("1000000000"),
    "bn": Decimal("1000000000"),
    "millones": Decimal("1000000"),
    "million": Decimal("1000000"),
    "millón": Decimal("1000000"),
    "mn": Decimal("1000000"),
    "thousand": Decimal("1000"),
    "mil": Decimal("1000"),
    "k": Decimal("1000"),
}

# Cualificador -> operador. Los EN conservan su mapeo historico (at least,
# more than, above -> >=; up to, less than, below -> <=); los ES se mapean por
# significado: "mas de"/"menos de" son estrictos.
_QUALIFIER_OPERATORS = {
    "at least": ">=",
    "more than": ">=",
    "above": ">=",
    "up to": "<=",
    "less than": "<=",
    "below": "<=",
    "approximately": "==",
    "about": "==",
    "al menos": ">=",
    "como mínimo": ">=",
    "como minimo": ">=",
    "más de": ">",
    "mas de": ">",
    "superior a": ">",
    "por encima de": ">",
    "hasta": "<=",
    "como máximo": "<=",
    "como maximo": "<=",
    "menos de": "<",
    "inferior a": "<",
    "por debajo de": "<",
    "aproximadamente": "==",
    "alrededor de": "==",
    "cerca de": "==",
}

# Solo estos cualificadores hacen que un "==" cuente cumplido dentro del 5%:
# la aproximacion la declara el directivo. Un "==" sin cualificador sigue
# siendo exacto para "met" y "partial" dentro del 5%.
_APPROXIMATE_QUALIFIERS = frozenset(
    {"approximately", "about", "aproximadamente", "alrededor de", "cerca de"}
)

# Alternacion ordenada de mayor a menor longitud para que "mil millones" gane
# a "mil" y "como mínimo" a "mínimo".
_QUALIFIERS_ALT = "|".join(
    sorted(_QUALIFIER_OPERATORS, key=len, reverse=True)
)
_MAGNITUDES_ALT = "|".join(sorted(_MAGNITUDES, key=len, reverse=True))

# El \b inicial impide casar el digito de un token pegado (Q3, FY2026, H1):
# ahi no hay frontera de palabra y no se genera candidato.
_TARGET_RE = re.compile(
    rf"\b(?:(?P<qualifier>{_QUALIFIERS_ALT})\b\s*)?"
    r"[$€£]?\s*"
    r"(?P<number>\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)?)"
    rf"(?:\s*(?P<magnitude>{_MAGNITUDES_ALT})\b)?",
    flags=re.IGNORECASE,
)

# "2H26" y "2H" (semestre, con o sin ano): el digito inicial lo sigue una H
# de periodo; no es un objetivo ("growth in 2H of 8%" apunta al 8, no al 2).
_HALF_PREFIX_RE = re.compile(r"^[Hh](?:\d|\b)")
# "10-K": el numero del formulario no es un objetivo.
_FORM_10K_RE = re.compile(r"^-\s*[Kk]\b")
# Un rango no es un objetivo unico. Marcador delante de la primera cifra
# ("between $4 and...", "entre 4 y...", "de 4 a...") con union palabra, o
# union dura sin marcador ("4 to 5", "$4-$5").
_RANGE_MARKER_RE = re.compile(r"\b(?:between|entre|de)\s*[$€£]?\s*$", flags=re.IGNORECASE)
_RANGE_WORD_JOIN_RE = re.compile(r"^\s*[$€£]?\s*(?:and|y|a)\s*[$€£]?\s*$", flags=re.IGNORECASE)
_RANGE_HARD_JOIN_RE = re.compile(r"^\s*[$€£]?\s*(?:to|[-–])\s*[$€£]?\s*$", flags=re.IGNORECASE)
# Tras "hasta <ano>", esto delimita un plazo: fin de frase, puntuacion o
# "de/en/inclusive" ("hasta 2027", "hasta 2027 de 5 millones", "hasta 2027
# inclusive"). Los conectores a/y/e NO: "hasta 2000 y 3000 unidades" o
# "hasta 2000 a 3000 unidades" tienen la cifra como objetivo (variante de
# Cerebro, FAV v5). Un sustantivo de unidad ("hasta 2000 vehiculos")
# tampoco es plazo: la cifra es la cantidad objetivo.
_HASTA_YEAR_TRAILER_RE = re.compile(
    r"^\s*(?:$|[.,;:)\-–]|de\b|en\b|inclusive\b)", flags=re.IGNORECASE
)

_EN_MAGNITUDES = frozenset({"billion", "bn", "million", "mn", "thousand", "k"})
_ES_MAGNITUDES = frozenset({"millones", "millón", "mil millones", "billones", "billón", "mil"})


def _parse_number(raw: str, magnitude: str = "") -> Decimal | None:
    """Cifra con separadores; el idioma de la magnitud decide su papel.

    Con magnitud espanola (millones, mil millones, billones, mil) el punto es
    de millares y la coma decimal; con magnitud inglesa (billion, million,
    bn, mn, thousand, k) o sin magnitud, al reves. Una cabeza "0" siempre es
    decimal ("0.250" es 0.25). "12.000" sin magnitud es ambiguo: None antes
    que inventar la escala (un x1000 cambia el veredicto).
    """
    es = magnitude.lower() in _ES_MAGNITUDES
    try:
        if "," in raw and "." in raw:
            if raw.rfind(",") > raw.rfind("."):
                return Decimal(raw.replace(".", "").replace(",", "."))
            return Decimal(raw.replace(",", ""))
        if "," in raw:
            _head, _, tail = raw.rpartition(",")
            if not es and len(tail) == 3:
                # EN o sin magnitud: "1,200" son millares.
                return Decimal(raw.replace(",", ""))
            # ES: "2,5" es 2.5 (los millares van con punto).
            return Decimal(raw.replace(",", "."))
        if "." in raw:
            head, _, tail = raw.rpartition(".")
            if head == "0":
                return Decimal(raw)
            if es:
                if len(tail) == 3 and head.replace(".", "").isdigit():
                    return Decimal(raw.replace(".", ""))
                return Decimal(raw)
            if not magnitude and len(tail) == 3 and head.replace(".", "").isdigit():
                return None
            return Decimal(raw)
        return Decimal(raw)
    except ArithmeticError:
        return None


class ManagementCredibilityService:
    def register(
        self,
        db: Session,
        company: Company,
        *,
        promise: str,
        promise_date: date,
        expected_period: str,
        metric: str | None,
        operator: str | None,
        target_value: Decimal | None,
        unit: str | None,
        source_document_id: int | None = None,
        call_claim_id: int | None = None,
        approximate: bool = False,
    ) -> ManagementPromise:
        if target_value is not None and operator not in OPERATORS:
            raise ValueError("A numeric promise requires a supported operator")
        if source_document_id is not None:
            # El id llega del cliente: sin comprobarlo, uno inexistente rompía la
            # FK en Postgres (500) y uno de otro usuario o empresa se enlazaba.
            # db.get va acotado por tenant.
            document = db.get(Document, source_document_id)
            if document is None or document.company_id not in (None, company.id):
                raise ValueError("Source document not found for this company")
        row = ManagementPromise(
            company_id=company.id,
            source_document_id=source_document_id,
            call_claim_id=call_claim_id,
            promise=promise.strip(),
            promise_date=promise_date,
            expected_period=expected_period.strip(),
            metric=metric.strip().lower() if metric else None,
            operator=operator,
            target_value=target_value,
            unit=unit,
            status="open",
            evidence=[],
            metadata_={
                "source": "manual" if call_claim_id is None else "call_claim",
                "approximate": approximate,
            },
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def import_call_claims(
        self, db: Session, company: Company
    ) -> list[ManagementPromise]:
        claims = list(
            db.scalars(
                select(CallClaim)
                .join(Transcript, CallClaim.transcript_id == Transcript.id)
                .where(
                    Transcript.company_id == company.id,
                    CallClaim.claim_type.in_(["guidance", "commitment", "target"]),
                )
                .order_by(CallClaim.id)
            ).all()
        )
        created = []
        for claim in claims:
            existing = db.scalar(
                select(ManagementPromise).where(
                    ManagementPromise.call_claim_id == claim.id
                )
            )
            if existing:
                created.append(existing)
                continue
            operator, target, qualifier = self._parse_target(claim.claim)
            row = ManagementPromise(
                company_id=company.id,
                call_claim_id=claim.id,
                promise=claim.claim,
                promise_date=claim.created_at.date(),
                expected_period=claim.period or "unspecified",
                # register() normaliza la metrica; aqui llega cruda del extractor
                # y un 'Revenue' con mayuscula nunca casaba con el hecho
                # ('revenue'), dejando la promesa abierta para siempre.
                metric=claim.metric.strip().lower() if claim.metric else None,
                operator=operator,
                target_value=target,
                unit=None,
                status="open",
                evidence=[
                    {
                        "call_claim_id": claim.id,
                        "transcript_id": claim.transcript_id,
                        "speaker": claim.speaker,
                    }
                ],
                metadata_={
                    "source": "call_claim",
                    "speaker_role": claim.speaker_role,
                    # Solo una promesa declarada aproximada ('about', 'alrededor
                    # de'...) puede contar cumplida dentro del 5%; un '=='
                    # pelado sigue exigiendo la cifra exacta para 'met'.
                    "approximate": qualifier in _APPROXIMATE_QUALIFIERS,
                },
            )
            db.add(row)
            created.append(row)
        db.commit()
        for row in created:
            db.refresh(row)
        return created

    def reconcile(
        self, db: Session, company: Company
    ) -> list[ManagementPromise]:
        promises = list(
            db.scalars(
                select(ManagementPromise)
                .where(ManagementPromise.company_id == company.id)
                .order_by(ManagementPromise.promise_date, ManagementPromise.id)
            ).all()
        )
        for promise in promises:
            if not promise.metric:
                continue
            statement = select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == promise.metric,
                # Un veredicto solo puede salir de cifras REPORTADAS: un hecho
                # estimado o derivado marcaba promesas como cumplidas con un
                # dato que la empresa nunca publico.
                FinancialFact.is_reported.is_(True),
            )
            year_match = re.search(r"(?:19|20)\d{2}", promise.expected_period)
            if year_match:
                year = int(year_match.group(0))
                normalized_period = re.sub(
                    r"[^A-Z0-9]", "", promise.expected_period.upper()
                )
                quarter_match = re.search(r"Q[1-4]", normalized_period)
                if quarter_match:
                    # Hechos trimestrales ingeridos desde 10-Q llevan
                    # fiscal_year NULL y el año solo en period '<end>:Qn';
                    # exigir fiscal_year == año los dejaria irreconciliables.
                    statement = statement.where(
                        FinancialFact.fiscal_quarter == quarter_match.group(0),
                        or_(
                            FinancialFact.fiscal_year == year,
                            FinancialFact.period.like(f"{year}-%"),
                        ),
                    )
                elif "FY" in normalized_period:
                    statement = statement.where(
                        FinancialFact.fiscal_year == year
                    )
                    # An annual promise must not be reconciled against a later
                    # quarterly observation from the same fiscal year.
                    statement = statement.where(
                        or_(
                            FinancialFact.fiscal_quarter == "FY",
                            FinancialFact.fiscal_quarter.is_(None),
                        )
                    )
            else:
                statement = statement.where(
                    FinancialFact.period == promise.expected_period
                )
            actual = db.scalar(
                statement.order_by(desc(FinancialFact.created_at)).limit(1)
            )
            if actual is None:
                continue
            promise.actual_fact_id = actual.id
            promise.actual_value = actual.value
            promise.verified_at = datetime.now(UTC)
            if promise.target_value is None or promise.operator not in OPERATORS:
                promise.status = "outcome_recorded"
            else:
                met = OPERATORS[promise.operator](actual.value, promise.target_value)
                distance = abs(actual.value - promise.target_value)
                tolerance = abs(promise.target_value) * Decimal("0.05")
                approximate = promise.operator == "==" and bool(
                    (promise.metadata_ or {}).get("approximate")
                )
                if met or (
                    # Solo si el directivo dijo 'approximately/about' (o su
                    # equivalente ES) la igualdad no es exacta: dentro del 5%
                    # cuenta cumplida. Un '==' sin cualificador sigue parcial.
                    approximate and distance <= tolerance
                ):
                    promise.status = "met"
                else:
                    promise.status = "partial" if distance <= tolerance else "missed"
            # Conciliar otra vez con el mismo dato no es evidencia nueva: antes
            # cada pulsación de «Conciliar» repetía la entrada.
            if any(
                isinstance(item, dict) and item.get("financial_fact_id") == actual.id
                for item in (promise.evidence or [])
            ):
                continue
            promise.evidence = [
                *(promise.evidence or []),
                {
                    "financial_fact_id": actual.id,
                    "period": actual.period,
                    "source_type": actual.source_type,
                    "actual_value": str(actual.value),
                },
            ]
        db.commit()
        for promise in promises:
            db.refresh(promise)
        return promises

    def set_explanation(
        self, db: Session, promise: ManagementPromise, explanation: str
    ) -> ManagementPromise:
        promise.management_explanation = explanation.strip()
        db.commit()
        db.refresh(promise)
        return promise

    def dashboard(self, db: Session, company: Company) -> dict[str, Any]:
        promises = list(
            db.scalars(
                select(ManagementPromise)
                .where(ManagementPromise.company_id == company.id)
                .order_by(desc(ManagementPromise.promise_date))
            ).all()
        )
        resolved = [row for row in promises if row.status in {"met", "partial", "missed"}]
        score = (
            sum(1 if row.status == "met" else 0.5 if row.status == "partial" else 0 for row in resolved)
            / len(resolved)
            if resolved
            else None
        )
        return {
            "ticker": company.ticker,
            "score": score,
            "grade": (
                "high" if score is not None and score >= 0.8 else
                "mixed" if score is not None and score >= 0.5 else
                "low" if score is not None else "insufficient_history"
            ),
            "counts": {
                "total": len(promises),
                "open": sum(row.status == "open" for row in promises),
                "met": sum(row.status == "met" for row in promises),
                "partial": sum(row.status == "partial" for row in promises),
                "missed": sum(row.status == "missed" for row in promises),
            },
            "promises": [self.payload(row) for row in promises],
            "method": "resolved promises: met=1, partial=0.5, missed=0",
        }

    @staticmethod
    def payload(row: ManagementPromise) -> dict[str, Any]:
        return {
            "id": row.id,
            "company_id": row.company_id,
            "source_document_id": row.source_document_id,
            "call_claim_id": row.call_claim_id,
            "promise": row.promise,
            "promise_date": row.promise_date,
            "expected_period": row.expected_period,
            "metric": row.metric,
            "operator": row.operator,
            "target_value": row.target_value,
            "unit": row.unit,
            "actual_fact_id": row.actual_fact_id,
            "actual_value": row.actual_value,
            "status": row.status,
            "management_explanation": row.management_explanation,
            "verified_at": row.verified_at,
            "evidence": row.evidence,
        }

    @staticmethod
    def _parse_target(text: str) -> tuple[str | None, Decimal | None, str]:
        """(operador, objetivo, cualificador); cualificador "" si no hubo."""
        candidates: list[tuple[str, Decimal, str, int, int]] = []
        for match in _TARGET_RE.finditer(text):
            number_text = match.group("number")
            magnitude = (match.group("magnitude") or "").lower()
            magnitude = re.sub(r"\s+", " ", magnitude)
            qualifier = (match.group("qualifier") or "").lower()
            following = text[match.end("number"):]
            # Un ano (2026), un semestre (2H26) o un formulario (10-K) no son
            # el objetivo numerico: antes se tomaban como target y el veredicto
            # comparaba el hecho contra 2026.
            if _HALF_PREFIX_RE.match(following) or _FORM_10K_RE.match(following):
                continue
            preceding = text[: match.start("number")].rstrip()
            # Token de periodo SUELTO delante ("FY 2026", "Q 3", "H 2"); un
            # token pegado (Q3) ya lo frena el \b y una palabra que acabe en h
            # (launch, growth) no es un periodo.
            if re.search(r"(?:^|\s)(?:fy|q|h)$", preceding, flags=re.IGNORECASE):
                continue
            numeric = _parse_number(number_text, magnitude)
            if numeric is None:
                continue
            year_shaped = (
                not magnitude
                and not re.search(r"[.,]", number_text)
                and len(number_text) == 4
                and 1900 <= int(number_text) <= 2099
            )
            if year_shaped and (
                not qualifier
                or (qualifier == "hasta" and _HASTA_YEAR_TRAILER_RE.match(following))
            ):
                # Un ano pelado nunca es el objetivo; tras "hasta" tampoco si
                # cierra plazo ("ventas de 5 millones hasta 2027": la cifra es
                # 5 millones, FAV v4). Con sustantivo de unidad o conector de
                # lista la cifra SI es el objetivo ("hasta 2000 vehiculos" y
                # "hasta 2000 y 3000 unidades" son <=2000; variante de
                # Cerebro, FAV v5). Coste declarado: "hasta 2000 en tiendas" o
                # "hasta 2000 de clientes" se leen como plazo y no dan
                # objetivo. El resto de cualificadores no cambian: "deliver
                # at least 2000 vehicles" es >=2000 (FAV r1), "above 2026
                # units" es >=2026. EN sin regla: by/through/until no son
                # cualificadores.
                continue
            candidates.append(
                (qualifier, numeric, magnitude, match.start("number"), match.end("number"))
            )
        if not candidates:
            return None, None, ""
        # Un rango no cabe en un (operador, objetivo) unico; declararlo sin
        # objetivo es mejor que un == contra el extremo inferior (FAV
        # Calidad/datos): "between $4 and $5 billion", "entre 4 y 5 mil
        # millones", "de 4 a 5", "4 to 5 billion", "$4-$5 billion".
        if len(candidates) >= 2:
            _q0, _n0, _m0, start0, end0 = candidates[0]
            _q1, _n1, _m1, start1, _e1 = candidates[1]
            join = text[end0:start1]
            if _RANGE_HARD_JOIN_RE.fullmatch(join) or (
                _RANGE_MARKER_RE.search(text[:start0])
                and _RANGE_WORD_JOIN_RE.fullmatch(join)
            ):
                return None, None, ""
        # Si hay una cifra con cualificador ('at least $5 billion'), esa manda;
        # sin cualificadores se toma la primera cifra que no sea ano/trimestre.
        qualifier, numeric, magnitude, _start, _end = next(
            (candidate for candidate in candidates if candidate[0]),
            candidates[0],
        )
        operator = _QUALIFIER_OPERATORS.get(qualifier, "==")
        return operator, numeric * _MAGNITUDES.get(magnitude, Decimal(1)), qualifier

    @staticmethod
    def _target(text: str) -> tuple[str | None, Decimal | None]:
        operator, numeric, _qualifier = ManagementCredibilityService._parse_target(text)
        return operator, numeric
