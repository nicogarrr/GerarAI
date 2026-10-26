"""Memo Markdown descargable de una tesis (solo lectura de datos persistidos).

Nunca inventa contenido: cada seccion sale de ThesisVersion/ThesisSection/
ClaimEvidence tal cual esta persistida; lo que falta se marca como
"pendiente". Siempre cierra con el aviso de que no es asesoramiento
financiero.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Claim, ClaimEvidence, Company, SourceAudit, ThesisSection, ThesisVersion
from app.services.memo_text_es import RATING_ES, STATUS_ES, label_es, percent_es
from app.services.thesis_approval_service import APPROVAL_SECTION_TITLE


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
        # Marca interna ("publicable=True") que contradice el estado del memo y
        # listas largas de ids de hechos: siguen en la ficha, no en el documento.
        line = re.sub(r"\s+publicable=(?:True|False|None)", "", line)
        line = re.sub(r"\s*\(\d{5,}(?:, \d{5,})*\)", "", line)
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
        titulo = re.sub(r"\s*-?\s*INFERIDO$", "", str(section.get("titulo") or "")).strip()
        parrafos = [
            re.sub(r"^INFERIDO:\s*", "", str(p)).strip()
            for p in (section.get("parrafos") or [])
            if str(p).strip()
        ]
        if not titulo or not parrafos:
            continue
        out.append(f"### {titulo}")
        for parrafo in parrafos:
            out.append(f"- {parrafo}" if parrafo.startswith("Evidencia ") else parrafo)
        out.append("")
    return out


def _money(value) -> str:
    return f"${float(value):,.2f}" if value is not None else "pendiente"


def build_memo_markdown(
    db: Session,
    company: Company,
    thesis: ThesisVersion,
    *,
    stale: bool = False,
    latest_data_at: datetime | None = None,
    draft: bool = False,
) -> str:
    """``draft=True``: memo de un borrador sin publicar, por lista blanca.

    Solo cabecera sin veredicto, catalizadores, criterios de invalidacion y
    calidad de la evidencia. Sin rating, hipotesis, resumen, valoracion,
    secciones ni fuentes: pueden llevar cifras o veredicto que la ficha oculta.
    """
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

    def _prob(key: str) -> str:
        value = probs.get(key)
        return percent_es(float(value), decimals=0) if isinstance(value, (int, float)) else "pendiente"

    lines: list[str] = []
    lines.append(f"# Memo de tesis — {company.ticker} ({company.name or company.ticker})")
    lines.append("")
    rating_part = "" if draft else f"rating {label_es(RATING_ES, thesis.rating)} · "
    lines.append(
        f"Versión {thesis.version} · estado {label_es(STATUS_ES, thesis.status)} · "
        f"{rating_part}"
        f"generada {thesis.created_at:%Y-%m-%d %H:%M} UTC · actualizada {thesis.updated_at:%Y-%m-%d %H:%M} UTC"
    )
    if stale:
        when = f"{latest_data_at:%Y-%m-%d}" if latest_data_at else "desconocida"
        lines.append(f"\n> AVISO: tesis potencialmente DESACTUALIZADA: hay datos mas nuevos (hasta {when}).")
    lines.append("")

    if not draft:
        audit = db.scalars(
            select(SourceAudit)
            .where(SourceAudit.thesis_version_id == thesis.id, *tenant_filters(db, SourceAudit))
            .order_by(SourceAudit.id.desc())
            .limit(1)
        ).first()
        if audit is not None and not audit.passed:
            lines.append(
                "> AVISO: la auditoría de fuentes de esta versión NO pasó. La valoración puede estar "
                "incompleta y es solo indicativa, no un veredicto. Correcciones pendientes de la auditoría:"
            )
            for fix in (audit.required_fixes or [])[:5]:
                lines.append(f"> - {fix}")
            lines.append("")
        elif audit is None:
            lines.append("> Sin auditoría de fuentes registrada para esta versión.")
            lines.append("")

    if not draft and thesis.status != "published":
        lines.append(
            f"> ESTADO: versión en estado «{label_es(STATUS_ES, thesis.status)}», no publicada ni "
            "aprobada. Es una lectura de seguimiento, no un veredicto ni una recomendación."
        )
        lines.append("")

    if draft:
        lines.append(
            "> BORRADOR sin publicar. No incluye veredicto, hipótesis, resumen, "
            "valoración ni secciones de la tesis."
        )
        lines.append("")
    else:
        same_text = bool(thesis.hypothesis) and (thesis.hypothesis or "").strip() == (
            thesis.executive_summary or ""
        ).strip()
        if same_text:
            # Hipótesis y resumen idénticos: se dice una vez, no dos.
            lines.append("## Hipótesis y resumen ejecutivo")
            lines.append(thesis.executive_summary or "_Pendiente._")
            lines.append("")
        else:
            lines.append("## Hipótesis")
            lines.append(thesis.hypothesis or "_Pendiente._")
            lines.append("")

            lines.append("## Resumen ejecutivo")
            lines.append(thesis.executive_summary or "_Pendiente._")
            lines.append("")

        lines.append("## Valoración y escenarios")
        lines.append("| Escenario | Valor | Probabilidad |")
        lines.append("|---|---|---|")
        lines.append(f"| Bajista | {_money(thesis.bear_value)} | {_prob('bear')} |")
        lines.append(f"| Base | {_money(thesis.base_value)} | {_prob('base')} |")
        lines.append(f"| Alcista | {_money(thesis.bull_value)} | {_prob('bull')} |")
        lines.append(
            f"\nPrecio actual: {_money(thesis.current_price)} · Valor esperado: "
            f"{_money(thesis.expected_value)} · Margen de seguridad: "
            + (percent_es(float(thesis.margin_of_safety)) if thesis.margin_of_safety is not None else "pendiente")
        )
        lines.append("")

    lines.append("## Catalizadores")
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
        lines.append("_Pendiente._")
    lines.append("")

    lines.append("## Criterios de invalidación")
    criteria = thesis.invalidation_criteria or []
    if criteria:
        for item in criteria:
            lines.append(f"- {item}")
    else:
        lines.append("_Pendiente._")
    lines.append("")

    lines.append("## Calidad de la evidencia")
    lines.append(
        f"Confianza de datos {thesis.data_confidence_score}/100 · cobertura de fuentes "
        f"{thesis.source_coverage_score}/100 · red-team {thesis.red_team_score}/100 · "
        f"riesgo de valoración {thesis.valuation_risk_score}/100"
    )
    lines.append("")

    if not draft:
        # La aprobación por Telegram es un registro operativo, no análisis.
        sections = [sec for sec in sections if sec.title != APPROVAL_SECTION_TITLE]
        narrative = _narrative_lines(thesis.narrative_sections)
        if narrative:
            lines.append("## Análisis narrativo")
            lines.extend(narrative)

        if sections:
            lines.append("## Secciones")
            for section in sections:
                lines.append(f"### {section.title}")
                lines.append(section.body or "_Pendiente._")
                lines.append("")

        analysis = _full_analysis_lines(thesis.thesis_markdown or "")
        if any(item.strip() for item in analysis):
            lines.append("## Análisis completo")
            lines.append(
                "Texto de la tesis persistida (misma versión que la ficha). Descriptivo: no "
                "garantiza que cifras, fuentes o inferencias estén validadas."
            )
            lines.append("")
            lines.extend(analysis)
            lines.append("")

        if evidence_rows:
            lines.append("## Fuentes")
            for statement, url, tier in evidence_rows:
                short = (statement or "")[:110].replace("\n", " ")
                lines.append(f"- [{tier}] {short} — {url}")
            lines.append("")

    lines.append("---")
    lines.append(
        f"Generado {datetime.now(UTC):%Y-%m-%d %H:%M} UTC desde la versión persistida "
        f"{thesis.version} (fingerprint {thesis.input_fingerprint or 'n/a'})."
    )
    lines.append(
        "Documento informativo de investigación. NO es asesoramiento financiero "
        "ni recomendación de compra o venta."
    )
    return "\n".join(lines) + "\n"
