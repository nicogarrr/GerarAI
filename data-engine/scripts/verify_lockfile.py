#!/usr/bin/env python3
"""Verificacion del lockfile de data-engine (uv.lock).

Fuente de verdad de la RESOLUCION: ``data-engine/uv.lock``.
Fuente de verdad de la INTENCION: ``[project].dependencies`` de
``pyproject.toml`` (rangos), que ``requirements.txt`` refleja y que el gate
``dep-parity`` de CI exige ver para las dos.

Los rangos son intencion, no reproducibilidad: dos instalaciones del mismo
commit con rangos pueden resolver distinto. Este script es el que convierte
"hay rangos" en "el lock sigue cubriendo lo que se pide".

Uso:
    python data-engine/scripts/verify_lockfile.py           # CI: sale != 0 si falla
    python data-engine/scripts/verify_lockfile.py --quiet   # sin el informe

Falla (exit 1) si:
  1. requirements.txt y pyproject.toml derivan (delega en
     ``sync_requirements.py --check``: la paridad declarada tiene que ir antes).
  2. El lock no declara una dependencia directa que requirements.txt pide.
  3. El lock declara una dependencia directa que requirements.txt ya no pide
     (incluye las extras `[project.optional-dependencies]`: si se anade una
     dependencia sin re-locar, el lock queda mintiendo).
  4. La version fijada de un paquete no satisface el rango declarado.
  5. A un paquete del lock le falta el hash de su distribucion, o no tiene
     ninguna distribucion fijada: sin hash no hay verificacion de integridad.
  6. La version de interprete que declara el lock no es la fijada en
     `.python-version`, o `requires-python` de pyproject no la contiene.
  7. la familia torch (torch y torchvision) no queda en su pin CPU-only
     (`TORCH_CPU_PIN` / `TORCHVISION_CPU_PIN`): torchvision compila contra la
     ABI de torch y la wheel de PyPI revienta con "operator torchvision::nms
     does not exist" sobre un torch +cpu (run 41259298388 del job Evals).

Ademas AVISA (no falla, exit 0) si el interprete que ejecuta el script no es el
fijado: el diagnostico de este repo se hace sobre 3.11 mientras el runtime
declarado es 3.12, y un rojo aqui seria ruido en lugar de senal.
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Reutilizado a proposito: sync_requirements.py ya sabe normalizar nombres y
# cargar pyproject/requirements. El pin de torch CPU tiene UNA sola definicion
# (TORCH_CPU_PIN) y este script la reutiliza en vez de copiarla.
import sync_requirements as sr

ROOT = sr.ROOT
LOCK = ROOT / "uv.lock"
PYPROJECT_VERSION_FILE = ROOT / ".python-version"
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
TORCH_PINNED = sr.TORCH_CPU_PIN.split("==", 1)[1]
TORCHVISION_PINNED = sr.TORCHVISION_CPU_PIN.split("==", 1)[1]

# La familia torch va entera al indice CPU de PyTorch: torch porque es el
# runtime (TORCH_CPU_PIN, el mismo de los Dockerfile) y torchvision porque
# compila contra la ABI de torch. torchvision es transitiva (docling): nadie
# mas la fija, y el run 41259298388 del job Evals cayo justo por eso (uv la
# resolvio de PyPI y el import de sentence_transformers reventaba).
TORCH_FAMILY = (
    (
        "torch",
        TORCH_PINNED,
        "TORCH_CPU_PIN",
        "Dockerfile, Dockerfile.prod y sync_requirements.py usan ese pin",
    ),
    (
        "torchvision",
        TORCHVISION_PINNED,
        "TORCHVISION_CPU_PIN",
        "compila contra la ABI de torch; ver sync_requirements.py",
    ),
)

_COMPARATOR_RE = re.compile(r"(===|==|~=|!=|>=|<=|>|<)\s*([^,;\s]+)")


class LockError(Exception):
    """Fallo de verificacion que no se puede atribuir a un campo concreto."""


# --------------------------------------------------------------------------
# Versiones: comparacion por segmento de release (stdlib only)
# --------------------------------------------------------------------------
def release_tuple(version: str) -> tuple[int, ...]:
    """Segmento de release de una version PEP 440: '2.9.1+cpu' -> (2, 9, 1).

    Se compara el segmento de release a proposito: es lo que deciden los
    rangos que usa este repo (los tags .postN/.rcN no aparecen en los rangos,
    y un tag nunca debe hacer fallar un '>=' por debajo del numero de release).
    """
    head = version.strip().split("+", 1)[0]
    out: list[int] = []
    for part in head.split("."):
        digits = re.match(r"\d+", part)
        if not digits:
            break
        out.append(int(digits.group(0)))
    if not out:
        raise LockError(f"version no parseable: {version!r}")
    return tuple(out)


def pad(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def cmp_versions(a: str, b: str) -> int:
    ta, tb = pad(release_tuple(a), release_tuple(b))
    return (ta > tb) - (ta < tb)


def satisfies(version: str, spec: str) -> bool:
    """¿version satisface spec? Subconjunto de PEP 440 que requirements.txt usa.

    Se soporta lo que `sync_requirements.py` genera y `pyproject.toml` declara:
    >=, <=, >, <, ==, !=, ~= y listas separadas por coma. Cualquier otra cosa
    falla en cerrado (LockError) en vez de devolver True por descuido: un
    verificador de lock que no sabe comparar no puede afirmar que el lock vale.
    """
    spec = (spec or "").strip()
    if spec in ("", "*"):
        return True
    leftover = spec
    for op, raw in _COMPARATOR_RE.findall(spec):
        leftover = leftover.replace(f"{op} {raw}", "", 1).replace(f"{op}{raw}", "", 1)
        if raw.endswith(".*"):
            # '==3.12.*' / '!=3.12.*': prefijo de segmentos.
            prefix = release_tuple(raw[:-2])
            cur = release_tuple(version)
            ok = cur[: len(prefix)] == prefix
            if op == "!=":
                ok = not ok
            elif op != "==":
                raise LockError(f"comodador de prefijo sin soporte: {op}{raw!r}")
            if not ok:
                return False
            continue
        c = cmp_versions(version, raw)
        target = release_tuple(raw)
        ok = {
            "===": c == 0,
            "==": c == 0,
            "!=": c != 0,
            ">=": c >= 0,
            "<=": c <= 0,
            ">": c > 0,
            "<": c < 0,
            # PEP 440: '~=3.1.0' es '>=3.1.0, ==3.1.*' y '~=3.1' es '>=3.1, ==3.*'.
            # O sea, se compara el prefijo que SOBRA tras quitar el ultimo
            # segmento del pin, no los dos primeros a pelo (eso rechazaria
            # 3.9 para '~=3.1', que si es compatible).
            "~=": c >= 0 and release_tuple(version)[: len(target) - 1] == target[: len(target) - 1],
        }[op]
        if not ok:
            return False
    if leftover.strip(" ,"):
        raise LockError(f"especificador no parseable: {spec!r}")
    return True


def pins_exactly_one_minor(spec: str) -> tuple[int, int] | None:
    """Minor de Python que permite spec, si y solo si permite UNO solo.

    uv normaliza '>=3.12,<3.13' a '==3.12.*' al escribir uv.lock, que es la
    forma que sale. Un lock que admitiera dos minors no fijaria el interprete,
    que es justo lo que se le pide fijar.

    Se reconocen solo las formas que uv escribe (y las equivalentes escritas a
    mano). Cualquier otra falla en cerrado con LockError en vez de devolver
    'no fijar' por una via que no se ha comprobado: este verificador prefiere
    quejarse a afirmar.
    """
    lo: tuple[int, int] | None = None
    hi: tuple[int, int] | None = None
    rest = (spec or "").strip()
    for op, raw in _COMPARATOR_RE.findall(spec):
        rest = rest.replace(f"{op} {raw}", "", 1).replace(f"{op}{raw}", "", 1)
        t = release_tuple(raw)
        minor = (t[0], t[1]) if len(t) >= 2 else (t[0], 0)
        if op in ("==", "==="):
            # '==3.12.*' y '==3.12.10' dejan ambos UNA minor; uv escribe la
            # primera y la segunda solo aparece si alguien la escribe a mano.
            this_lo, this_hi = minor, (minor[0], minor[1] + 1)
        elif op in (">=", "~="):
            this_lo, this_hi = minor, None
        elif op == "<=":
            this_lo, this_hi = None, (minor[0], minor[1] + 1)
        elif op == "<":
            this_lo, this_hi = None, minor
        else:
            raise LockError(
                f"requires-python={spec!r}: operador {op!r} sin soporte para enumerar minors"
            )
        # Interseccion: el piso es el mayor lo, el techo es el menor hi.
        if this_lo is not None and (lo is None or this_lo > lo):
            lo = this_lo
        if this_hi is not None and (hi is None or this_hi < hi):
            hi = this_hi
    if rest.strip(" ,"):
        raise LockError(f"requires-python no parseable: {spec!r}")
    if lo is None or hi is None:
        return None
    # Un minor y solo uno <=> el intervalo [lo, hi) mide exactamente una minor.
    if (hi[0] - lo[0], hi[1] - lo[1]) != (0, 1):
        return None
    return lo


# --------------------------------------------------------------------------
# Carga
# --------------------------------------------------------------------------
def load_lock() -> dict:
    if not LOCK.exists():
        raise LockError(
            f"no existe {LOCK.name}. Generalo con:\n"
            "    cd data-engine && uv lock"
        )
    try:
        return tomllib.loads(LOCK.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise LockError(f"{LOCK.name} no es TOML valido: {exc}") from exc


def locked_index(lock: dict) -> dict[str, dict]:
    return {sr.norm(p["name"]): p for p in lock.get("package", [])}


def root_package(lock: dict) -> dict:
    for p in lock.get("package", []):
        src = p.get("source") or {}
        if not src.get("registry"):
            return p
    raise LockError(f"{LOCK.name}: no encuentro el paquete raiz del proyecto (source no-registry)")


def pinned_python() -> tuple[int, int]:
    if not PYPROJECT_VERSION_FILE.exists():
        raise LockError(
            f"no existe {PYPROJECT_VERSION_FILE.name}. Sin el interprete fijado, "
            "una lockfile no reproduce nada."
        )
    raw = PYPROJECT_VERSION_FILE.read_text(encoding="utf-8").strip()
    t = release_tuple(raw)
    if len(t) < 2:
        raise LockError(f"{PYPROJECT_VERSION_FILE.name}={raw!r}: se espera al menos X.Y")
    return t[0], t[1]


def parse_pyproject() -> dict:
    return tomllib.loads(sr.PYPROJECT.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------
def check_declared_parity(lock: dict, pyproject: dict, errors: list[str]) -> None:
    """pyproject <-> requirements.txt <-> lock[package.metadata].requires-dist.

    El tercer lado es el que faltaba: uv reescribe lo que el proyecto pide a su
    forma normalizada, asi que si requirements.txt se edita a mano y no se
    re-loca, aqui aparece la divergencia (y al re-locarlo, el gate dep-parity
    sigue exigiendo que requirements.txt vuelva a derivar).
    """
    declared = {sr.norm(n): s for n, s in sr.load_pyproject().items()}
    rd = root_package(lock).get("metadata", {}).get("requires-dist", [])
    base: dict[str, str] = {}
    extras: dict[str, dict[str, str]] = {}
    for entry in rd:
        name = sr.norm(entry["name"])
        marker = entry.get("marker") or ""
        m = re.search(r"extra\s*==\s*['\"]([^'\"]+)['\"]", marker)
        if m:
            extras.setdefault(m.group(1), {})[name] = entry.get("specifier", "")
        else:
            base[name] = entry.get("specifier", "")

    for name in sorted(set(base) ^ set(declared)):
        side = "solo en requirements.txt" if name in declared else "solo en el lock"
        errors.append(f"{name}: {side} (requires-dist del lock = {base.get(name, 'AUSENTE')!r})")
    for name in sorted(set(base) & set(declared)):
        if base[name] != declared[name]:
            errors.append(
                f"{name}: el lock resuelve el rango {base[name]!r} y requirements.txt {declared[name]!r}"
            )

    want_extras = pyproject.get("project", {}).get("optional-dependencies", {})
    for group, items in sorted(want_extras.items()):
        want = {sr.norm(sr.split_req(i)[0]): sr.split_req(i)[1] for i in items}
        got = extras.get(group, {})
        for name in sorted(set(want) ^ set(got)):
            errors.append(f"extras[{group}] {name}: solo en " + ("requirements.txt" if name in want else "el lock"))
    for group in sorted(set(extras) - set(want_extras)):
        errors.append(f"el lock declara la extra {group!r}, que pyproject ya no tiene")

    # Segunda pasada sobre [package.optional-dependencies], que es la lista que
    # uv instala de verdad: los marcadores de requires-dist y esta lista tienen
    # que contar lo mismo, asi que un desfase entre ambas (lock editado a mano,
    # o re-locado con extras distintas) sale aqui.
    locked_opt = root_package(lock).get("optional-dependencies") or {}
    for group in sorted(set(want_extras) ^ set(locked_opt)):
        side = "pyproject" if group in want_extras else "el lock"
        errors.append(f"extras[{group}]: solo existe en {side}")
    for group in sorted(set(want_extras) & set(locked_opt)):
        want = {sr.norm(sr.split_req(i)[0]) for i in want_extras[group]}
        got = {sr.norm(d["name"]) for d in locked_opt[group]}
        for name in sorted(want - got):
            errors.append(f"extras[{group}] {name}: pyproject lo pide y el lock no lo instala (falta re-locar)")
        for name in sorted(got - want):
            errors.append(f"extras[{group}] {name}: el lock lo instala y pyproject ya no lo pide")


def check_resolution(lock: dict, errors: list[str]) -> int:
    """Todo lo que se pide, resuelto; y resuelto dentro de los rangos."""
    index = locked_index(lock)
    declared = sr.load_pyproject()
    root_deps = {sr.norm(d["name"]) for d in root_package(lock).get("dependencies", [])}
    n = 0
    for name in sorted(declared):
        n += 1
        pkg = index.get(name)
        if pkg is None:
            errors.append(f"{name}: pedido en requirements.txt, AUSENTE de {LOCK.name} (falta re-locar)")
            continue
        version = pkg["version"]
        if name not in root_deps:
            errors.append(f"{name}: esta en el lock pero no entre las dependencias del proyecto")
        if name == "torch":
            spec = f"=={TORCH_PINNED}"
        else:
            spec = declared[name]
        try:
            ok = satisfies(version, spec)
        except LockError as exc:
            errors.append(f"{name}: {exc} (rango declarado {spec!r})")
            continue
        if not ok:
            errors.append(
                f"{name}: el lock fija {version}, fuera del rango declarado {spec!r}. "
                "Re-loca (uv lock) o corrige el rango; no se puede dejar asado."
            )
    return n


def check_hashes(lock: dict, errors: list[str]) -> tuple[int, int]:
    """Toda distribucion fijada lleva hash, y todo paquete fijado tiene alguna."""
    index = locked_index(lock)
    n_pkgs = n_hashed = 0
    for name, pkg in sorted(index.items()):
        src = pkg.get("source") or {}
        if not src.get("registry"):
            continue  # el paquete raiz (editable) no se descarga.
        n_pkgs += 1
        dists = []
        if pkg.get("sdist"):
            dists.append(("sdist", pkg["sdist"]))
        for w in pkg.get("wheels") or []:
            dists.append(("wheel", w))
        if not dists:
            errors.append(f"{name}=={pkg['version']}: sin sdist ni wheels fijados")
            continue
        for kind, d in dists:
            h = d.get("hash") or ""
            if not h.startswith("sha256:"):
                errors.append(
                    f"{name}=={pkg['version']}: {kind} sin hash sha256 "
                    f"(url={d.get('url', '?')})"
                )
            else:
                n_hashed += 1
    return n_pkgs, n_hashed


def check_torch_cpu(lock: dict, errors: list[str]) -> None:
    """La familia torch del lock tiene que salir entera del indice CPU de PyTorch."""
    index = locked_index(lock)
    constraints = {sr.norm(c["name"]): c for c in (lock.get("manifest") or {}).get("constraints") or []}
    for name, pinned, pin_const, why in TORCH_FAMILY:
        pkg = index.get(name)
        if pkg is None:
            errors.append(f"{name}: AUSENTE del lock (la familia torch se instala CPU-only siempre)")
            continue
        if pkg["version"] != pinned:
            errors.append(f"{name}: el lock fija {pkg['version']} pero {pin_const} es {pinned} ({why})")
        src = (pkg.get("source") or {}).get("registry")
        if src != TORCH_INDEX:
            errors.append(f"{name}: el lock lo saca de {src!r}, no del indice CPU de PyTorch ({TORCH_INDEX})")
        got = constraints.get(name, {}).get("specifier")
        if got != f"=={pinned}":
            errors.append(
                f"{name}: el lock no registra la constraint '=={pinned}' "
                f"(manifest.constraints dice {got!r}); sin ella un 'uv lock --upgrade' "
                f"flotaria {name} por encima del pin CPU-only"
            )


def check_interpreter(lock: dict, pyproject: dict, errors: list[str], warns: list[str]) -> tuple[int, int]:
    want = pinned_python()
    lock_spec = (lock.get("requires-python") or "").strip()
    try:
        got = pins_exactly_one_minor(lock_spec)
    except LockError as exc:
        errors.append(f"{LOCK.name}: requires-python={lock_spec!r}: {exc}")
    else:
        if got is None:
            errors.append(
                f"{LOCK.name}: requires-python={lock_spec!r} no fija un unico minor de Python; "
                f"se exige exactamente {'.'.join(map(str, want))}"
            )
        elif got != want:
            errors.append(
                f"{LOCK.name} resuelve para Python {got[0]}.{got[1]}, "
                f"pero la version fijada es {want[0]}.{want[1]} (.python-version)"
            )
    declared = pyproject.get("project", {}).get("requires-python", "")
    try:
        if not satisfies(f"{want[0]}.{want[1]}.99", declared):
            errors.append(
                f"requires-python={declared!r} de pyproject.toml no contiene "
                f"la version fijada {want[0]}.{want[1]}"
            )
    except LockError as exc:
        errors.append(f"pyproject requires-python={declared!r}: {exc}")
    running = sys.version_info
    if (running.major, running.minor) != want:
        warns.append(
            f"estás ejecutando el verificador con Python {running.major}.{running.minor}.{running.micro} "
            f"y el runtime declarado es {want[0]}.{want[1]}; el lock sigue siendo valido para "
            f"{want[0]}.{want[1]}, pero la suite NO se puede considerar verde en {running.major}.{running.minor}"
        )
    return want


# --------------------------------------------------------------------------
def main() -> int:
    quiet = "--quiet" in sys.argv[1:]
    errors: list[str] = []
    warns: list[str] = []
    notes: list[str] = []
    if sr.check() != 0:
        errors.append(
            "requirements.txt y pyproject.toml derivan: arregla eso primero "
            "(python data-engine/scripts/sync_requirements.py --write)"
        )
    else:
        try:
            lock = load_lock()
            pyproject = parse_pyproject()
            want = check_interpreter(lock, pyproject, errors, warns)
            check_declared_parity(lock, pyproject, errors)
            n_declared = check_resolution(lock, errors)
            n_pkgs, n_hashed = check_hashes(lock, errors)
            check_torch_cpu(lock, errors)
            extras = sorted(pyproject.get("project", {}).get("optional-dependencies", {}))
            notes.append(f"paquetes fijados en el lock: {len(lock.get('package', []))}")
            notes.append(f"directas verificadas contra requirements.txt: {n_declared}")
            notes.append(f"paquetes de registro con distribucion hasheada: {n_pkgs}")
            notes.append(f"distribuciones hasheadas en total: {n_hashed}")
            notes.append(f"interprete fijado: Python {want[0]}.{want[1]}")
            notes.append(f"extras declaradas: {', '.join(extras)}")
        except LockError as exc:
            errors.append(str(exc))

    for w in warns:
        print(f"AVISO: {w}")
    if errors:
        print(f"Lockfile ROTO ({len(errors)} problema(s)):")
        for e in errors:
            print(f"  - {e}")
        print("Arregla y re-loca con: cd data-engine && uv lock")
        return 1
    if not quiet:
        print("Lockfile OK.")
        for n in notes:
            print(f"  {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())