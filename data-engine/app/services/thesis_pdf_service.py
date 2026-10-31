"""Servicio de exportación de tesis de inversión a formato PDF.

Fulfills: VAL-DATA-005 (y satisface VAL-DATA-001)
Expected Behavior:
- PDF generado con biblioteca estándar (matplotlib/pypdf) 100% en Python (EUR0)
- Diseño profesional con branding GerarAI y texto visible en español
- Incluye resumen ejecutivo, composición de cartera/posiciones y secciones de análisis
- Generación de descarga en <5 segundos
- Sanitización rigurosa de nombres de archivo contra inyección de comandos o cabeceras
"""

from __future__ import annotations

import io
import re
import textwrap
import unicodedata
from dataclasses import dataclass, field

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Claim, Portfolio, Position, ThesisSection, ThesisVersion
from app.services.company_resolver import resolve_company
from app.services.thesis_publication_gate import archived_thesis_notice, thesis_withheld_reason


@dataclass
class PdfSection:
    """Sección de texto de la tesis."""

    title: str
    body: str = ""


@dataclass
class HoldingItem:
    """Activo o posición en cartera. price/value a None = sin dato verificado (se muestra N/D)."""

    ticker: str
    shares: float
    price: float | None
    value: float | None
    weight: str
    currency: str = ""
    price_is_cost: bool = False
    value_currency: str = ""


@dataclass
class ThesisPdfData:
    """Estructura de datos para generar el PDF de una tesis o cartera."""

    ticker: str = ""
    company_name: str = ""
    portfolio_name: str = ""
    version: int = 1
    # rating=None -> sin insignia (los informes de cartera no tienen calificación)
    rating: str | None = None
    status: str = "draft"
    generated_on: str = ""
    executive_summary: str = ""
    provenance: str = ""
    sections: list[PdfSection] = field(default_factory=list)
    holdings: list[HoldingItem] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)


def sanitize_pdf_filename(raw_name: str, fallback: str = "gerarai-tesis") -> str:
    """Sanitiza el nombre de archivo eliminando caracteres peligrosos (SSRF/Command Injection)."""
    normalized = unicodedata.normalize("NFKD", raw_name).encode("ascii", "ignore").decode("ascii")
    # Solo alfanuméricos, guiones y puntos
    clean = re.sub(r"[^a-zA-Z0-9_\.-]", "-", normalized)
    clean = re.sub(r"-+", "-", clean).strip("-.")
    return clean[:64] or fallback


def _new_page() -> tuple[plt.Figure, plt.Axes]:
    """Página A4 con lienzo fijo 0-1.

    Sin límites explícitos, matplotlib autoescala los ejes con los artistas
    (rectángulo de cabecera, líneas separadoras): la cabecera acababa ocupando
    media página y los textos por debajo del separador salían del área visible.
    """
    fig = plt.figure(figsize=(8.27, 11.69), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    return fig, ax


def build_thesis_pdf(data: ThesisPdfData) -> bytes:
    """Construye un documento PDF vectorial de alta calidad con branding GerarAI."""
    buf = io.BytesIO()

    # Formato A4 estándar
    with PdfPages(buf) as pdf:
        # Página 1: Portada, Resumen Ejecutivo y Cartera/Activos
        fig1, ax1 = _new_page()

        # Cabecera superior con branding oscuro
        header_rect = plt.Rectangle((0, 0.88), 1, 0.12, facecolor="#0f172a", edgecolor="none")
        ax1.add_patch(header_rect)

        ax1.text(0.06, 0.95, "GERAR AI", fontsize=20, weight="bold", color="#38bdf8", va="center")
        ax1.text(
            0.06,
            0.91,
            "INFORME DE TESIS DE INVERSIÓN Y CARTERA",
            fontsize=10,
            weight="bold",
            color="#94a3b8",
            va="center",
        )
        date_str = data.generated_on or "Fecha no especificada"
        ax1.text(0.94, 0.93, f"Fecha: {date_str}", fontsize=9, color="#94a3b8", ha="right", va="center")

        # Título principal
        title_entity = data.company_name or data.portfolio_name or data.ticker or "Informe de Inversión"
        if data.ticker and data.company_name:
            main_title = f"{data.company_name} ({data.ticker})"
        elif data.portfolio_name:
            main_title = f"Cartera: {data.portfolio_name}"
        else:
            main_title = title_entity

        ax1.text(0.06, 0.83, main_title, fontsize=17, weight="bold", color="#0f172a", va="center")

        # Insignia de Calificación (solo si la tesis tiene rating; un informe
        # de cartera nunca inventa una calificación)
        meta_parts = [f"Versión v{data.version}"]
        if data.status:
            meta_parts.append(f"Estado: {data.status.upper()}")
        if data.provenance:
            meta_parts.append(f"Procedencia: {data.provenance}")
        meta_x = 0.06
        if data.rating:
            rating_map = {
                "buy": ("#16a34a", "COMPRA"),
                "strong_buy": ("#15803d", "COMPRA FUERTE"),
                "hold": ("#d97706", "MANTENER"),
                "watch": ("#2563eb", "SEGUIMIENTO"),
                "sell": ("#dc2626", "VENTA"),
                "insufficient_data": ("#64748b", "DATOS INSUFICIENTES"),
            }
            badge_bg, badge_lbl = rating_map.get(data.rating.lower(), ("#475569", data.rating.upper()))
            badge_rect = plt.Rectangle((0.06, 0.77), 0.22, 0.035, facecolor=badge_bg, edgecolor="none")
            ax1.add_patch(badge_rect)
            ax1.text(0.17, 0.787, badge_lbl, fontsize=9.5, weight="bold", color="white", ha="center", va="center")
            meta_x = 0.31
        ax1.text(
            meta_x,
            0.787,
            " · ".join(meta_parts),
            fontsize=9,
            color="#64748b",
            va="center",
        )

        # Línea separadora
        ax1.plot([0.06, 0.94], [0.75, 0.75], color="#e2e8f0", lw=1.5)

        # Resumen Ejecutivo
        ax1.text(0.06, 0.72, "Resumen Ejecutivo", fontsize=13, weight="bold", color="#1e293b", va="top")
        summary_text = data.executive_summary.strip() or "Sin resumen ejecutivo disponible."
        wrapped_summary = textwrap.fill(summary_text, width=88)
        ax1.text(0.06, 0.69, wrapped_summary, fontsize=9.5, color="#334155", va="top", linespacing=1.4)

        current_y = 0.52
        # Tabla de Cartera si existen activos
        if data.holdings:
            ax1.text(0.06, current_y, "Composición de la Cartera", fontsize=13, weight="bold", color="#1e293b", va="top")
            current_y -= 0.03
            table_data = [["Activo", "Títulos", "Precio", "Valor", "Peso"]]

            def _fmt_money(v: float | None, ccy: str, is_cost: bool = False) -> str:
                if v is None:
                    return "n/d"
                lbl = f"{v:,.2f} {ccy}".strip()
                return lbl + (" *" if is_cost else "")

            for h in data.holdings[:6]:
                price_lbl = _fmt_money(h.price, h.currency, h.price_is_cost)
                value_lbl = _fmt_money(h.value, h.value_currency)
                table_data.append([h.ticker, f"{h.shares:,.2f}", price_lbl, value_lbl, h.weight])

            tbl = ax1.table(
                cellText=table_data,
                colWidths=[0.16, 0.16, 0.22, 0.24, 0.10],
                loc="center",
                bbox=[0.06, current_y - 0.18, 0.88, 0.18],
            )
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(8.5)
            for (r, _c), cell in tbl.get_celld().items():
                cell.set_edgecolor("#cbd5e1")
                if r == 0:
                    cell.set_facecolor("#f1f5f9")
                    cell.set_text_props(weight="bold", color="#1e293b")
                else:
                    cell.set_facecolor("#ffffff" if r % 2 == 1 else "#f8fafc")
                    cell.set_text_props(color="#334155")
            current_y -= 0.20
            if any(h.price_is_cost for h in data.holdings[:6]):
                ax1.text(
                    0.06,
                    current_y,
                    "* Valorado al coste de adquisición por falta de cotización disponible.",
                    fontsize=7.5,
                    color="#64748b",
                    va="top",
                )
            current_y -= 0.02

        # Primera sección si hay espacio
        if data.sections:
            sec0 = data.sections[0]
            ax1.text(0.06, current_y, sec0.title, fontsize=12, weight="bold", color="#1e293b", va="top")
            current_y -= 0.025
            wrapped_sec = textwrap.fill(sec0.body[:500], width=88)
            ax1.text(0.06, current_y, wrapped_sec, fontsize=9, color="#334155", va="top", linespacing=1.35)

        # Pie de página
        ax1.text(0.06, 0.03, "GerarAI — Informe de Análisis Financiero Confidencial", fontsize=8, color="#94a3b8", va="bottom")
        ax1.text(0.94, 0.03, "Página 1 de 2", fontsize=8, color="#94a3b8", ha="right", va="bottom")

        pdf.savefig(fig1)
        plt.close(fig1)

        # Página 2: Análisis Detallado, Riesgos y Evidencias
        fig2, ax2 = _new_page()

        # Mini cabecera
        ax2.plot([0.06, 0.94], [0.94, 0.94], color="#0f172a", lw=2)
        ax2.text(0.06, 0.96, f"GerarAI · {main_title} — Análisis Detallado", fontsize=10, weight="bold", color="#0f172a")
        ax2.text(0.94, 0.96, f"v{data.version}", fontsize=9, color="#64748b", ha="right")

        y2 = 0.90
        # Secciones siguientes (la primera ya está en la página 1)
        for sec in data.sections[1:4]:
            ax2.text(0.06, y2, sec.title, fontsize=12, weight="bold", color="#1e293b", va="top")
            y2 -= 0.025
            wrapped = textwrap.fill(sec.body, width=88)
            ax2.text(0.06, y2, wrapped, fontsize=9, color="#334155", va="top", linespacing=1.35)
            lines_c = len(wrapped.split("\n"))
            y2 -= (lines_c * 0.018 + 0.03)
            if y2 < 0.25:
                break

        # Citas y fuentes
        if data.citations and y2 > 0.16:
            ax2.text(0.06, y2, "Fuentes y Evidencias Consultadas", fontsize=11, weight="bold", color="#1e293b", va="top")
            y2 -= 0.025
            for cit in data.citations[:4]:
                ax2.text(0.08, y2, f"• {cit[:110]}", fontsize=8, color="#475569", va="top")
                y2 -= 0.02

        # Aviso legal en español (es-ES)
        disclaimer_box = plt.Rectangle((0.06, 0.06), 0.88, 0.06, facecolor="#f8fafc", edgecolor="#e2e8f0")
        ax2.add_patch(disclaimer_box)
        disclaimer_text = (
            "Aviso legal: Este informe tiene fines exclusivamente informativos y formativos. No constituye "
            "asesoramiento financiero personalizado ni recomendación de inversión. Rentabilidades pasadas no "
            "garantizan rendimientos futuros."
        )
        ax2.text(0.08, 0.095, textwrap.fill(disclaimer_text, width=95), fontsize=7.5, color="#64748b", va="center")

        # Pie de página
        ax2.text(0.06, 0.03, "GerarAI — Informe de Análisis Financiero Confidencial", fontsize=8, color="#94a3b8", va="bottom")
        ax2.text(0.94, 0.03, "Página 2 de 2", fontsize=8, color="#94a3b8", ha="right", va="bottom")

        pdf.savefig(fig2)
        plt.close(fig2)

    return buf.getvalue()


def export_thesis_pdf_for_ticker(db: Session, ticker: str) -> tuple[bytes, str]:
    """Genera el PDF para un ticker específico a partir de la última versión de su tesis."""
    company = resolve_company(db, ticker)
    if not company:
        raise ValueError(f"No existe la empresa con ticker {ticker}")

    thesis = db.scalar(
        select(ThesisVersion)
        .where(ThesisVersion.company_id == company.id)
        .order_by(desc(ThesisVersion.version))
        .limit(1)
    )
    if not thesis:
        raise ValueError(f"No hay ninguna versión de tesis para {company.ticker}")

    sections = db.scalars(
        select(ThesisSection)
        .where(ThesisSection.thesis_version_id == thesis.id)
        .order_by(ThesisSection.order_index)
    ).all()

    claims = db.scalars(
        select(Claim)
        .options(selectinload(Claim.evidence))
        .where(Claim.thesis_version_id == thesis.id)
    ).all()

    reason = thesis_withheld_reason(db, thesis)
    pdf_sections = [] if reason else [PdfSection(title=s.title, body=s.body or "") for s in sections]
    citations: list[str] = []
    tiers: set[str] = set()
    has_evidence = False
    if not reason:
        for c in claims:
            evidences = list(c.evidence or [])
            if evidences:
                has_evidence = True
                tiers.update((e.source_tier or "unknown") for e in evidences)
                first_with_url = next((e for e in evidences if e.source_url), None)
                if first_with_url is not None:
                    citations.append(f"{c.statement} — fuente: {first_with_url.source_url}")
                else:
                    citations.append(f"{c.statement} — fuente registrada sin enlace")
            else:
                citations.append(f"{c.statement} — sin fuente registrada")

    if not claims or not has_evidence:
        provenance = "SIN FUENTES REGISTRADAS"
    elif tiers <= {"primary", "tier_primary", "official", "regulatory"}:
        provenance = "FUENTES OFICIALES"
    else:
        provenance = "MIXTA (oficiales y secundarias)"

    data = ThesisPdfData(
        ticker=company.ticker,
        company_name=company.name or "",
        version=thesis.version,
        rating="insufficient_data" if reason else thesis.rating or "watch",
        status=thesis.status or "draft",
        generated_on=thesis.updated_at.date().isoformat() if thesis.updated_at else "",
        executive_summary=archived_thesis_notice(thesis, reason) if reason else thesis.executive_summary or "",
        provenance=provenance,
        sections=pdf_sections,
        citations=citations,
    )

    filename = f"gerarai-tesis-{sanitize_pdf_filename(company.ticker)}-v{thesis.version}.pdf"
    content = build_thesis_pdf(data)
    return content, filename


def export_portfolio_pdf_report(db: Session, portfolio_id: int) -> tuple[bytes, str]:
    """Genera el informe PDF de una cartera incluyendo activos, ponderaciones y tesis global."""
    portfolio = db.scalar(select(Portfolio).where(Portfolio.id == portfolio_id))
    if not portfolio:
        raise ValueError(f"No se encontró la cartera con ID {portfolio_id}")

    positions = (
        db.scalars(
            select(Position)
            .options(selectinload(Position.company))
            .where(Position.portfolio_id == portfolio_id)
        ).all()
    )

    base_ccy = (portfolio.base_currency or "EUR").upper()
    # quantity/market_price/average_cost son NOT NULL en positions (Numeric, default 0).
    # Una posicion con valoracion en suspenso (split sin precio verificado, coste
    # "Realized P/L not ready" de IBKR, etc.) NO tiene precio fiable: se muestra
    # n/d y se excluye del total, nunca se inventa un 0.
    holdings: list[HoldingItem] = []
    rows: list[tuple] = []
    for p in positions:
        qty = float(p.quantity)
        held = bool(p.valuation_hold_reason)
        market_px = float(p.market_price)
        cost_px = float(p.average_cost)
        price_is_cost = not held and not market_px and bool(cost_px)
        px = None if held else (market_px if market_px else cost_px)
        native_ccy = (p.currency or "").upper()
        # Valor en divisa base si el libro lo tiene; si no, valor nativo estimado.
        base_val = None if held else (float(p.market_value_base) if p.market_value_base is not None else None)
        val = None if px is None else (base_val if base_val is not None else qty * px)
        rows.append((p, qty, px, price_is_cost, native_ccy, val, base_val is not None))

    # Pesos solo comparables cuando todas las valoraciones comparten divisa.
    valued_rows = [r for r in rows if r[5] is not None]
    all_base = bool(valued_rows) and all(r[6] for r in valued_rows)
    same_ccy = len({(base_ccy if r[6] else r[4]) for r in valued_rows}) <= 1
    total_val = sum(r[5] for r in valued_rows) if (all_base or same_ccy) else 0.0
    for p, qty, px, price_is_cost, native_ccy, val, is_base in rows:
        weight = "n/d" if val is None or total_val <= 0 else f"{(val / total_val * 100):.1f}%"
        ticker_name = p.company.ticker if p.company else f"ACT-{p.company_id}"
        holdings.append(
            HoldingItem(
                ticker=ticker_name,
                shares=qty,
                price=px,
                value=val,
                weight=weight,
                currency=native_ccy,
                price_is_cost=price_is_cost,
                value_currency=base_ccy if is_base else native_ccy,
            )
        )

    cost_rows = sum(1 for r in rows if r[3])
    held_rows = sum(1 for r in rows if r[5] is None)
    composition_body = ""
    if rows:
        if total_val > 0:
            top = sorted(valued_rows, key=lambda r: r[5], reverse=True)[:3]
            lines = []
            for p, _qty, _px, _pc, _ccy, val, _ib in top:
                share = f"{(val / total_val * 100):.1f}%"
                name = p.company.ticker if p.company else f"ACT-{p.company_id}"
                lines.append(f"{name}: {share}")
            composition_body = "Mayores posiciones por peso estimado: " + ", ".join(lines) + "."
        else:
            # Divisas mezcladas sin valor consolidado: no se ordenan por peso.
            names = [p.company.ticker if p.company else f"ACT-{p.company_id}" for p, *_r in rows]
            composition_body = (
                "Posiciones: " + ", ".join(names) + ". "
                "Pesos no calculables: hay posiciones en divisas distintas sin valor consolidado en divisa base."
            )

    limitations: list[str] = []
    if cost_rows:
        limitations.append(f"{cost_rows} posición(es) valorada(s) al coste de adquisición por falta de cotización")
    if held_rows:
        limitations.append(f"{held_rows} posición(es) con valoración en suspenso (sin precio verificado): n/d y excluida(s) del total")
    ccys = sorted({r[4] for r in rows if r[4]})
    if len(ccys) > 1:
        limitations.append("posiciones en varias divisas (" + ", ".join(ccys) + ")")
    if rows and not all_base:
        limitations.append("sin valor de mercado consolidado en divisa base para alguna posición")
    limitations_body = (
        "Limitaciones de este informe: " + "; ".join(limitations) + "."
        if limitations
        else "Todas las posiciones tienen valor de mercado consolidado en divisa base."
    )
    # Divisa del total: la común a todas las valoraciones (base si hay valor
    # consolidado; la nativa compartida si no), nunca la base por defecto.
    total_ccy = base_ccy if all_base else (ccys[0] if len(ccys) == 1 else "")
    summary = f"Informe consolidado de la cartera {portfolio.name}. Consta de {len(positions)} posiciones activas"
    if total_val > 0 and total_ccy:
        summary += f" con un valor total estimado de {total_val:,.2f} {total_ccy}"
    summary += "."

    data = ThesisPdfData(
        portfolio_name=portfolio.name,
        version=1,
        rating=None,
        status="",
        generated_on=portfolio.created_at.date().isoformat() if portfolio.created_at else "",
        executive_summary=summary,
        provenance="DATOS DE LA CARTERA REGISTRADA",
        holdings=holdings,
        sections=[
            PdfSection(title="1. Composición", body=composition_body or "Cartera sin posiciones registradas."),
            PdfSection(title="2. Datos y limitaciones", body=limitations_body),
        ],
    )

    filename = f"gerarai-cartera-{sanitize_pdf_filename(portfolio.name)}.pdf"
    content = build_thesis_pdf(data)
    return content, filename
