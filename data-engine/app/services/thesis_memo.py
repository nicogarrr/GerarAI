"""Memo Markdown descargable de una tesis (solo lectura de datos persistidos).

Nunca inventa contenido: cada seccion sale de ThesisVersion/ThesisSection/
ClaimEvidence tal cual esta persistida; lo que falta se marca como
"pendiente". Siempre cierra con el aviso de que no es asesoramiento
financiero.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Claim, ClaimEvidence, Company, SourceAudit, ThesisSection, ThesisVersion
from app.services.display_es import fecha_es
from app.services.memo_text_es import RATING_ES, STATUS_ES, label_es, money_thesis, percent_es
from app.services.thesis_approval_service import APPROVAL_SECTION_TITLE
from app.services.thesis_publication_gate import archived_thesis_notice, thesis_withheld_reason
from app.valuation.margin_convention import (
    MARGIN_OF_SAFETY_CONVENTION,
    MARGIN_OF_SAFETY_FORMULA,
)


def _fecha_hora_utc(value: datetime) -> str:
    """«24 oct 2026, 09:41 UTC»: la fecha en la forma corta que usa la web.

    La ficha pinta «generada el 24 oct 2026» (formatGeneratedDate, es-ES);
    el memo es el mismo documento y no puede fechar en ISO crudo.
    """
    return f"{fecha_es(value)}, {value:%H:%M} UTC"


def _fraction_row_to_percent(line: str) -> str:
    """Fila de tabla con unidad EXPLÍCITA «fracción» y valor 0,xx -> «xx %».

    Solo si la celda de unidad dice exactamente «fracción» y el valor es un
    decimal simple; en cualquier otro caso la fila queda tal cual.
    """
    cells = line.split("|")
    # cells[0] y cells[-1] son los bordes vacíos de la fila.
    if len(cells) < 5 or cells[3].strip() != "fracción":
        return line
    raw = cells[2].strip()
    if not re.fullmatch(r"-?\d+,\d+", raw):
        return line
    # Decimal exacto: sin redondeo (0,2345 -> 23,45 %; 0,23 -> 23 %).
    pct = (Decimal(raw.replace(",", ".")) * 100).normalize()
    text = format(pct, "f").replace(".", ",")
    cells[2] = f" {text} % "
    cells[3] = " porcentaje "
    return "|".join(cells)


def _full_analysis_lines(markdown: str) -> list[str]:
    """Cuerpo del análisis persistido (thesis_markdown) listo para el memo.

    Se quita el título propio y se baja un nivel cada encabezado para que cuelgue
    de «Análisis completo». Es el mismo texto que ve la ficha: no se reescribe ni
    se rellena nada.
    """
    out: list[str] = []
    seen_refs: set[str] = set()
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            continue
        if line.startswith("Doctrina de inversión") or line.startswith("Extracto documental"):
            # Contexto recuperado (biblioteca o documentos): solo la referencia
            # (título y fuente), nunca el texto del fragmento en un documento exportable.
            ref = re.split(r"\s(?:Biblioteca|Documento)\s\d+:", line, maxsplit=1)[0].rstrip()
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
            line = f"- {ref} [texto del extracto omitido; consultar en la ficha]"
            out.append(line)
            continue
        # Solo campos identificados del productor, nunca prosa libre:
        # - "- Estado: `ok` publicable=True" (marca interna que contradice el estado);
        # - celdas "N hechos citados (id, id, ...)" de la tabla de procedencia
        #   (los ids siguen en la ficha).
        if line.startswith("- Estado:"):
            line = re.sub(r"\s+publicable=(?:True|False|None)\s*$", "", line)
        if line.startswith("|"):
            line = re.sub(r"(\d+ hechos? citados?) \(\d+(?:, \d+)*\)", r"\1", line)
            line = _fraction_row_to_percent(line)
        if line.startswith("### "):
            out.append(f"**{line[4:]}**")
        elif line.startswith("## "):
            out.append(f"### {line[3:]}")
        else:
            out.append(line)
    return out


def _narrative_lines(narrative: list | None) -> list[str]:
    """Secciones narrativas persistidas (mismo texto que la ficha), sin reescribir."""
    out: list[str] = []
    for section in narrative or []:
        if not isinstance(section, dict):
            continue
        # La marca técnica INFERIDO se sustituye, no se borra: la calificación
        # (interpretación a partir de titulares, no confirmada) se conserva.
        titulo = str(section.get("titulo") or "").strip()
        if re.search(r"\s*-?\s*INFERIDO$", titulo):
            titulo = re.sub(r"\s*-?\s*INFERIDO$", "", titulo).strip() + " (interpretación, no confirmado)"
        parrafos = [
            re.sub(r"^INFERIDO:\s*", "Interpretación a partir de titulares, no confirmada: ", str(p)).strip()
            for p in (section.get("parrafos") or [])
            if str(p).strip()
        ]
        if not titulo or not parrafos:
            continue
        out.append(f"### {titulo}")
        # Cada párrafo es un párrafo: con salto simple se fusionaban en uno
        # solo en Markdown y salían pegados en el PDF. Las pistas «Evidencia»
        # consecutivas siguen juntas (una lista, no párrafos separados).
        primero = True
        prev_evidencia = False
        for parrafo in parrafos:
            es_evidencia = parrafo.startswith("Evidencia ")
            if not primero and not (es_evidencia and prev_evidencia):
                out.append("")
            out.append(f"- {parrafo}" if es_evidencia else parrafo)
            primero = False
            prev_evidencia = es_evidencia
        out.append("")
    return out


def _money(value, currency: str | None) -> str:
    """Valor por acción en la divisa del listado, como la ficha (thesisMoney).

    Nunca el símbolo $ a secas: para una acción en EUR seria una cifra
    inventada. Sin cifra, «pendiente».
    """
    return money_thesis(float(value), currency) if value is not None else "pendiente"


_ENGLISH_LABELS: dict[str, str] = {
    "changes_requested": "changes requested",
    "draft_failed_audit": "draft (audit not passed)",
    "incomplete_price": "incomplete price",
    "insufficient_data": "insufficient data",
}


def _english_label(value: str | None) -> str:
    """Rating/estado guardado (clave inglesa) legible en ingles."""
    key = (value or "").strip()
    if not key:
        return "n/a"
    return _ENGLISH_LABELS.get(key, key.replace("_", " "))


def build_memo_markdown(
    db: Session,
    company: Company,
    thesis: ThesisVersion,
    *,
    stale: bool = False,
    latest_data_at: datetime | None = None,
    draft: bool = False,
    isolated: bool = False,
    language: str = "es",
) -> str:
    """``draft=True``: memo de un borrador sin publicar, por lista blanca.

    Solo cabecera sin veredicto, catalizadores, criterios de invalidacion y
    calidad de la evidencia. Sin rating, hipotesis, resumen, valoracion,
    secciones ni fuentes: pueden llevar cifras o veredicto que la ficha oculta.
    """
    reason = thesis_withheld_reason(db, thesis)
    if reason and language == "en":
        return (
            f"# Thesis memo - {company.ticker}\n\n"
            f"{archived_thesis_notice(thesis, reason, language)}\n\n"
            "The stored original is kept; this document does not publish its archived analysis.\n\n"
            "Informational research document. It is NOT financial advice "
            "or a recommendation to buy or sell.\n"
        )
    if reason:
        return (
            f"# Memo de tesis - {company.ticker}\n\n"
            f"{archived_thesis_notice(thesis, reason)}\n\n"
            "El original persistido se conserva; este documento no publica su análisis archivado.\n\n"
            "Documento informativo de investigación. NO es asesoramiento financiero "
            "ni recomendación de compra o venta.\n"
        )
    sections = list(
        db.scalars(
            select(ThesisSection)
            .where(ThesisSection.thesis_version_id == thesis.id)
            .order_by(ThesisSection.order_index, ThesisSection.id)
        ).all()
    )
    evidence_rows = db.execute(
        select(Claim.statement, ClaimEvidence.source_url, ClaimEvidence.source_tier)
        .join(ClaimEvidence, ClaimEvidence.claim_id == Claim.id)
        .where(
            Claim.thesis_version_id == thesis.id,
            ClaimEvidence.source_url.is_not(None),
            *tenant_filters(db, Claim, ClaimEvidence),
        )
        .limit(30)
    ).all()

    probs = thesis.scenario_probabilities or {}
    # Ingles (Ajustes): solo el andamiaje fijo del memo; el contenido persistido
    # (hipotesis, secciones, catalizadores...) sale en el idioma en que se genero.
    en = language == "en"

    def tr(es: str, english: str) -> str:
        return english if en else es

    def pct(value: float, decimals: int = 1) -> str:
        return f"{value * 100:.{decimals}f}%" if en else percent_es(value, decimals=decimals)

    def money(value) -> str:
        return "pending" if en and value is None else _money(value, company.currency)

    pending = tr("_Pendiente._", "_Pending._")

    def _prob(key: str) -> str:
        value = probs.get(key)
        return pct(float(value), decimals=0) if isinstance(value, (int, float)) else tr("pendiente", "pending")

    lines: list[str] = []
    lines.append(f"# {tr('Memo de tesis', 'Thesis memo')} — {company.ticker} ({company.name or company.ticker})")
    lines.append("")
    if en:
        rating_part = "" if draft else f"rating {_english_label(thesis.rating)} · "
        lines.append(
            f"Version {thesis.version} · status {_english_label(thesis.status)} · {rating_part}"
            f"generated {_fecha_hora_utc(thesis.created_at)} · updated {_fecha_hora_utc(thesis.updated_at)}"
        )
    else:
        rating_part = "" if draft else f"rating {label_es(RATING_ES, thesis.rating)} · "
        lines.append(
            f"Versión {thesis.version} · estado {label_es(STATUS_ES, thesis.status)} · "
            f"{rating_part}"
            f"generada {_fecha_hora_utc(thesis.created_at)} · actualizada {_fecha_hora_utc(thesis.updated_at)}"
        )
    if stale:
        when = fecha_es(latest_data_at) if latest_data_at else tr("desconocida", "unknown")
        lines.append(tr(f"\n> AVISO: tesis potencialmente DESACTUALIZADA: hay datos mas nuevos (hasta {when}).",
                        f"\n> WARNING: thesis possibly OUT OF DATE: there is newer data (up to {when})."))
    lines.append("")

    if not draft and thesis.margin_of_safety is not None:
        convention = (thesis.valuation_basis or {}).get("margin_of_safety_convention")
        if convention == MARGIN_OF_SAFETY_CONVENTION:
            lines.append(tr(
                f"> Convención del margen de seguridad: {MARGIN_OF_SAFETY_FORMULA}; "
                "V es el valor de referencia del modelo y P el precio comparable de esta versión.",
                f"> Margin of safety convention: {MARGIN_OF_SAFETY_FORMULA}; "
                "V is the model's reference value and P the comparable price of this version.",
            ))
        else:
            lines.append(tr(
                "> AVISO: margen de seguridad histórico sin convención de fórmula verificada. "
                "Se conserva la cifra y el texto originales; no se ha recalculado. "
                "No comparar este porcentaje con el margen actual (V - P) / V.",
                "> WARNING: historical margin of safety without a verified formula convention. "
                "The original figure and text are kept; it has not been recalculated. "
                "Do not compare this percentage with the current margin (V - P) / V.",
            ))
        lines.append("")

    if not draft:
        audit = db.scalars(
            select(SourceAudit)
            .where(SourceAudit.thesis_version_id == thesis.id, *tenant_filters(db, SourceAudit))
            .order_by(SourceAudit.id.desc())
            .limit(1)
        ).first()
        if audit is not None and not audit.passed:
            lines.append(tr(
                "> AVISO: la auditoría de fuentes de esta versión NO pasó. La valoración puede estar "
                "incompleta y es solo indicativa, no un veredicto. Correcciones pendientes de la auditoría:",
                "> WARNING: the source audit of this version did NOT pass. The valuation may be "
                "incomplete and is only indicative, not a verdict. Fixes pending from the audit:",
            ))
            for fix in (audit.required_fixes or [])[:5]:
                lines.append(f"> - {fix}")
            lines.append("")
        elif audit is None:
            lines.append(tr("> Sin auditoría de fuentes registrada para esta versión.",
                            "> No source audit recorded for this version."))
            lines.append("")

    if isolated:
        lines.append(tr(
            "> ARTEFACTO DE PRUEBA AISLADA: generada en una transacción con rollback; NO está "
            "persistida, ni publicada ni aprobada.",
            "> ISOLATED TEST ARTIFACT: generated in a rolled-back transaction; it is NOT "
            "stored, published or approved.",
        ))
        lines.append("")
    if not draft and thesis.status != "published":
        lines.append(tr(
            f"> ESTADO: versión en estado «{label_es(STATUS_ES, thesis.status)}», no publicada ni "
            "aprobada. Es una lectura de seguimiento, no un veredicto ni una recomendación.",
            f"> STATUS: version in status «{_english_label(thesis.status)}», not published or "
            "approved. It is a follow-up reading, not a verdict or a recommendation.",
        ))
        lines.append("")

    if draft:
        lines.append(tr(
            "> BORRADOR sin publicar. No incluye veredicto, hipótesis, resumen, "
            "valoración ni secciones de la tesis.",
            "> Unpublished DRAFT. It does not include the verdict, hypothesis, summary, "
            "valuation or sections of the thesis.",
        ))
        lines.append("")
    else:
        same_text = bool(thesis.hypothesis) and (thesis.hypothesis or "").strip() == (
            thesis.executive_summary or ""
        ).strip()
        if same_text:
            # Hipótesis y resumen idénticos: se dice una vez, no dos.
            lines.append(tr("## Hipótesis y resumen ejecutivo", "## Hypothesis and executive summary"))
            lines.append(thesis.executive_summary or pending)
            lines.append("")
        else:
            lines.append(tr("## Hipótesis", "## Hypothesis"))
            lines.append(thesis.hypothesis or pending)
            lines.append("")

            lines.append(tr("## Resumen ejecutivo", "## Executive summary"))
            lines.append(thesis.executive_summary or pending)
            lines.append("")

        lines.append(tr("## Valoración y escenarios", "## Valuation and scenarios"))
        lines.append(tr("| Escenario | Valor | Probabilidad |", "| Scenario | Value | Probability |"))
        lines.append("|---|---|---|")
        lines.append(f"| {tr('Bajista', 'Bear')} | {money(thesis.bear_value)} | {_prob('bear')} |")
        lines.append(f"| Base | {money(thesis.base_value)} | {_prob('base')} |")
        lines.append(f"| {tr('Alcista', 'Bull')} | {money(thesis.bull_value)} | {_prob('bull')} |")
        # El precio guardado es el que usó el modelo al generar la versión,
        # no la cotización de hoy: se rotula como tal, con la fecha de la
        # cotización solo si quedó persistida (nunca una fecha inventada).
        price_as_of = (thesis.valuation_basis or {}).get("price_as_of")
        price_label = tr("Precio del modelo", "Model price") + (
            f" {tr('al', 'as of')} {fecha_es(price_as_of)}" if price_as_of else ""
        )
        lines.append(
            f"\n{price_label}: {money(thesis.current_price)} · {tr('Valor esperado', 'Expected value')}: "
            f"{money(thesis.expected_value)} · {tr('Margen de seguridad', 'Margin of safety')}: "
            + (pct(float(thesis.margin_of_safety)) if thesis.margin_of_safety is not None else tr("pendiente", "pending"))
        )
        lines.append("")

    lines.append(tr("## Catalizadores", "## Catalysts"))
    catalysts = thesis.catalysts or []
    if catalysts:
        for item in catalysts:
            if isinstance(item, dict):
                label = item.get("label") or item.get("title") or item.get("name") or str(item)
                when = item.get("date") or item.get("when") or ""
                lines.append(f"- {label}" + (f" ({when})" if when else ""))
            else:
                lines.append(f"- {item}")
    else:
        lines.append(pending)
    lines.append("")

    lines.append(tr("## Criterios de invalidación", "## Invalidation criteria"))
    criteria = thesis.invalidation_criteria or []
    if criteria:
        for item in criteria:
            lines.append(f"- {item}")
    else:
        lines.append(pending)
    lines.append("")

    lines.append(tr("## Calidad de la evidencia", "## Evidence quality"))
    lines.append(tr(
        f"Confianza de datos {thesis.data_confidence_score}/100 · cobertura de fuentes "
        f"{thesis.source_coverage_score}/100 · red-team {thesis.red_team_score}/100 · "
        f"riesgo de valoración {thesis.valuation_risk_score}/100",
        f"Data confidence {thesis.data_confidence_score}/100 · source coverage "
        f"{thesis.source_coverage_score}/100 · red-team {thesis.red_team_score}/100 · "
        f"valuation risk {thesis.valuation_risk_score}/100",
    ))
    lines.append("")

    if not draft:
        # La aprobación por Telegram es un registro operativo, no análisis.
        sections = [sec for sec in sections if sec.title != APPROVAL_SECTION_TITLE]
        narrative = _narrative_lines(thesis.narrative_sections)
        if narrative:
            lines.append(tr("## Análisis narrativo", "## Narrative analysis"))
            lines.extend(narrative)

        if sections:
            lines.append(tr("## Secciones", "## Sections"))
            for section in sections:
                lines.append(f"### {section.title}")
                lines.append(section.body or pending)
                lines.append("")

        analysis = _full_analysis_lines(thesis.thesis_markdown or "")
        if any(item.strip() for item in analysis):
            lines.append(tr("## Análisis completo", "## Full analysis"))
            origin = (
                tr("Texto de la tesis de una ejecución aislada (no persistida)",
                   "Thesis text from an isolated run (not stored)")
                if isolated
                else tr("Texto de la tesis persistida (misma versión que la ficha)",
                        "Stored thesis text (same version as the company page)")
            )
            lines.append(tr(
                f"{origin}. Descriptivo: no garantiza que cifras, fuentes o inferencias "
                "estén validadas.",
                f"{origin}. Descriptive: it does not guarantee that figures, sources or inferences "
                "are validated.",
            ))
            lines.append("")
            lines.extend(analysis)
            lines.append("")

        if evidence_rows:
            lines.append(tr("## Fuentes", "## Sources"))
            for statement, url, tier in evidence_rows:
                short = (statement or "")[:110].replace("\n", " ")
                lines.append(f"- [{tier}] {short} — {url}")
            lines.append("")

    lines.append("---")
    if isolated:
        lines.append(tr(
            f"Generado {_fecha_hora_utc(datetime.now(UTC))} desde una ejecución aislada "
            "(rollback, no persistida; sin fingerprint persistido).",
            f"Generated {_fecha_hora_utc(datetime.now(UTC))} from an isolated run "
            "(rolled back, not stored; no stored fingerprint).",
        ))
    else:
        lines.append(tr(
            f"Generado {_fecha_hora_utc(datetime.now(UTC))} desde la versión persistida "
            f"{thesis.version} (fingerprint {thesis.input_fingerprint or 'n/a'}).",
            f"Generated {_fecha_hora_utc(datetime.now(UTC))} from stored version "
            f"{thesis.version} (fingerprint {thesis.input_fingerprint or 'n/a'}).",
        ))
    lines.append(tr(
        "Documento informativo de investigación. NO es asesoramiento financiero "
        "ni recomendación de compra o venta.",
        "Informational research document. It is NOT financial advice "
        "or a recommendation to buy or sell.",
    ))
    return "\n".join(lines) + "\n"
