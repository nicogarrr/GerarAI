"""Memo Markdown descargable de una tesis (solo lectura de datos persistidos).

Nunca inventa contenido: cada seccion sale de ThesisVersion/ThesisSection/
ClaimEvidence tal cual esta persistida; lo que falta se marca como
"pendiente". Siempre cierra con el aviso de que no es asesoramiento
financiero.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Claim, ClaimEvidence, Company, ThesisSection, ThesisVersion
from app.services.memo_text_es import RATING_ES, STATUS_ES, label_es, percent_es
from app.services.thesis_approval_service import APPROVAL_SECTION_TITLE


def _full_analysis_lines(markdown: str) -> list[str]:
    """Cuerpo del análisis persistido (thesis_markdown) listo para el memo.

    Se quita el título propio y se baja un nivel cada encabezado para que cuelgue
    de «Análisis completo». Es el mismo texto que ve la ficha: no se reescribe ni
    se rellena nada.
    """
    out: list[str] = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            continue
        if line.startswith("### "):
            out.append(f"**{line[4:]}**")
        elif line.startswith("## "):
            out.append(f"### {line[3:]}")
        else:
            out.append(line)
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
        lines.append(f"\n> ⚠ Tesis potencialmente DESACTUALIZADA: hay datos mas nuevos (hasta {when}).")
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
                "Texto íntegro de la tesis persistida, con las cifras de entrada, su fuente y "
                "periodo, supuestos, datos pendientes y procedencia. Lo que falta aparece "
                "marcado como pendiente."
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
