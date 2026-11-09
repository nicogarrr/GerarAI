"""ingest_industry_peers: --dry-run real en el paso de afines de negocio.

Hallazgo del auditor (main 419a8218): con --affinity-only --dry-run el CLI
entraba en _affinity sin mirar dry_run, y _affinity descarga fuentes, cambia
tags y hace db.commit. Estos tests fijan que con dry no se descarga, no se
tocan tags y no hay commit, y que sin dry la ruta se ejecuta como antes.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def _cargar():
    path = Path(__file__).resolve().parent.parent / "scripts" / "ingest_industry_peers.py"
    spec = importlib.util.spec_from_file_location("ingest_industry_peers", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _miembro(cik: str, ticker: str, sic: int = 3663):
    return SimpleNamespace(cik=cik, ticker=ticker, name=ticker, factor_tags=[f"sic:{sic}"], industry=None)


def _db_falso(members):
    class _Scalars:
        def all(self):
            return members

    return SimpleNamespace(
        info={},
        scalars=lambda _q: _Scalars(),
        commits=[],
        commit=lambda: None,
        rollback=lambda: None,
        close=lambda: None,
    )


def _preparar(mod, monkeypatch, members):
    """Espías en la descarga, el etiquetado y el commit; miembros del grupo fijos."""
    db = _db_falso(members)
    llamadas = {"describe": [], "tag": [], "commit": 0}
    db.commit = lambda: llamadas.__setitem__("commit", llamadas["commit"] + 1)
    monkeypatch.setattr(
        mod.ba, "describe", lambda cik, name, get: llamadas["describe"].append(cik) or {"tokens": ["x"]}
    )
    monkeypatch.setattr(mod.ba, "affine_sets", lambda docs: {})
    monkeypatch.setattr(mod.ba, "tag_affine", lambda c, sets: llamadas["tag"].append(c.ticker) or 0)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    return db, llamadas


def test_affinity_dry_run_no_descarga_ni_tagea_ni_commitea(monkeypatch):
    mod = _cargar()
    members = [
        _miembro("0000897061", "MSFT"),
        _miembro("0000320193", "AAPL"),
        _miembro("0000000001", "FUERA", 9999),
    ]
    db, llamadas = _preparar(mod, monkeypatch, members)
    out = mod._affinity(db, ((3663, 3663),), True)
    assert llamadas == {"describe": [], "tag": [], "commit": 0}
    assert out["dry_run"] is True and out["members"] == 2 and out["tickers"] == ["AAPL", "MSFT"]
    assert "no se descarga" in out["accion"]


def test_affinity_sin_dry_descarga_tagea_y_commitea(monkeypatch):
    """El flag llega: sin dry la ruta se ejecuta (mata el mutante siempre-dry)."""
    mod = _cargar()
    members = [_miembro("0000897061", "MSFT")]
    db, llamadas = _preparar(mod, monkeypatch, members)
    out = mod._affinity(db, ((3663, 3663),), False)
    assert llamadas["describe"] == [897061]
    assert llamadas["tag"] == ["MSFT"]
    assert llamadas["commit"] == 1
    assert out["members"] == 1 and "dry_run" not in out


def test_main_affinity_only_dry_run_no_llama_la_ruta(monkeypatch, capsys):
    """El probe del auditor: ['--sic','3663','--affinity-only','--dry-run'] no llama a la ruta."""
    mod = _cargar()
    members = [_miembro("0000897061", "MSFT")]
    db, llamadas = _preparar(mod, monkeypatch, members)
    monkeypatch.setattr(mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        mod.sys, "argv", ["ingest_industry_peers.py", "--sic", "3663", "--affinity-only", "--dry-run"]
    )
    mod.main()
    assert llamadas == {"describe": [], "tag": [], "commit": 0}
    salida = json.loads(capsys.readouterr().out)
    assert salida["dry_run"] is True and salida["members"] == 1
