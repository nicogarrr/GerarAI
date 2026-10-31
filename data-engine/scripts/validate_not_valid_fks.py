"""Valida las FKs que las migraciones dejaron NOT VALID (paso aparte de 0114).

0114 crea/alinea las FKs como NOT VALID para no escanear tablas en caliente
durante el despliegue: las acciones ON DELETE rigen desde el DDL, pero las
filas LEGACY no estan verificadas hasta este paso. Mientras una FK siga NOT
VALID el planificador no puede apoyarse en ella (p. ej. para join elimination)
y no hay garantia retroactiva de integridad.

    python scripts/validate_not_valid_fks.py              # solo lista (dry-run)
    python scripts/validate_not_valid_fks.py --apply      # VALIDATE una a una
    python scripts/validate_not_valid_fks.py --apply --tabla documents

Idempotente: solo toca constraints con convalidated = false. Cada VALIDATE va
en su propia transaccion (lock SHARE UPDATE EXCLUSIVE breve por constraint,
no bloquea lecturas/escrituras). Si alguna falla por datos huerfanos, el
script sigue con el resto, lista al final TODAS las que fallaron con una
muestra de claves infractoras y sale 1: corregir datos y relanzar.

Sale 0 cuando no queda ninguna FK NOT VALID (nada que hacer o todo validado).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlalchemy as sa

_FKS_PENDIENTES = """
select conname, conrelid::regclass::text as tabla
from pg_constraint
where contype = 'f' and not convalidated and connamespace = 'public'::regnamespace
order by conrelid::regclass::text, conname
"""

_MUESTRA_INFRACTORAS = """
select {cols}
from {tabla} t
where {cond}
limit 5
"""


def _pendientes(conn, tabla: str | None) -> list[tuple[str, str]]:
    rows = conn.execute(sa.text(_FKS_PENDIENTES)).all()
    return [(r[0], r[1]) for r in rows if tabla is None or r[1] == tabla]


def _muestra_infractores(conn, conname: str, tabla: str, quote) -> list[str]:
    """Hasta 5 filas que violan la FK (columnas locales -> referenciadas).

    Un unico NOT EXISTS con TODAS las igualdades: en una FK compuesta el
    hijo (A1,B2) es huerfano aunque existan los padres (A1,B1) y (A2,B2);
    comparar columna a columna no lo detectaria.
    """
    meta = conn.execute(
        sa.text(
            "select conkey, confkey, confrelid::regclass::text "
            "from pg_constraint where conname = :n and conrelid = cast(:t as regclass)"
        ),
        {"n": conname, "t": tabla},
    ).one()
    conkey, confkey, ref = meta[0], meta[1], meta[2]
    att = sa.text(
        "select attname from pg_attribute where attrelid = cast(:t as regclass) and attnum = :a"
    )
    locales = [conn.execute(att, {"t": tabla, "a": int(a)}).scalar_one() for a in conkey]
    remotas = [conn.execute(att, {"t": ref, "a": int(a)}).scalar_one() for a in confkey]
    igualdades = " and ".join(
        f"r.{quote(m)} = t.{quote(l)}" for l, m in zip(locales, remotas, strict=True)
    )
    cond = " and ".join(
        [*(f"t.{quote(l)} is not null" for l in locales),
         f"not exists (select 1 from {quote(ref)} r where {igualdades})"]
    )
    cols = ", ".join(quote(l) for l in locales)
    sql = _MUESTRA_INFRACTORAS.format(cols=cols, tabla=quote(tabla), cond=cond)
    return [str(tuple(r)) for r in conn.execute(sa.text(sql)).all()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="ejecuta VALIDATE (sin esto solo lista)")
    parser.add_argument("--tabla", default=None, help="limita a una tabla")
    args = parser.parse_args()

    from app.core.config import get_settings

    engine = sa.create_engine(get_settings().database_url)
    quote = engine.dialect.identifier_preparer.quote
    with engine.connect() as conn:
        pendientes = _pendientes(conn, args.tabla)
    if not pendientes:
        print("No queda ninguna FK NOT VALID. Nada que hacer.")
        return 0
    print(f"{len(pendientes)} FKs NOT VALID pendientes:")
    for nombre, tabla in pendientes:
        print(f"  {tabla}: {nombre}")
    if not args.apply:
        print("\nDry-run: relanza con --apply para validarlas.")
        return 0

    fallidas: list[tuple[str, str, list[str]]] = []
    for nombre, tabla in pendientes:
        try:
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        f"ALTER TABLE {quote(tabla)} VALIDATE CONSTRAINT {quote(nombre)}"
                    )
                )
            print(f"OK   {tabla}: {nombre}")
        except sa.exc.SQLAlchemyError as exc:
            with engine.connect() as conn:
                muestra = _muestra_infractores(conn, nombre, tabla, quote)
            fallidas.append((tabla, nombre, muestra))
            print(f"FALLO {tabla}: {nombre} ({exc.__class__.__name__})")
    if fallidas:
        print(f"\n{len(fallidas)} FKs NO validadas por datos huerfanos:")
        for tabla, nombre, muestra in fallidas:
            print(f"  {tabla}: {nombre}")
            for fila in muestra:
                print(f"    muestra: {fila}")
        print("Corrige los datos y relanza el script (idempotente).")
        return 1
    with engine.connect() as conn:
        restantes = _pendientes(conn, args.tabla)
    assert not restantes, restantes
    print("\nTodas las FKs pendientes quedaron validadas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
