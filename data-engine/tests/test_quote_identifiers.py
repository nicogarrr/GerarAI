"""_quote_identifiers: escape de comillas dobles en identificadores SQL.

Sin el escape, una columna con '"' en su nombre romperia el literal
INSERT ... SELECT de la migracion de thesis_versions (B608).
"""

from __future__ import annotations

import sqlite3

from app.core.database import _quote_identifiers


def test_plain_names_are_double_quoted():
    assert _quote_identifiers(["id", "value"]) == ['"id"', '"value"']


def test_embedded_double_quote_is_escaped_and_usable():
    weird = 'col"with"quotes'
    quoted = _quote_identifiers(["id", weird])
    assert quoted[1] == '"col""with""quotes"'
    conn = sqlite3.connect(":memory:")
    conn.execute(f'CREATE TABLE src ({", ".join(f"{q} TEXT" for q in quoted)})')  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- test local sqlite :memory:, SQL construido solo con identificadores fijos del test
    conn.execute(f'INSERT INTO src ({", ".join(quoted)}) VALUES (\'a\', \'b\')')  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- test local sqlite :memory:, SQL construido solo con identificadores fijos del test
    conn.execute(f'CREATE TABLE dst ({", ".join(f"{q} TEXT" for q in quoted)})')  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- test local sqlite :memory:, SQL construido solo con identificadores fijos del test
    conn.execute(f"INSERT INTO dst ({', '.join(quoted)}) SELECT {', '.join(quoted)} FROM src")  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- test local sqlite :memory:, SQL construido solo con identificadores fijos del test
    assert conn.execute("SELECT * FROM dst").fetchall() == [("a", "b")]
