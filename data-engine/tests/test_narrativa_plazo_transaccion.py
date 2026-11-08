"""La narrativa extensa no pierde la sesión mientras espera al modelo.

Antes: la narrativa corre dentro de la transacción de la tesis; con una llamada de más de 120 s Postgres cortaba la
conexión «idle in transaction», el INSERT del gasto fallaba y el job entero acababa en PendingRollbackError
(8-nov-2026, 20 de 24 tesis del lote sobre main 995ed3fca). Ahora la transacción amplía su propio plazo antes de la
llamada.
"""
from types import SimpleNamespace

from app.services import thesis_deep_narrative as N


class _Db:
    def __init__(self, dialect: str = "postgresql"):
        self.calls: list[str] = []
        self._dialect = dialect

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name=self._dialect))

    def execute(self, stmt, *a, **k):
        self.calls.append(str(stmt))


def test_amplia_el_plazo_de_la_transaccion_en_postgres():
    db = _Db()
    N.allow_slow_call(db)
    assert db.calls == ["SET LOCAL idle_in_transaction_session_timeout = 900000"]


def test_no_toca_otros_motores():
    db = _Db("sqlite")
    N.allow_slow_call(db)
    assert db.calls == []


def test_la_narrativa_amplia_el_plazo_antes_de_llamar_al_modelo(monkeypatch):
    db = _Db()
    order: list[str] = []

    class _Provider:
        name = "fake"

        async def complete(self, request):
            order.append("llamada" if any("SET LOCAL" in c for c in db.calls) else "llamada_sin_plazo")
            raise RuntimeError("fin")

    class _Budget:
        def can_spend(self, *a, **k):
            return True

    monkeypatch.setattr(N, "fact_pack", lambda *a, **k: [{"id": i} for i in range(3)])
    monkeypatch.setattr(N, "_resolve_fact_locators", lambda *a, **k: {})
    monkeypatch.setattr(N, "BudgetController", _Budget)
    monkeypatch.setattr(N, "_build_request", lambda facts, note: object())
    company = SimpleNamespace(ticker="X", name="X")
    assert N.maybe_deep_narrative(db, company, {}, {}, None, [], provider=_Provider()) is None
    assert order == ["llamada"]
