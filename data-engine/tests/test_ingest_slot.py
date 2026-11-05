"""Semaforo de concurrencia de ingesta: contadores deterministas, sin reloj."""
from __future__ import annotations

import threading

from app.workers.ingest_slot import (
    DocumentIngestSlot,
    document_ingest_slot,
    reset_document_ingest_slot,
)


def test_serializa_dos_hilos_con_limite_uno():
    slot = DocumentIngestSlot(1)
    entered_a = threading.Event()
    release_a = threading.Event()
    entered_b = threading.Event()
    done_b = threading.Event()

    def worker_a():
        with slot.hold():
            entered_a.set()
            release_a.wait(10)

    def worker_b():
        entered_b.set()
        with slot.hold():
            done_b.set()

    ta = threading.Thread(target=worker_a)
    tb = threading.Thread(target=worker_b)
    ta.start()
    assert entered_a.wait(10)
    tb.start()
    assert entered_b.wait(10)
    # B esta dentro de hold() pero bloqueado: la sonda no bloqueante lo prueba
    # de forma determinista (sin sleeps ni reloj).
    assert not slot.try_hold()
    assert slot.max_active == 1
    release_a.set()
    ta.join(10)
    tb.join(10)
    assert done_b.is_set()
    assert slot.acquired == 2
    assert slot.max_active == 1


def test_limite_dos_admite_dos_pero_no_tres():
    slot = DocumentIngestSlot(2)
    a = threading.Event()
    b = threading.Event()
    release = threading.Event()

    def worker(ev):
        with slot.hold():
            ev.set()
            release.wait(10)

    ta = threading.Thread(target=worker, args=(a,))
    tb = threading.Thread(target=worker, args=(b,))
    ta.start()
    tb.start()
    assert a.wait(10) and b.wait(10)
    assert not slot.try_hold()
    assert slot.max_active == 2
    release.set()
    ta.join(10)
    tb.join(10)


def test_limite_invalido_rechazado():
    import pytest

    with pytest.raises(ValueError):
        DocumentIngestSlot(0)


def test_singleton_respeta_setting_y_se_recrea_al_cambiar(monkeypatch):
    reset_document_ingest_slot()
    uno = document_ingest_slot(1)
    assert document_ingest_slot(1) is uno
    dos = document_ingest_slot(2)
    assert dos is not uno and dos.limit == 2
    reset_document_ingest_slot()
