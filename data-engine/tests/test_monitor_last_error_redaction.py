"""last_error de los monitores Form 4 y 13D/G se guarda redactado (como #2900/#2864)."""

from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models.entities import ConnectorState
from app.services import insider_monitor, schedule13dg_monitor

SECRET = "https://user:hunter2@efts.sec.gov/LATEST/search?apikey=SUPERSECRET123"


def _boom(*_args, **_kwargs):
    raise RuntimeError(f"connect failed: {SECRET} password=dbpass99")


def _state(db, connector):
    return db.scalar(select(ConnectorState).where(ConnectorState.connector == connector))


def _clean(db, connector):
    db.query(ConnectorState).filter(ConnectorState.connector == connector).delete()
    db.commit()


def _assert_redacted(text: str) -> None:
    assert "SUPERSECRET123" not in text
    assert "hunter2" not in text
    assert "dbpass99" not in text
    assert "REDACTED" in text


def _check(monkeypatch, module, connector, *, stats_con_detalle: bool):
    init_db()
    db = SessionLocal()
    try:
        _clean(db, connector)
        monkeypatch.setattr(module, "watchlist_tickers", _boom)
        stats = module.scan(db, delay_seconds=0)
        assert stats["status"] == "error"
        state = _state(db, connector)
        assert state.consecutive_errors == 1
        # last_error (persistido para ops, no se sirve en ninguna respuesta):
        # detalle con secretos redactados, como mandaron #2900/#2864.
        _assert_redacted(state.last_error)
        assert state.last_error.startswith("RuntimeError: connect failed")
        if stats_con_detalle:
            _assert_redacted(" ".join(state.metadata_["last_run"]["errors"]))
            _assert_redacted(" ".join(stats["errors"]))
        else:
            # stats SI se sirve en la API (ownership.scan): solo razon
            # publica constante, nada derivado de la excepcion.
            errores = " ".join(stats["errors"])
            assert "schedule13dg_scan_fatal" in errores
            assert "RuntimeError" not in errores
            assert "SUPERSECRET123" not in errores
            assert "hunter2" not in errores
            assert "dbpass99" not in errores
            assert errores == " ".join(state.metadata_["last_run"]["errors"])
    finally:
        _clean(db, connector)
        db.close()


def test_insider_monitor_redacta_last_error(monkeypatch):
    # insider_monitor.scan no se sirve en ninguna ruta: su stats conserva el
    # detalle redactado (cubierto arriba); si una ruta lo expone, hay que
    # pasarlo a razon constante como en schedule13dg_monitor.
    _check(monkeypatch, insider_monitor, insider_monitor.CONNECTOR_NAME, stats_con_detalle=True)


def test_schedule13dg_monitor_redacta_last_error(monkeypatch):
    _check(monkeypatch, schedule13dg_monitor, schedule13dg_monitor.CONNECTOR_NAME,
           stats_con_detalle=False)
