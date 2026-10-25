from __future__ import annotations

import pytest

from app.services.document_store import DocumentStore


class FakeMinio:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.objects: list[tuple[str, str, bytes, str]] = []
        self.removed: list[tuple[str, str]] = []

    def bucket_exists(self, bucket: str) -> bool:
        return bool(self.objects)

    def make_bucket(self, bucket: str) -> None:
        self.created.append(bucket)

    def put_object(self, bucket, object_name, stream, *, length, content_type):
        self.objects.append((bucket, object_name, stream.read(length), content_type))

    def remove_object(self, bucket, object_name):
        self.removed.append((bucket, object_name))

    def list_objects(self, bucket, *, prefix="", recursive=False):
        for item in self.objects:
            if item[0] != bucket or not item[1].startswith(prefix):
                continue
            yield type("Object", (), {"object_name": item[1]})()


def test_document_store_uses_tenant_scoped_minio_original(monkeypatch):
    store = DocumentStore()
    store.settings.app_env = "production"
    store.settings.document_storage_backend = "minio"
    fake = FakeMinio()
    monkeypatch.setattr(store, "_client", lambda: fake)

    uri = store.put_bytes(
        "msft",
        "filing",
        "../10-k.pdf",
        b"immutable-original",
        tenant_id=17,
        content_type="application/pdf",
    )

    assert uri == "minio://research/tenant-17/MSFT/filing/.._10-k.pdf"
    assert fake.created == ["research"]
    assert fake.objects == [
        ("research", "tenant-17/MSFT/filing/.._10-k.pdf", b"immutable-original", "application/pdf")
    ]


def test_document_store_rejects_unscoped_minio_write():
    store = DocumentStore()
    store.settings.app_env = "production"
    store.settings.document_storage_backend = "minio"

    try:
        store.put_bytes("MSFT", "filing", "10-k.pdf", b"raw")
    except ValueError as exc:
        assert "Tenant context" in str(exc)
    else:
        raise AssertionError("Unscoped document write should fail")


def test_document_store_rejects_local_originals_in_production():
    store = DocumentStore()
    store.settings.app_env = "production"
    store.settings.document_storage_backend = "local"

    try:
        store.put_bytes("MSFT", "filing", "10-k.pdf", b"raw", tenant_id=17)
    except RuntimeError as exc:
        assert "must use MinIO" in str(exc)
    else:
        raise AssertionError("Production must not accept local canonical originals")


@pytest.mark.parametrize(
    ("ticker", "category", "filename"),
    [
        (".", "filing", "doc.pdf"),
        ("..", "filing", "doc.pdf"),
        ("MSFT", ".", "doc.pdf"),
        ("MSFT", "..", "doc.pdf"),
        ("MSFT", "filing", "."),
        ("MSFT", "filing", ".."),
        ("folder/../outside", "filing", "doc.pdf"),
        ("/outside", "filing", "doc.pdf"),
        (r"\outside", "filing", "doc.pdf"),
        (r"C:\outside", "filing", "doc.pdf"),
    ],
)
def test_document_store_rejects_unsafe_local_path_components(
    tmp_path, ticker, category, filename
):
    store = DocumentStore()
    store.local_root = tmp_path / "storage" / "raw"

    with pytest.raises(ValueError, match="local document storage"):
        store.put_bytes_local(
            ticker,
            category,
            filename,
            b"raw",
            tenant_id=17,
        )


def test_document_store_rejects_local_symlink_escape(tmp_path):
    raw_root = tmp_path / "storage" / "raw"
    outside = tmp_path / "outside"
    tenant_link = raw_root / "tenant-17"
    raw_root.mkdir(parents=True)
    outside.mkdir()
    try:
        tenant_link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlinks are not available: {exc}")

    store = DocumentStore()
    store.local_root = raw_root

    with pytest.raises(ValueError, match="local document storage"):
        store.put_bytes_local(
            "MSFT",
            "filing",
            "escaped.pdf",
            b"raw",
            tenant_id=17,
        )

    assert not (outside / "filing" / "escaped.pdf").exists()
    assert not (outside / "filing").exists()

def test_document_store_deletes_minio_object_and_tenant_prefix(monkeypatch):
    store = DocumentStore()
    store.settings.app_env = "production"
    store.settings.document_storage_backend = "minio"
    fake = FakeMinio()
    monkeypatch.setattr(store, "_client", lambda: fake)

    uri = store.put_bytes(
        "MSFT", "filing", "10-k.pdf", b"raw", tenant_id=7
    )
    assert store.delete(uri) is True
    assert fake.removed == [("research", "tenant-7/MSFT/filing/10-k.pdf")]

    fake.objects[:] = [
        ("research", "tenant-7/MSFT/filing/10-k.pdf", b"raw", "application/pdf"),
        ("research", "tenant-8/MSFT/filing/10-k.pdf", b"raw", "application/pdf"),
    ]
    assert store.delete_tenant_prefix(7) == 1
    assert fake.removed == [
        ("research", "tenant-7/MSFT/filing/10-k.pdf"),
        ("research", "tenant-7/MSFT/filing/10-k.pdf"),
    ]
    assert all(not name.startswith("tenant-8/") for _, name in fake.removed)


def test_document_store_delete_is_idempotent_and_rejects_escape(tmp_path):
    store = DocumentStore()
    store.local_root = tmp_path / "storage" / "raw"
    path = store.put_bytes_local("MSFT", "filing", "10-k.pdf", b"raw", tenant_id=9)
    assert store.delete(path) is True
    assert store.delete(path) is False

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"do-not-delete")
    with pytest.raises(ValueError, match="local document storage"):
        store.delete(str(outside))
    assert outside.exists()
