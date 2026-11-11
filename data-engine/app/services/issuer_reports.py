"""Informes de emisoras que no presentan a la SEC: registro oficial o web de la empresa.

Caso real (cartera de Nico, 8-nov-2026): Fairfax (FFH.TO, Canada) y Georgia
Capital (CGEO.L, Londres) tenian precio y DCA pero ningun documento, asi que
la tesis y el desglose por partes no tenian nada que citar («sin datos SEC»).

- Canada: SEDAR+ (www.sedarplus.ca) responde a cualquier peticion con la
  pagina de bloqueo de Radware (captcha antibots, medido 8-nov-2026), asi
  que no se usa. La alternativa gratis y publica es la web de la empresa:
  la pagina de inversores (``company.ir_url``) enlaza los PDF del informe
  anual y de los trimestrales (Fairfax: «Fairfax-Financial-2025-Annual-
  Report», «FFH-2026-Q3-Interim-Report»).
- Reino Unido, respaldo: si el NSM no da informe anual (sin LEI, caido o sin
  informe), las ultimas cuentas depositadas en Companies House por el propio
  emisor (nombre exacto), con su URL publica (``companies_house_report``).
- Reino Unido: el NSM de la FCA (``connectors.fca_nsm``) guarda por LEI los
  informes regulados; los de Georgia Capital van sin etiquetar (xhtml de 21
  MB convertido de PDF), pero sus anuncios RNS de resultados («3rd Quarter
  Results», «Half-year Financial Report») son html con el estado del NAV.

Reglas generales (nunca por emisor): de cada fuente se toma el ultimo
informe ANUAL y el ultimo PERIODICO; se prefiere la version en ingles; la
fecha sale del propio registro (NSM) o de la ruta de subida / el año del
nombre del fichero (web). Nada se descarga aqui: se devuelven las URLs para
la ingesta normal de documentos (texto troceado y citable por pagina).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

ANNUAL_RE = re.compile(
    r"annual[\s_-]*report|integrated[\s_-]*report|rapport[\s_-]*annuel|"
    r"(?:informe|reporte)[\s_-]*anual|(?<![a-z])ar[\s_-]?20\d\d", re.I)
INTERIM_RE = re.compile(
    r"interim[\s_-]*report|quarterly[\s_-]*report|(?<![a-z])q[1-4][\s_-]*(?:20\d\d|report)|"
    r"half[\s_-]*year(?:ly)?[\s_-]*report|rapport[\s_-]*trimestriel|"
    r"(?<![a-z0-9])[1-4]t[\s_-]*20\d\d(?!\d)", re.I)
NON_ENGLISH_RE = re.compile(r"(?:^|[\s_\-./])(?:french|francais|fran[cç]ais|fr|espanol|deutsch)(?=$|[\s_\-./])", re.I)
EXCLUDE_RE = re.compile(r"circular|proxy|letter|esg|sustainab|governance|presentation|webcast|notice", re.I)
_UPLOAD_DATE = re.compile(r"/(20\d\d)/(0[1-9]|1[0-2])/")
_YEAR = re.compile(r"(?<!\d)(19\d\d|20\d\d)(?!\d)")

# Por orden: el anuncio de resultados anuales (texto completo con cuentas y NAV)
# antes que el «Annual Financial Report» en RNS, que suele ser solo el aviso
# de que el informe está disponible (Georgia Capital, 23-abr-2026: 18 KB).
NSM_ANNUAL_TYPES = ("Final Results", "Annual Financial Report")
NSM_PERIODIC_TYPES = ("3rd Quarter Results", "1st Quarter Results", "Half-year Financial Report",
                      "Interim Management Statement", "Final Results")
# El NSM guarda PDF/xhtml de hasta decenas de MB; la ingesta acepta 15 MB.
# Un anuncio RNS («Plain text») es el texto completo del anuncio en html.
NSM_PREFERRED_FORMATS = ("Plain text", "PDF", "Untagged", "Tagged")


@dataclass(frozen=True)
class ReportLink:
    kind: str  # annual | periodic
    url: str
    title: str
    date: str  # AAAA-MM-DD o AAAA-MM (web) / AAAA (solo año)
    source: str


def _order_key(url: str, text: str) -> str:
    upload = _UPLOAD_DATE.search(urlparse(url).path)
    if upload:
        return f"{upload.group(1)}-{upload.group(2)}"
    years = [int(y) for y in _YEAR.findall(f"{url} {text}")]
    return f"{max(years)}" if years else ""


def _links(page_html: str, base_url: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", page_html or "", re.S | re.I):
        href = unescape(m.group(1)).strip()
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(m.group(2)))).strip()
        url = urljoin(base_url, href)
        if urlparse(url).scheme in {"http", "https"} and urlparse(url).path.lower().endswith(".pdf"):
            out.append((url, text))
    return out


def pick_ir_reports(page_html: str, base_url: str) -> list[ReportLink]:
    """Ultimo informe anual y ultimo periodico enlazados como PDF en la pagina de inversores."""
    best: dict[str, tuple[str, str, str]] = {}
    host = urlparse(base_url).hostname or ""
    for url, text in _links(page_html, base_url):
        name = f"{urlparse(url).path.rsplit('/', 1)[-1]} {text}"
        if EXCLUDE_RE.search(name) or NON_ENGLISH_RE.search(name.replace(".pdf", " ")):
            continue
        if ANNUAL_RE.search(name):
            kind = "annual"
        elif INTERIM_RE.search(name):
            kind = "periodic"
        else:
            continue
        key = _order_key(url, text)
        if not key:
            continue
        if kind not in best or key > best[kind][0]:
            stem = urlparse(url).path.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("-", " ").replace("_", " ")
            best[kind] = (key, url, text if len(text) >= 8 else stem)
    return [ReportLink(kind=k, url=v[1], title=v[2], date=v[0], source=f"web de la empresa ({host})")
            for k, v in sorted(best.items())]


def pick_nsm_reports(filings: list[Any]) -> list[ReportLink]:
    """Ultimo informe anual y ultimo de resultados periodicos de un emisor en el NSM."""
    def rank(f: Any) -> tuple[str, int]:
        fmt = str(getattr(f, "document_format", "") or "")
        pref = NSM_PREFERRED_FORMATS.index(fmt) if fmt in NSM_PREFERRED_FORMATS else len(NSM_PREFERRED_FORMATS)
        return (f.submitted_date, -pref)

    out: list[ReportLink] = []
    used: set[str] = set()
    groups = [("annual", (t,)) for t in NSM_ANNUAL_TYPES] + [("periodic", NSM_PERIODIC_TYPES)]
    for kind, types in groups:
        if kind == "annual" and any(link.kind == "annual" for link in out):
            continue
        pool = [f for f in filings if f.filing_type in types and f.url not in used
                and str(f.document_format) in NSM_PREFERRED_FORMATS[:2]]
        if not pool:
            continue
        pick = max(pool, key=rank)
        used.add(pick.url)
        out.append(ReportLink(kind=kind, url=pick.url, title=f"{pick.company} — {pick.filing_type} ({pick.submitted_date})",
                              date=pick.submitted_date, source="FCA National Storage Mechanism"))
    return out


async def companies_house_report(company: Any) -> ReportLink | None:
    """Ultimas cuentas anuales depositadas en Companies House por el propio emisor (nombre exacto).

    Respaldo general para un emisor britanico cuando el NSM no da su informe (sin LEI,
    NSM caido o sin informe anual): son las cuentas oficiales, citables por su URL publica.
    None si la funcion esta apagada (sin ``COMPANIES_HOUSE_API_KEY``) o no hay cuentas."""
    from app.services.companies_house_evidence import issuer_annual_accounts
    from app.services.connectors.companies_house import CompaniesHouseError, client_from_settings

    name = str(getattr(company, "name", "") or "").strip()
    client = client_from_settings(max_requests=12)
    if client is None or not name:
        return None
    try:
        accounts = await issuer_annual_accounts(client, name)
    except CompaniesHouseError:
        return None
    finally:
        await client.aclose()
    if not accounts or not accounts.get("document_url"):
        return None
    made_up = accounts.get("made_up_to") or ""
    return ReportLink(kind="annual", url=str(accounts["document_url"]),
                      title=f"{accounts['company_name']} — cuentas anuales a {made_up} (Companies House)",
                      date=str(accounts.get("filed_on") or made_up), source="Companies House")


async def discover_reports(company: Any) -> tuple[list[ReportLink], str]:
    """(enlaces, motivo). Reino Unido -> NSM por LEI; si no, la pagina de inversores."""
    from app.services import esef_live
    from app.services.connectors.fca_nsm import NsmClient, NsmError
    from app.services.public_fetch import fetch_public_url_async

    ticker = str(getattr(company, "ticker", "") or "")
    if esef_live.SUFFIX_JURISDICTION.get(esef_live._ticker_suffix(ticker)) == "GB":
        from app.services.connectors.esef import EsefClient, gleif_http_client

        http = gleif_http_client()
        nsm = NsmClient(client=http)
        try:
            identity, reason = await esef_live.resolve_issuer(company, esef=EsefClient(), http=http, nsm=nsm)
            if identity is None:
                links, reason = [], f"sin_lei: {reason}"
            else:
                try:
                    filings = await nsm.list_filings_for_lei(identity.lei, filing_type=None, size=200)
                    links = pick_nsm_reports(filings)
                    reason = "ok" if links else "nsm_sin_informes"
                except NsmError as exc:
                    links, reason = [], f"nsm_error: {exc}"
        finally:
            await http.aclose()
        if not any(link.kind == "annual" for link in links):
            # Sin informe anual del NSM: las cuentas oficiales del registro mercantil.
            ch = await companies_house_report(company)
            if ch is not None:
                return [*links, ch], (reason if links else f"companies_house ({reason})")
        return links, reason
    ir_url = str(getattr(company, "ir_url", "") or "").strip()
    if not ir_url:
        return [], "sin_ir_url: la ficha no tiene la web de inversores"
    try:
        content, _, final_url = await fetch_public_url_async(ir_url, timeout=30)
    except Exception as exc:  # noqa: BLE001 - la web caida no es un error de la tesis
        return [], f"ir_inaccesible: {type(exc).__name__}"
    links = pick_ir_reports(content.decode("utf-8", errors="replace"), final_url or ir_url)
    return links, "ok" if links else "ir_sin_informes_pdf"
