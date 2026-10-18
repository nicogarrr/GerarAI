"""Exportación Obsidian de tesis persistidas. Solo stdlib, sin almacenamiento."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse
from zipfile import ZIP_DEFLATED, ZipFile


def _yaml(value: str) -> str:
    # JSON strings are a valid YAML scalar and protect frontmatter from injection.
    import json

    return json.dumps(value, ensure_ascii=False)


def _safe_url(url: str | None) -> str:
    if not url:
        return ""
    clean = url.strip()
    if any(character in clean for character in "<>\r\n\t"):
        return ""
    parsed = urlparse(clean)
    return clean if parsed.scheme in {"https", "http"} and parsed.netloc else ""


def _line(value: str) -> str:
    return re.sub(r"[\r\n]+", " ", value).strip()


_TICKER_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,19}")
_DISCLAIMER = "Documento informativo de investigación. No es asesoramiento financiero."


@dataclass
class Source:
    url: str = ""
    date: str = ""
    statement: str = ""
    tier: str = ""


@dataclass
class Note:
    title: str
    version: int = 1
    date: str = ""
    status: str = ""
    body: str = ""
    sources: list[Source] = field(default_factory=list)


@dataclass
class CompanyEntry:
    """Empresa del vault del tenant con sus metadatos persistidos."""

    ticker: str
    name: str = ""
    sector: str = ""
    industry: str = ""
    in_portfolio: bool = False
    in_watchlist: bool = False


def _frontmatter(ticker: str, note: Note) -> str:
    urls = list(dict.fromkeys(url for source in note.sources if (url := _safe_url(source.url))))
    lines = [
        "---",
        f"ticker: {_yaml(ticker)}",
        *([f"fecha: {_yaml(note.date)}"] if note.date else []),
        f"estado: {_yaml(note.status or 'sin datos')}",
        "fuentes:",
    ]
    lines.extend(f"  - {_yaml(url)}" for url in urls)
    if not urls:
        lines[-1] = "fuentes: []"
    return "\n".join(lines) + "\n---\n\n"


def _render_thesis_note(ticker: str, note: Note) -> str:
    """Cuerpo completo de una nota de tesis (mismo formato en zip suelto y vault)."""
    content = _frontmatter(ticker, note) + f"# {note.title}\n\n[[{ticker} - Índice]]\n\n"
    content += (note.body.strip() or "## Sin datos\n\nNo hay contenido de tesis persistido.") + "\n\n"
    content += "## Fuentes\n\n"
    if note.sources:
        for source in note.sources:
            url = _safe_url(source.url)
            label = _line(source.statement or source.tier or "Fuente")
            date = f" ({_line(source.date)})" if source.date else ""
            # Angle brackets protect Markdown URLs containing parentheses.
            content += (
                f"- {label}: [Fuente](<{url}>){date}\n"
                if url
                else f"- {label}: Sin datos de URL{date}\n"
            )
    else:
        content += "Sin datos de fuentes vinculadas.\n"
    content += f"\n{_DISCLAIMER}\n"
    return content


def build_obsidian_zip(ticker: str, notes: list[Note]) -> bytes:
    """Construye notas enlazadas entre sí sin inventar citas ni fechas."""
    if not _TICKER_PATTERN.fullmatch(ticker):
        raise ValueError("Ticker inválido")
    if not notes:
        raise ValueError("No hay tesis")
    if len({note.version for note in notes}) != len(notes):
        raise ValueError("Versiones duplicadas")
    output = io.BytesIO()
    folder = f"GerarAI/{ticker}"
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        filenames = [f"Tesis {ticker} v{note.version}" for note in notes]
        index_note = Note(title=f"{ticker} - Índice", date=notes[-1].date, status=notes[-1].status)
        index_content = _frontmatter(ticker, index_note) + f"# {ticker} - Índice\n\n## Tesis\n\n"
        index_content += "\n".join(f"- [[{name}]]" for name in reversed(filenames)) + "\n"
        archive.writestr(f"{folder}/{ticker} - Índice.md", index_content)
        for name, note in zip(filenames, notes, strict=True):
            archive.writestr(f"{folder}/{name}.md", _render_thesis_note(ticker, note))
    return output.getvalue()


def find_mentions(text: str, candidates: dict[str, str]) -> set[str]:
    """Tickers candidatos mencionados literalmente en el texto.

    Solo enlaza menciones literales con límites de palabra completos en ambos
    lados: el ticker como token propio (ni subcadena ni prefijo de otro
    identificador: "RKLB-OTHER" o "BRK.B" no mencionan a RKLB/BRK) o el
    nombre completo de la empresa ("Banco Santanderino" no menciona a Banco
    Santander). Nunca infiere relaciones que el texto no afirma. Los tickers
    de un carácter y los nombres ambiguos (<6 letras o "Unknown") no enlazan
    para no fabricar falsos positivos.
    """
    if not text:
        return set()
    found: set[str] = set()
    for ticker, name in candidates.items():
        if len(ticker) < 2 or not _TICKER_PATTERN.fullmatch(ticker):
            continue
        if re.search(rf"(?<![A-Za-z0-9.\-]){re.escape(ticker)}(?![A-Za-z0-9.\-])", text):
            found.add(ticker)
            continue
        clean = name.strip()
        if (
            len(clean) >= 6
            and clean.lower() != "unknown"
            and re.search(rf"(?<!\w){re.escape(clean)}(?!\w)", text, re.IGNORECASE)
        ):
            found.add(ticker)
    return found


def _company_frontmatter(entry: CompanyEntry) -> str:
    roles: list[str] = []
    if entry.in_portfolio:
        roles.append("cartera")
    if entry.in_watchlist:
        roles.append("watchlist")
    lines = [
        "---",
        'tipo: "empresa"',
        f"ticker: {_yaml(entry.ticker)}",
        f"nombre: {_yaml(entry.name)}",
        f"sector: {_yaml(entry.sector)}",
        f"industria: {_yaml(entry.industry)}",
        "rol:",
    ]
    lines.extend(f"  - {_yaml(role)}" for role in roles)
    if not roles:
        lines[-1] = "rol: []"
    return "\n".join(lines) + "\n---\n\n"


def _sector_label(value: str) -> str:
    clean = _line(value)
    return clean if clean and clean != "Unknown" else "Sin datos"


def build_obsidian_vault(
    companies: list[CompanyEntry],
    notes_by_ticker: dict[str, list[Note]],
    mentions: dict[str, set[str]] | None = None,
    unresolved_symbols: list[str] | None = None,
) -> bytes:
    """Vault Markdown del tenant: índice global, índice por ticker y tesis enlazadas.

    Todo el contenido viene de `companies`, `notes_by_ticker` y `mentions`
    (datos persistidos): los huecos se escriben como "Sin datos", nunca se
    rellenan. Las menciones se validan contra el vault para que ningún
    wikilink apunte a una nota que no existe.
    """
    mentions = mentions or {}
    unresolved = sorted({symbol.strip().upper() for symbol in (unresolved_symbols or []) if symbol.strip()})
    ordered = sorted(companies, key=lambda entry: entry.ticker)
    tickers: set[str] = set()
    for entry in ordered:
        if not _TICKER_PATTERN.fullmatch(entry.ticker):
            raise ValueError("Ticker inválido")
        if entry.ticker in tickers:
            raise ValueError("Empresa duplicada")
        tickers.add(entry.ticker)
    for ticker, notes in notes_by_ticker.items():
        if ticker not in tickers:
            raise ValueError("Notas de empresa fuera del vault")
        if len({note.version for note in notes}) != len(notes):
            raise ValueError("Versiones duplicadas")
    unknown_mentions = {target for targets in mentions.values() for target in targets} - tickers
    if unknown_mentions:
        raise ValueError("Mención a empresa fuera del vault")

    latest = max(
        (note.date for notes in notes_by_ticker.values() for note in notes if note.date),
        default="",
    )
    mentioned_by: dict[str, list[str]] = {
        entry.ticker: sorted(
            source for source, targets in mentions.items() if entry.ticker in targets and source != entry.ticker
        )
        for entry in ordered
    }

    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        index_lines = [
            "---",
            'tipo: "indice"',
            *([f"fecha: {_yaml(latest)}"] if latest else []),
            "---",
            "",
            "# GerarAI - Índice del vault",
            "",
            "> **Nota de migración:** antes del renombre de marca las notas se",
            "> generaban en la carpeta `CavaAI/`. Si ya tenías un vault,",
            "> mueve esa carpeta a `GerarAI/` a mano; este zip no la migra solo.",
            "",
            "## Cartera",
            "",
        ]
        portfolio = [entry for entry in ordered if entry.in_portfolio]
        watchlist = [entry for entry in ordered if entry.in_watchlist]
        if portfolio:
            index_lines.extend(
                f"- [[{entry.ticker} - Índice|{entry.ticker}]] - {_line(entry.name) or 'Sin datos de nombre'}"
                for entry in portfolio
            )
        else:
            index_lines.append("Sin datos: no hay posiciones en cartera.")
        index_lines.extend(["", "## Watchlist", ""])
        if watchlist:
            index_lines.extend(
                f"- [[{entry.ticker} - Índice|{entry.ticker}]] - {_line(entry.name) or 'Sin datos de nombre'}"
                for entry in watchlist
            )
        else:
            index_lines.append("Sin datos: no hay empresas en watchlist.")
        if unresolved:
            index_lines.extend(["", "## Símbolos sin empresa en el universo", ""])
            index_lines.extend(f"- {symbol} (sin datos de empresa)" for symbol in unresolved)
        index_lines.extend(["", _DISCLAIMER, ""])
        archive.writestr("GerarAI/Índice.md", "\n".join(index_lines))

        for entry in ordered:
            ticker = entry.ticker
            folder = f"GerarAI/{ticker}"
            notes = notes_by_ticker.get(ticker, [])
            filenames = [f"Tesis {ticker} v{note.version}" for note in notes]

            index_note = Note(
                title=f"{ticker} - Índice",
                date=notes[-1].date if notes else "",
                status=notes[-1].status if notes else "sin tesis",
            )
            content = (
                _frontmatter(ticker, index_note)
                + f"# {ticker} - Índice\n\n[[Índice|Índice del vault]]\n\n"
                + f"## Empresa\n\n- [[{ticker}]]\n\n## Tesis\n\n"
            )
            if filenames:
                content += "\n".join(f"- [[{name}]]" for name in reversed(filenames)) + "\n"
            else:
                content += f"Sin datos: no hay tesis persistida para {ticker}.\n"
            related = sorted(mentions.get(ticker, set()) - {ticker})
            content += "\n## Empresas relacionadas\n\n"
            if related:
                content += "\n".join(f"- [[{other}]]" for other in related) + "\n"
            else:
                content += f"Sin datos: ninguna tesis de {ticker} menciona a otras empresas del vault.\n"
            archive.writestr(f"{folder}/{ticker} - Índice.md", content)

            roles: list[str] = []
            if entry.in_portfolio:
                roles.append("En cartera")
            if entry.in_watchlist:
                roles.append("En watchlist")
            display_name = _line(entry.name) or ticker
            note_content = _company_frontmatter(entry) + f"# {display_name} ({ticker})\n\n"
            note_content += f"- Rol: {' · '.join(roles) if roles else 'Sin datos de rol'}\n"
            note_content += f"- Sector: {_sector_label(entry.sector)}\n"
            note_content += f"- Industria: {_sector_label(entry.industry)}\n\n"
            note_content += "## Tesis\n\n"
            if filenames:
                note_content += "\n".join(f"- [[{name}]]" for name in reversed(filenames)) + "\n"
            else:
                note_content += f"Sin datos: no hay tesis persistida para {ticker}.\n"
            note_content += "\n## Mencionada en\n\n"
            backlinks = mentioned_by[ticker]
            if backlinks:
                note_content += "\n".join(f"- [[{other}]]" for other in backlinks) + "\n"
            else:
                note_content += "Sin datos: ninguna otra empresa del vault la menciona.\n"
            note_content += f"\n[[{ticker} - Índice]] · [[Índice|Índice del vault]]\n\n{_DISCLAIMER}\n"
            archive.writestr(f"{folder}/{ticker}.md", note_content)

            for name, note in zip(filenames, notes, strict=True):
                archive.writestr(f"{folder}/{name}.md", _render_thesis_note(ticker, note))
    return output.getvalue()
