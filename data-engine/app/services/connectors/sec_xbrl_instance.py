"""Parser de instancias XBRL de EDGAR (fichero *_htm.xml de un filing).

La API companyfacts excluye hechos con dimensiones: los filers por clases
(Visa, Berkshire, ...) declaran EPS/acciones por clase y la API gratuita se
queda sin ellos. Este parser lee la instancia XBRL del filing y recupera
esos hechos CON su miembro dimensional, sin inventar nada: solo lo que el
emisor declaro, con su contexto (periodo + miembro + eje).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET  # nosec B314  # stdlib solo para tipos (Element) y ParseError: defusedxml no los exporta; el parseo usa defusedxml
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

# XBRL externo (SEC/ESEF): defusedxml solo para PARSEAR (iterparse).
import defusedxml.ElementTree as DefusedET

# Tags XBRL (nombre local) que alimentan cada metrica interna. Los "basic"
# solo se usan cuando el emisor no declara el diluido (Berkshire no tiene
# dilucion); el tag real usado queda en la procedencia.
METRIC_TAGS: dict[str, tuple[str, ...]] = {
    "eps_diluted": ("EarningsPerShareDiluted", "EarningsPerShareBasic"),
    "shares_diluted": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
}

# dei:EntityCommonStockSharesOutstanding (portada, INSTANTE por clase). Los
# filers multi-clase (META, GOOGL, BRK.B, ASTS, V) no tienen el saldo
# consolidado en companyfacts (la SEC excluye hechos dimensionados): entra
# por el carril per-clase del class_filer_eps_service, nunca por aqui como
# hecho suelto.
ECSO_TAG = "EntityCommonStockSharesOutstanding"

# Unidades declaradas (`unitRef`) que admiten cada metrica. Un BPA etiquetado
# en acciones, o un saldo de acciones etiquetado en moneda, es OTRA magnitud
# y no se lee como la metrica (FIX5-5). Con `unitRef` se exige declaracion
# estructural valida; sin `unitRef` se conserva la compatibilidad sintetica.
_EPS_UNITS = frozenset({"uUSD", "usd", "USD", "EUR", "iso4217:EUR", "iso4217:USD", "usdPerShare"})
_SHARE_UNITS = frozenset({"ushares", "shares", "xbrli:shares", "pure"})
ALLOWED_UNITS: dict[str, frozenset[str]] = {
    "EarningsPerShareDiluted": _EPS_UNITS,
    "EarningsPerShareBasic": _EPS_UNITS,
    "WeightedAverageNumberOfDilutedSharesOutstanding": _SHARE_UNITS,
    "WeightedAverageNumberOfSharesOutstandingBasic": _SHARE_UNITS,
    ECSO_TAG: _SHARE_UNITS,
}

_ALL_TAGS = {tag for tags in METRIC_TAGS.values() for tag in tags} | {ECSO_TAG}


_XBRLI_NS = "http://www.xbrl.org/2003/instance"
_ISO4217_NS = "http://www.xbrl.org/2003/iso4217"
_SHARES_CLARK = "{" + _XBRLI_NS + "}shares"


def _qname_clark(text: str, scope: dict[str, str]) -> str:
    """Resuelve un QName `prefijo:local` (o sin prefijo = ns por defecto) a
    `{uri}local`. Prefijo no declarado: se deja tal cual (nunca coincide)."""
    prefix, sep, local = text.partition(":")
    if not sep:
        uri = scope.get("")
        return "{" + uri + "}" + text if uri else text
    uri = scope.get(prefix)
    return "{" + uri + "}" + local if uri else text


def _unit_allowed(tag: str, unit_ref: str, units: dict[str, tuple[tuple[str, ...], tuple[str, ...]]]) -> bool:
    """Valida la unidad CONTRA su estructura declarada en la instancia.

    Los emisores reales usan ids propios (BRK: `U_UnitedStatesOfAmericaDollarsShare`,
    `U_shares`): el id no dice la magnitud, el `<unit>` si. Se conserva la
    estructura (numerador, denominador): el BPA es moneda / acciones, no
    shares / USD ni shares / shares, y las acciones son una unidad simple
    `xbrli:shares`. Una unidad no declarada en la instancia no prueba la
    magnitud: fallo cerrado.
    """
    allowed = ALLOWED_UNITS.get(tag)
    if allowed is None:
        return True
    structure = units.get(unit_ref)
    if structure is None:
        return False
    numerator, denominator = structure
    if allowed is _EPS_UNITS:
        return (
            len(numerator) == 1
            and numerator[0].startswith("{" + _ISO4217_NS + "}")
            and denominator == (_SHARES_CLARK,)
        )
    return numerator == (_SHARES_CLARK,) and not denominator


@dataclass(frozen=True)
class DimensionedFact:
    tag: str
    value: Decimal
    start: date | None
    end: date | None
    instant: date | None
    # (eje, miembro): sin el eje no se puede distinguir un miembro de CLASE
    # (el BPA por clase del emisor) de un miembro de SEGMENTO (el BPA de un
    # negocio) (FIX5-9).
    members: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def member_names(self) -> tuple[str, ...]:
        return tuple(member for _axis, member in self.members)

    @property
    def duration_days(self) -> int | None:
        if self.start is None or self.end is None:
            return None
        return (self.end - self.start).days


def _local(name: str) -> str:
    return name.split("}")[-1].split(":")[-1]


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _member_pairs(context: ET.Element) -> tuple[tuple[str, str], ...]:
    """(eje, miembro) de cada explicitMember del contexto.

    En iXBRL el eje viaja como atributo `dimension` del propio explicitMember;
    se acepta tambien como elemento hijo por si el render lo expresa asi. Sin
    eje el miembro queda con eje vacio y el consumidor decide (FIX5-9).
    """
    pairs: list[tuple[str, str]] = []
    for node in context.iter():
        if _local(node.tag) == "typedMember":
            # Preserve otherwise invisible extra scope for class-total guards.
            # A typed value is not a class QName and must not be a candidate.
            pairs.append(((node.get("dimension") or "").strip(), "__typed_member__"))
            continue
        if _local(node.tag) != "explicitMember" or not node.text:
            continue
        axis = (node.get("dimension") or "").strip()
        if not axis:
            dim = next(
                (d for d in node.iter() if _local(d.tag) == "dimension"), None
            )
            axis = ((dim.text or "").strip() if dim is not None else "")
        pairs.append((axis, _local(node.text)))
    return tuple(pairs)


def parse_instance_dimensioned_facts(
    stream,
    *,
    min_days: int = 300,
    max_days: int = 380,
) -> list[DimensionedFact]:
    """Hechos con dimension de miembro y duracion anual de una instancia XBRL.

    Solo devuelve hechos que llevan al menos un explicitMember (los sin
    dimension ya los cubre companyfacts) y con duracion dentro de
    [min_days, max_days] (anual; absorbe anos de 52/53 semanas). Valores no
    numericos o no finitos se descartan: nunca llegan a la BD.

    El valor es el DECLARADO en el elemento: iXBRL expresa la magnitud real en
    el literal escalado por `scale` y con `sign="-"` negada (FIX5-5). Un
    `unitRef` que la metrica no admite descarta el hecho entero.
    """
    contexts: dict[str, tuple[date | None, date | None, date | None, tuple[tuple[str, str], ...]]] = {}
    units: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    facts: list[DimensionedFact] = []
    # Ambito de prefijos de namespace: el `<measure>` es un QName y se resuelve
    # con las declaraciones del documento (incluida la por defecto), no por su
    # texto literal: Visa/BRK escriben `shares` sin prefijo.
    scopes: list[dict[str, str]] = [{}]
    pending_ns: list[tuple[str, str]] = []
    for _event, el in DefusedET.iterparse(stream, events=("start-ns", "start", "end")):
        if _event == "start-ns":
            pending_ns.append(el)  # type: ignore[arg-type]
            continue
        if _event == "start":
            scope = dict(scopes[-1])
            scope.update(pending_ns)
            pending_ns = []
            scopes.append(scope)
            continue
        scope = scopes.pop()
        tag = _local(el.tag)
        if tag == "measure":
            # Cada measure se resuelve con SU propio ambito (puede redeclarar
            # prefijos o el ns por defecto) antes de perderlo al cerrarse.
            el.set("clark", _qname_clark((el.text or "").strip(), scope))
            continue
        if tag == "unit":
            def _measures(parent) -> tuple[str, ...]:
                return tuple(
                    node.get("clark") or ""
                    for node in parent.iter()
                    if _local(node.tag) == "measure"
                )

            numerator = denominator = None
            for child in el:
                if _local(child.tag) == "divide":
                    for part in child:
                        if _local(part.tag) == "unitNumerator":
                            numerator = _measures(part)
                        elif _local(part.tag) == "unitDenominator":
                            denominator = _measures(part)
            if numerator is None:
                numerator, denominator = _measures(el), ()
            units[el.get("id") or ""] = (numerator, denominator or ())
            el.clear()
        elif tag == "context":
            members = _member_pairs(el)
            start = end = instant = None
            for node in el.iter():
                node_tag = _local(node.tag)
                if node_tag == "startDate":
                    start = _parse_date(node.text)
                elif node_tag == "endDate":
                    end = _parse_date(node.text)
                elif node_tag == "instant":
                    instant = _parse_date(node.text)
            contexts[el.get("id") or ""] = (start, end, instant, members)
            el.clear()
        elif tag in _ALL_TAGS:
            raw = (el.text or "").strip()
            try:
                value = Decimal(raw)
            except (InvalidOperation, ValueError):
                el.clear()
                continue
            if not value.is_finite():
                el.clear()
                continue
            unit_ref = (el.get("unitRef") or "").strip() or None
            if unit_ref is not None and not _unit_allowed(tag, unit_ref, units):
                el.clear()
                continue
            scale = el.get("scale") or "0"
            try:
                value = value * (Decimal(10) ** int(scale))
            except (InvalidOperation, ValueError):
                el.clear()
                continue
            if el.get("sign") == "-":
                value = -value
            start, end, instant, members = contexts.get(
                el.get("contextRef") or "", (None, None, None, ())
            )
            if members:
                facts.append(
                    DimensionedFact(
                        tag=tag,
                        value=value,
                        start=start,
                        end=end,
                        instant=instant,
                        members=members,
                    )
                )
            el.clear()
    if min_days is not None or max_days is not None:
        facts = [
            f
            for f in facts
            if f.duration_days is not None
            and (min_days is None or f.duration_days >= min_days)
            and (max_days is None or f.duration_days <= max_days)
        ]
    return facts


def parse_instance_dimensioned_ecso(stream) -> list[DimensionedFact]:
    """Hechos dei:EntityCommonStockSharesOutstanding DIMENSIONADOS (por
    clase) de una instancia XBRL: instantes de portada, no duraciones.

    Los hechos sin dimension los cubre el carril companyfacts (ingesta
    estandar): aqui solo interesan los miembros de clase que la SEC no
    consolida. El consumidor decide que miembros son de CLASE (eje
    *ClassAxis) y como agregarlos (suma derivada documentada).
    """
    return [
        f
        for f in parse_instance_dimensioned_facts(
            stream, min_days=None, max_days=None
        )
        if f.tag == ECSO_TAG and f.instant is not None
    ]
