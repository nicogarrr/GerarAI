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
    """Activo o posición en cartera."""

    ticker: str
    shares: float
    price: float
    value: float
    weight: str


@dataclass
class ThesisPdfData:
    """Estructura de datos para generar el PDF de una tesis o cartera."""

    ticker: str = ""
    company_name: str = ""
    portfolio_name: str = ""
    version: int = 1
    rating: str = "watch"
    status: str = "draft"
    generated_on: str = ""
    executive_summary: str = ""
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


def build_thesis_pdf(data: ThesisPdfData) -> bytes:
    """Construye un documento PDF vectorial de alta calidad con branding GerarAI."""
    buf = io.BytesIO()

    # Formato A4 estándar
    with PdfPages(buf) as pdf:
        # Página 1: Portada, Resumen Ejecutivo y Cartera/Activos
        fig1 = plt.figure(figsize=(8.27, 11.69), dpi=100)
        ax1 = fig1.add_axes([0, 0, 1, 1])
        ax1.set_axis_off()

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

        # Insignia de Calificación
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

        ax1.text(
            0.31,
            0.787,
            f"Versión v{data.version} · Estado: {data.status.upper()} · Procedencia: OFICIAL",
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
            table_data = [["Activo", "Títulos", "Precio (€)", "Valor (€)", "Peso"]]
            for h in data.holdings[:6]:
                table_data.append([h.ticker, f"{h.shares:,.2f}", f"{h.price:,.2f}", f"{h.value:,.2f}", h.weight])

            tbl = ax1.table(
                cellText=table_data,
                colWidths=[0.18, 0.18, 0.18, 0.20, 0.14],
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
            current_y -= 0.22

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
        fig2 = plt.figure(figsize=(8.27, 11.69), dpi=100)
        ax2 = fig2.add_axes([0, 0, 1, 1])
        ax2.set_axis_off()

        # Mini cabecera
        ax2.plot([0.06, 0.94], [0.94, 0.94], color="#0f172a", lw=2)
        ax2.text(0.06, 0.96, f"GerarAI · {main_title} — Análisis Detallado", fontsize=10, weight="bold", color="#0f172a")
        ax2.text(0.94, 0.96, f"v{data.version}", fontsize=9, color="#64748b", ha="right")

        y2 = 0.90
        # Secciones siguientes
        sections_to_show = data.sections[1:] if len(data.sections) > 1 else data.sections
        for sec in sections_to_show[:3]:
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
        select(Claim).where(Claim.thesis_version_id == thesis.id)
    ).all()

    reason = thesis_withheld_reason(db, thesis)
    pdf_sections = [] if reason else [PdfSection(title=s.title, body=s.body or "") for s in sections]
    citations = []
    if not reason:
        for c in claims:
            citations.append(f"{c.statement} [claim:{c.id}]")

    data = ThesisPdfData(
        ticker=company.ticker,
        company_name=company.name or "",
        version=thesis.version,
        rating="insufficient_data" if reason else thesis.rating or "watch",
        status=thesis.status or "draft",
        generated_on=thesis.updated_at.date().isoformat() if thesis.updated_at else "",
        executive_summary=archived_thesis_notice(thesis, reason) if reason else thesis.executive_summary or "",
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

    holdings: list[HoldingItem] = []
    total_val = sum(float(p.quantity or 0) * float(p.average_cost or p.market_price or 0) for p in positions)

    for p in positions:
        qty = float(p.quantity or 0)
        px = float(p.average_cost or p.market_price or 0)
        val = qty * px
        weight = f"{(val / total_val * 100):.1f}%" if total_val > 0 else "0.0%"
        ticker_name = p.company.ticker if p.company else f"ACT-{p.company_id}"
        holdings.append(
            HoldingItem(
                ticker=ticker_name,
                shares=qty,
                price=px,
                value=val,
                weight=weight,
            )
        )

    data = ThesisPdfData(
        portfolio_name=portfolio.name,
        version=1,
        rating="buy",
        status="published",
        generated_on=portfolio.created_at.date().isoformat() if portfolio.created_at else "",
        executive_summary=f"Informe consolidado de la cartera {portfolio.name}. Consta de {len(positions)} posiciones activas con un valor contable total estimado de {total_val:,.2f} €.",
        holdings=holdings,
        sections=[
            PdfSection(
                title="1. Estrategia y Asignación de Capital",
                body="La cartera está orientada a la generación de valor a largo plazo mediante empresas de alta calidad, ventajas competitivas sostenibles y balances saneados.",
            ),
            PdfSection(
                title="2. Control de Riesgos",
                body="Se monitorizan límites de concentración por posición y sector con rebalanceos periódicos basados en márgenes de seguridad y catalizadores operativos.",
            ),
        ],
    )

    filename = f"gerarai-cartera-{sanitize_pdf_filename(portfolio.name)}.pdf"
    content = build_thesis_pdf(data)
    return content, filename
