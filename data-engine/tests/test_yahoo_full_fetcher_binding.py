"""The default full Yahoo fetcher must honor runtime injection, without live I/O."""
from types import SimpleNamespace

from app.services import yahoo_fundamentals_service as service


def test_full_default_resolves_fetcher_at_call_time(monkeypatch):
    injected = object()
    monkeypatch.setattr(service, '_fetch_yahoo', injected)
    monkeypatch.setattr(service, 'full_entry', lambda db, company: {'symbol': 'ZZTEST'})

    def capture(db, company, entry, *, fetcher, commit):
        assert fetcher is injected
        assert commit is False
        return {'injected': True}

    monkeypatch.setattr(service, '_refresh', capture)
    assert service.refresh_full_from_yahoo(None, SimpleNamespace(ticker='ZZTEST'), commit=False) == {'injected': True}
