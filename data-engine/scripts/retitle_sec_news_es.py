"""Saneado ONE-SHOT de titulares SEC persistidos en inglés (quick win UX 4).

Contexto: la ingesta es insert-only con dedup por URL antes que por título,
así que un deploy del conector NO reescribe las filas ya persistidas. Este
script retitula SOLO esas filas históricas al formato español actual.

Campos que muta (SOLO texto compuesto por GerarAI y procedencia mal marcada):
- NewsEvent.title (visible en /research/news y tarjetas),
- NewsEvent.summary (del que deriva el título y alimenta otras superficies),
- metadata: RETIRA source_headline y marca headline_from_source=false.
  El source_headline de estas filas NO es un titular publicado por la SEC
  (el conector viejo lo construía, p.ej. «COST 8-K (fecha)»): conservarlo
  haría que los lectores de #574 siguieran atribuyendo a la fuente un texto
  creado por GerarAI. No se sustituye por nada: se retira y queda en el
  backup. El flag marca el título de display como generado por GerarAI (la
  UI omite entonces el prefijo de ticker duplicado).
Títulos, resúmenes y AMBOS valores de metadata originales quedan en el
backup JSON: el rollback restaura el estado previo exacto, no una
aproximación.

Seguridad (requisitos de revisión):
- DRY-RUN por defecto en apply Y en rollback: nada escribe sin --apply.
- Match estricto de origen: metadata.connector == "sec" AND
  NewsEvent.source == "SEC" AND url https cuyo HOST está en la allowlist
  SEC (www.sec.gov, sec.gov, data.sec.gov, efts.sec.gov) con ruta EDGAR
  (/Archives/edgar/): «sec.gov.attacker.example» NO casa. La huella del
  metadata sola no autentica origen.
- Patrón inglés conocido en el título (fecha entre paréntesis, «filed» o
  doble prefijo de ticker F175) y form por allowlist explícita de
  formularios SEC («filing» si es irreconocible, nunca un form inventado).
- Colisiones por tenant+compañía+título destino: se RELAJAN solo entre
  filas SEC estrictas con accession EDGAR DISTINTO y determinable (dos
  filings distintos comparten título de display por diseño; el dry-run las
  lista explícitamente para revisión). Se exige respecto de TODAS las
  filas que coexisten con ese destino (en BD y en el plan): URL igual,
  mismo accession, accession indeterminable u origen no verificable en
  cualquiera de ellas → se salta y se reporta. La comprobación se repite
  al aplicar.
- Backup exclusivo y durable ANTES de tocar la BD: se crea con modo 'x'
  (nunca sobrescribe), se fsync-ea y se renombra atómicamente.
- --apply requiere --plan ruta.json: el dry-run escribe el plan revisado y
  --apply compara CADA fila contra ese plan (título/summary/metadata
  actuales == valores esperados); una fila que cambió desde el dry-run se
  salta y se reporta, no se pisa. Una única transacción; error = rollback.
- --rollback restaura con precondición (el título actual debe ser el que
  escribió este plan); filas editadas después se saltan y se reportan.

Ejecutarlo sobre la BD de producción es una decisión aparte que requiere
aprobación explícita del propietario con alcance y preview del dry-run.

Uso:
    python -m scripts.retitle_sec_news_es --plan /tmp/sec-plan.json   # dry-run
    python -m scripts.retitle_sec_news_es --apply --plan /tmp/sec-plan.json --backup /tmp/sec.json
    python -m scripts.retitle_sec_news_es --rollback /tmp/sec.json           # preview
    python -m scripts.retitle_sec_news_es --rollback /tmp/sec.json --apply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Company, NewsEvent

# Patrones ingleses conocidos del conector SEC histórico:
#   «COST 8-K (2026-09-24)», «8-K filed 2026-09-24», doble prefijo F175.
_DATE_PARENS = re.compile(r"\(\d{4}-\d{2}-\d{2}\)\s*$")
_FILED_EN = re.compile(r"\bfiled\b", re.IGNORECASE)

# Allowlist explícita de formularios SEC: un regex amplio casaría con
# cualquier token «LETRAS-dígito» y acabaría afirmando un form inventado.
_KNOWN_FORMS = [
    "8-K/A", "8-K", "10-K/A", "10-K", "10-Q/A", "10-Q", "11-K", "20-F", "40-F",
    "6-K", "S-1/A", "S-1", "S-3", "S-4", "S-8", "S-11", "F-1/A", "F-1", "F-3",
    "F-4", "F-6", "F-10", "424B2", "424B3", "424B4", "424B5", "SC 13D/A",
    "SC 13D", "SC 13G/A", "SC 13G", "SC13D", "SC13G", "13F-HR", "13F-NT",
    "DEF 14A", "DEFA14A", "PRE 14A", "POS AM", "SD", "ARS", "144",
]
_FORM = re.compile(
    r"\b(" + "|".join(re.escape(form) for form in _KNOWN_FORMS) + r")\b"
)

# Hosts SEC legítimos (EDGAR). «sec.gov.attacker.example» NO está aquí.
_SEC_HOSTS = frozenset({"www.sec.gov", "sec.gov", "data.sec.gov", "efts.sec.gov"})
_SEC_PATH_PREFIX = "/Archives/edgar/"


def _is_sec_url(url: str | None) -> bool:
    """Match estricto de origen SEC: https + host en allowlist + ruta EDGAR."""
    if not url:
        return False
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "") in _SEC_HOSTS
        and parsed.path.startswith(_SEC_PATH_PREFIX)
    )


def _english_pattern(title: str) -> bool:
    return bool(_DATE_PARENS.search(title) or _FILED_EN.search(title))


def _strip_ticker_prefixes(text: str, ticker: str) -> str:
    """Quita prefijos repetidos del ticker (bug F175: «COST COST 8-K ...»)."""
    if not ticker:
        return text
    pattern = re.compile(rf"^(?:{re.escape(ticker)}\s+){{1,2}}", re.IGNORECASE)
    return pattern.sub("", text.strip())


def _form_from(headline: str, ticker: str) -> str | None:
    """Form del titular original, o None si no es determinable con certeza."""
    base = _strip_ticker_prefixes(headline, ticker)
    base = _DATE_PARENS.sub("", base).strip()
    base = re.sub(r"\bfiled\b", "", base, flags=re.IGNORECASE).strip()
    match = _FORM.search(base)
    return match.group(1) if match else None


def _plan_row(row: NewsEvent, ticker: str) -> dict | None:
    """Plan de saneado de una fila candidata, o None si no procede tocarla."""
    headline = (row.metadata_ or {}).get("source_headline") or row.title
    form = _form_from(headline, ticker)
    if form is None and not _english_pattern(row.title):
        # Sin form reconocible y sin patrón inglés: no tocar lo incierto.
        return None
    # «filing» si el form es irreconocible: el mismo fallback honesto del
    # conector, nunca un form inventado.
    new_headline = f"{form or 'filing'} presentado ante la SEC"
    new_title = f"{ticker} {new_headline}" if ticker else new_headline
    metadata = row.metadata_ or {}
    old_headline = metadata.get("source_headline")
    already_flagged = metadata.get("headline_from_source") is False
    if new_title == row.title and new_title == row.summary and old_headline is None and already_flagged:
        return None  # ya saneada (texto y procedencia)
    # Procedencia histórica: el source_headline de estas filas NO es un
    # titular publicado por la SEC — lo construía el conector viejo
    # («COST 8-K (fecha)») y NewsService lo guardó como verbatim de la
    # fuente. Preservar bytes no preserva procedencia: el plan lo RETIRA
    # (queda en el backup para rollback) y marca headline_from_source=False
    # para que los lectores de #574 dejen de atribuirlo a la SEC y la UI
    # omita el prefijo de ticker del título de display.
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "company_id": row.company_id,
        "expected": {
            "title": row.title,
            "summary": row.summary,
            "url": row.url,
            "source_headline": old_headline,
            "headline_from_source": metadata.get("headline_from_source"),
        },
        "new": {
            "title": new_title,
            "summary": new_title,
            "source_headline": None,
            "headline_from_source": False,
        },
    }


def _candidates(db) -> list[tuple[NewsEvent, str]]:
    rows = db.scalars(
        select(NewsEvent).where(
            NewsEvent.source == "SEC",
            NewsEvent.url.isnot(None),
        )
    ).all()
    out: list[tuple[NewsEvent, str]] = []
    for row in rows:
        if (row.metadata_ or {}).get("connector") != "sec":
            continue
        if not _is_sec_url(row.url):
            continue
        if not _english_pattern(row.title):
            continue
        ticker = ""
        if row.company_id is not None:
            company = db.get(Company, row.company_id)
            ticker = (company.ticker if company else "") or ""
        out.append((row, ticker))
    return out


def _write_backup_durable(path: str, payload: list[dict]) -> None:
    """Backup exclusivo ('x': nunca sobrescribe) y durable ANTES de la BD."""
    tmp = f"{path}.tmp-{os.getpid()}"
    # Exclusivo también el temporal: dos apply concurrentes no se pisan.
    with open(tmp, "x", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    if os.path.exists(path):
        os.unlink(tmp)
        raise FileExistsError(f"el backup {path} ya existe: no se sobrescribe")
    os.replace(tmp, path)
    dir_flag = getattr(os, "O_DIRECTORY", 0)
    if dir_flag:
        dir_fd = os.open(os.path.dirname(os.path.abspath(path)), dir_flag)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


_ACCESSION_DIR = re.compile(r"^/Archives/edgar/data/\d+/(\d{10,24})(?:/|$)")
_ACCESSION_DASHED = re.compile(r"(\d{10}-\d{2}-\d{3})")


def _edgar_accession(url: str | None) -> str | None:
    """Número de accession EDGAR (solo dígitos) de una URL, o None si no es
    determinable. Identifica el filing: dos variantes de URL del mismo
    accession son el MISMO filing."""
    if not url:
        return None
    path = urlparse(url).path
    match = _ACCESSION_DIR.match(path)
    if match:
        return match.group(1)
    match = _ACCESSION_DASHED.search(path)
    if match:
        return match.group(1).replace("-", "")
    return None


def _distinct_sec_filing(a: NewsEvent, b: NewsEvent) -> bool:
    """True solo si ambas filas son SEC estrictas con accession EDGAR
    distinto y determinable: dos filings distintos, no un duplicado ni dos
    variantes de URL del mismo filing."""
    if not a.url or not b.url or a.url == b.url:
        return False
    for row in (a, b):
        if row.source != "SEC" or (row.metadata_ or {}).get("connector") != "sec":
            return False
        if not _is_sec_url(row.url):
            return False
    accession_a = _edgar_accession(a.url)
    accession_b = _edgar_accession(b.url)
    return accession_a is not None and accession_b is not None and accession_a != accession_b


def _apply_plan(db, planned: list[dict]) -> tuple[int, list[int]]:
    """Aplica el plan re-verificando cada fila; devuelve (aplicadas, saltadas).

    El plan se revisa en dry-run, pero no es un chequeo permanente: al aplicar
    se re-verifica identidad (tenant/company), origen SEC estricto, estado
    esperado y colisiones de título en el momento del apply. Sin restricción
    UNIQUE sobre título, un duplicado entraría en silencio; por eso la
    colisión se vuelve a comprobar aquí, no solo al planificar.
    """
    applied = 0
    skipped: list[int] = []
    seen_destinations: dict[tuple, list[int]] = {}
    for item in planned:
        row = db.get(NewsEvent, item["id"])
        if (
            row is None
            or row.tenant_id != item["tenant_id"]
            or row.company_id != item.get("company_id")
        ):
            skipped.append(item["id"])
            continue
        # Revalida el origen al aplicar: el plan revisado no es un chequeo
        # permanente de que la fila sigue siendo una fila SEC estricta.
        metadata = row.metadata_ or {}
        if (
            row.source != "SEC"
            or metadata.get("connector") != "sec"
            or not _is_sec_url(row.url)
        ):
            skipped.append(item["id"])
            continue
        # La URL fija la identidad del filing: si cambió entre preview y
        # apply (aunque sea otra URL EDGAR válida), el plan ya no aplica.
        current = {
            "title": row.title,
            "summary": row.summary,
            "url": row.url,
            "source_headline": (row.metadata_ or {}).get("source_headline"),
            "headline_from_source": (row.metadata_ or {}).get("headline_from_source"),
        }
        if current != item["expected"]:
            # La fila cambió desde el plan revisado: no se pisa.
            skipped.append(item["id"])
            continue
        # Colisión en el momento del apply: otra fila del mismo tenant+company
        # ya tiene el título destino (o es otra fila de este mismo plan con el
        # mismo destino). Se relaja SOLO entre filas SEC estrictas con URLs
        # EDGAR canónicas distintas y no vacías: dos filings distintos del
        # mismo form comparten título de display por diseño. URL igual, no
        # verificable u origen dudoso: se salta en lugar de duplicar.
        new_title = item["new"]["title"]
        clashes = db.scalars(
            select(NewsEvent).where(
                NewsEvent.tenant_id == row.tenant_id,
                NewsEvent.company_id == row.company_id,
                NewsEvent.title == new_title,
                NewsEvent.id != row.id,
            )
        ).all()
        # TODAS las colisiones del destino deben ser admisibles: una sola
        # fila con URL igual, mismo accession u origen no verificable
        # bloquea el retitle (fail-closed, sin depender del orden).
        if any(not _distinct_sec_filing(row, clash) for clash in clashes):
            skipped.append(item["id"])
            continue
        destination = (row.tenant_id, row.company_id, new_title)
        if any(
            (other := db.get(NewsEvent, other_id)) is None
            or not _distinct_sec_filing(row, other)
            for other_id in seen_destinations.get(destination, [])
        ):
            skipped.append(item["id"])
            continue
        seen_destinations.setdefault(destination, []).append(row.id)
        row.title = new_title
        row.summary = item["new"]["summary"]
        # Procedencia: se retira el titular sintético atribuido a la SEC y
        # se marca el display como generado por GerarAI. Nueva asignación del
        # dict (no mutación in place) para que el cambio se registre.
        new_metadata = dict(row.metadata_ or {})
        new_metadata.pop("source_headline", None)
        new_metadata["headline_from_source"] = False
        row.metadata_ = new_metadata
        applied += 1
    return applied, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="escribe los cambios (sin esto es dry-run)")
    parser.add_argument("--plan", help="ruta JSON del plan; el dry-run la escribe y --apply la exige")
    parser.add_argument("--backup", help="ruta JSON de backup (obligatoria con --apply)")
    parser.add_argument("--rollback", help="restaura títulos desde un backup JSON (dry-run sin --apply)")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.rollback:
            with open(args.rollback, encoding="utf-8") as fh:
                backup = json.load(fh)
            restorable: list[dict] = []
            skipped: list[int] = []
            for entry in backup:
                row = db.get(NewsEvent, entry["id"])
                metadata = (row.metadata_ or {}) if row else {}
                current_new = (
                    {
                        "title": row.title,
                        "summary": row.summary,
                        "source_headline": metadata.get("source_headline"),
                        "headline_from_source": metadata.get("headline_from_source"),
                    }
                    if row
                    else None
                )
                if (
                    row is not None
                    and row.tenant_id == entry["tenant_id"]
                    and current_new == entry["new"]
                ):
                    restorable.append(entry)
                else:
                    # Precondición: solo se revierte lo que ESTE plan escribió
                    # y nadie tocó después.
                    skipped.append(entry["id"])
            mode = "APPLY" if args.apply else "DRY-RUN"
            print(f"[{mode}] rollback: {len(restorable)} reversibles, "
                  f"{len(skipped)} saltadas (editadas tras el plan o ausentes): {skipped}")
            if not args.apply:
                print("dry-run: sin escrituras. Repite con --apply para revertir.")
                return 0
            for entry in restorable:
                row = db.get(NewsEvent, entry["id"])
                row.title = entry["old"]["title"]
                row.summary = entry["old"]["summary"]
                restored_metadata = dict(row.metadata_ or {})
                # Restauración exacta de AMBOS valores: si el flag no
                # existía antes se retira; si existía se devuelve su valor.
                if entry["old"].get("headline_from_source") is None:
                    restored_metadata.pop("headline_from_source", None)
                else:
                    restored_metadata["headline_from_source"] = entry["old"]["headline_from_source"]
                if entry["old"].get("source_headline") is None:
                    restored_metadata.pop("source_headline", None)
                else:
                    restored_metadata["source_headline"] = entry["old"]["source_headline"]
                row.metadata_ = restored_metadata
            db.commit()
            print(f"rollback aplicado: {len(restorable)} filas restauradas")
            return 0

        candidates = _candidates(db)
        planned: list[dict] = []
        collisions: list[dict] = []
        undetermined: list[int] = []
        shared: list[tuple[int, int, str]] = []
        planned_titles: dict[tuple, list[int]] = {}
        for row, ticker in candidates:
            plan = _plan_row(row, ticker)
            if plan is None:
                undetermined.append(row.id)
                continue
            # Colisión INTRAPLAN: dos filas del mismo plan que convergen al
            # mismo título no aparecen en la BD hasta el commit. Se relaja
            # SOLO entre filings SEC distintos (URLs EDGAR canónicas
            # distintas y no vacías): el dry-run las lista para revisión.
            plan_key = (row.tenant_id, row.company_id, plan["new"]["title"])
            inadmissible = False
            for other_id in planned_titles.get(plan_key, []):
                other = db.get(NewsEvent, other_id)
                if other is None or not _distinct_sec_filing(row, other):
                    collisions.append({"id": row.id, "title": plan["new"]["title"],
                                       "clash_with": other_id})
                    inadmissible = True
                    break
                shared.append((other_id, row.id, plan["new"]["title"]))
            if inadmissible:
                continue
            clashes = db.scalars(
                select(NewsEvent).where(
                    NewsEvent.tenant_id == row.tenant_id,
                    NewsEvent.company_id == row.company_id,
                    NewsEvent.title == plan["new"]["title"],
                    NewsEvent.id != row.id,
                )
            ).all()
            # TODAS las colisiones del destino deben ser admisibles.
            blocked = next((c for c in clashes if not _distinct_sec_filing(row, c)), None)
            if blocked is not None:
                collisions.append({"id": row.id, "title": plan["new"]["title"], "clash_with": blocked.id})
                continue
            for clash in clashes:
                shared.append((clash.id, row.id, plan["new"]["title"]))
            planned_titles.setdefault(plan_key, []).append(row.id)
            planned.append(plan)

        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"[{mode}] candidatas SEC estrictas (connector+source+url https EDGAR+patrón): {len(candidates)}")
        print(f"[{mode}] a sanear: {len(planned)}; colisiones saltadas: {len(collisions)}; "
              f"sin form determinable o ya correctas: {len(undetermined)}")
        for item in planned:
            print(f"  #{item['id']}: {item['expected']['title']!r} -> {item['new']['title']!r}")
        for item in collisions:
            print(f"  COLISIÓN #{item['id']}: destino {item['title']!r} ya existe en #{item['clash_with']}")
        if shared:
            print(f"[{mode}] filas que compartirán título de display (filings SEC distintos; revisar):")
            for first_id, second_id, title in shared:
                print(f"  COMPARTIDO {title!r}: #{first_id} y #{second_id}")

        if not args.apply:
            if args.plan:
                with open(args.plan, "w", encoding="utf-8") as fh:
                    json.dump(planned, fh, ensure_ascii=False, indent=2)
                print(f"plan escrito en {args.plan}: revísalo y repite con --apply --plan {args.plan} --backup ruta.json")
            else:
                print("dry-run: sin escrituras. Repite con --plan ruta.json para guardar el plan.")
            return 0
        if not args.plan:
            print("error: --apply exige --plan ruta.json generado por el dry-run revisado", file=sys.stderr)
            return 2
        if not args.backup:
            print("error: --apply exige --backup ruta.json", file=sys.stderr)
            return 2
        with open(args.plan, encoding="utf-8") as fh:
            reviewed_plan = json.load(fh)
        backup_payload = [
            {"id": p["id"], "tenant_id": p["tenant_id"],
             "old": p["expected"], "new": p["new"]}
            for p in reviewed_plan
        ]
        _write_backup_durable(args.backup, backup_payload)
        print(f"backup durable escrito en {args.backup} ({len(reviewed_plan)} filas)")

        applied, skipped = _apply_plan(db, reviewed_plan)
        if skipped:
            print("saltadas al aplicar por revalidación "
                  f"(identidad/origen/estado/colisión desde el plan): {skipped}")
        db.commit()
        print(f"aplicado: {applied} filas saneadas en UNA transacción")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
