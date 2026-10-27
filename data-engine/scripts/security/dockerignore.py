"""Contexto de build tal y como lo ve el demonio: replica de `.dockerignore`.

Un `.dockerignore` mal puesto mete el `.env`, el `.venv` o `node_modules` dentro de
la imagen sin que ningun test lo note: el fichero se copia con `COPY . .`, el
escaneo de secrets lo ve como un hallazgo y para entonces el secreto ya esta en
la historia de la imagen (borrarlo despues no lo borra).

Para poder comprobarlo en un test (que no puede depender de docker) se replica la
semantica real de docker. Comprobada contra el daemon con un contexto de prueba y
el `.dockerignore` de este repo:

    patron `.env`       excluye `.env` y, por el prune del walk, todo lo que cuelgue
    patron `*.md`       solo casa en la raiz: NO es un glob recursivo
    patron `data-engine/.venv/`  excluye ese arbol (la barra final se limpia)
    patron `!README.md` re-incluye tras un `*.md` previo (gana el ultimo que casa)

Soporta `**/` como cero o mas directorios y `**` como cualquier ruta.
No intenta replicar el matiz de `MatchesOrParentMatches` para negaciones posterior al
prune, donde docker no rescata un fichero dentro de un directorio ya excluido y
este modulo tampoco.

Uso:

    python -m scripts.security.dockerignore . --context .
    python -m scripts.security.dockerignore data-engine --context data-engine
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Nombres/patrones que jamas deben entrar en un contexto de build.
DEFAULT_FORBIDDEN_DIRS = (
    ".env",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".next",
)
DEFAULT_FORBIDDEN_GLOBS = (
    ".env.*",
    "*.duckdb",
    "*.duckdb.wal",
    "*.sqlite",
    "*.sqlite3",
    "*.pem",
    "*.key",
    "*.p12",
    "id_rsa*",
)


@dataclass(frozen=True)
class Pattern:
    text: str
    negated: bool


@lru_cache(maxsize=512)
def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Traduce un glob estilo Go (`*` no cruza `/`) a una regex."""
    out = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 1
                if index + 1 < len(pattern) and pattern[index + 1] == "/":
                    out.append("(?:.*/)?")
                    index += 1
                else:
                    out.append(".*")
            else:
                out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            close = pattern.find("]", index + 1)
            if close == -1:
                out.append(re.escape(char))
            else:
                body = pattern[index + 1 : close]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body + "]")
                index = close
        else:
            out.append(re.escape(char))
        index += 1
    out.append("$")
    return re.compile("".join(out))


def parse_patterns(text: str) -> list[Pattern]:
    patterns: list[Pattern] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:].strip()
        line = line.rstrip("/").lstrip("/")
        if line.startswith("./"):
            line = line[2:]
        if line:
            patterns.append(Pattern(text=line, negated=negated))
    return patterns


def read_patterns(dockerignore: Path) -> list[Pattern]:
    return parse_patterns(dockerignore.read_text(encoding="utf-8"))


def _matches(pattern: Pattern, path: str) -> bool:
    if pattern.text == path or path.startswith(pattern.text + "/"):
        return True
    return bool(_glob_to_regex(pattern.text).match(path))


def _resolved(path: str, patterns: list[Pattern]) -> bool:
    excluded = False
    for pattern in patterns:
        if _matches(pattern, path):
            excluded = not pattern.negated
    return excluded


def is_excluded(path: str, patterns: list[Pattern]) -> bool:
    """Path relativo posix. True si docker no lo enviaria en el contexto."""
    clean = path.replace("\\", "/").strip()
    while clean.startswith("./"):
        clean = clean[2:]
    clean = clean.lstrip("/")
    if not clean:
        return False
    parts = clean.split("/")
    # Un directorio excluido no se recorre: una negacion posterior no lo rescata.
    for depth in range(1, len(parts)):
        if _resolved("/".join(parts[:depth]), patterns):
            return True
    return _resolved(clean, patterns)


def leaked(
    context: Path,
    forbidden_dirs: tuple[str, ...],
    forbidden_globs: tuple[str, ...],
) -> list[str]:
    """Ficheros del contexto que yo no deberia querer dentro de la imagen.

    Poda los directorios ya excluidos igual que hace el demonio: sin eso,
    recorrer la raiz del repo entra en node_modules y .git (cientos de miles de
    ficheros) para acabar descartandolos.
    """
    dockerignore = context / ".dockerignore"
    patterns = read_patterns(dockerignore) if dockerignore.is_file() else []
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(context):
        relative = Path(dirpath).relative_to(context)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not is_excluded((relative / name).as_posix(), patterns)
        )
        for name in sorted(filenames):
            path = (relative / name).as_posix()
            if is_excluded(path, patterns):
                continue
            parts = Path(path).parts
            prohibido = any(part in forbidden_dirs for part in parts) or any(
                _glob_to_regex(glob).match(name) for glob in forbidden_globs
            )
            if prohibido:
                found.append(path)
    return found


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("uso: python -m scripts.security.dockerignore <contexto> [...]")
        return 2
    failures = 0
    for raw in args:
        context = Path(raw)
        dockerignore = context / ".dockerignore"
        print(f"== {context} (.dockerignore: {'si' if dockerignore.is_file() else 'NO'})")
        found = leaked(context, DEFAULT_FORBIDDEN_DIRS, DEFAULT_FORBIDDEN_GLOBS)
        for path in found:
            print(f"  FUGA  {path}")
        if not found:
            print("  sin fugas (.env / .venv / node_modules / caches / claves fuera del contexto)")
        failures += len(found)
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - entrypoint de CLI
    sys.exit(main())