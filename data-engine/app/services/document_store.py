import re
import shutil
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath

from minio import Minio

from app.core.config import get_settings


class DocumentStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.local_root = Path("storage/raw")

    def _client(self) -> Minio:
        secure = self.settings.minio_endpoint.startswith("https://")
        endpoint = self.settings.minio_endpoint.replace("http://", "").replace("https://", "")
        return Minio(
            endpoint,
            access_key=self.settings.minio_access_key,
            secret_key=self.settings.minio_secret_key,
            secure=secure,
            # Con region explicita el SDK no consulta GetBucketLocation: Garage
            # (compatible S3) la fija en su config.
            region=self.settings.minio_region or None,
        )

    def put_bytes_local(
        self,
        ticker: str,
        category: str,
        filename: str,
        content: bytes,
        tenant_id: int | None = None,
    ) -> str:
        self._validate_local_component(ticker)
        self._validate_local_component(category)
        self._validate_local_component(filename)

        root = self.local_root.resolve()
        # Reconstruye la ruta SOLO con componentes que pasan una whitelist
        # estricta (re.fullmatch): es el guard que CodeQL reconoce como
        # sanitizador de py/path-injection. Los chequeos sobre los valores
        # crudos (arriba) no bastan: el path se deriva de _safe_*.
        parts = self._directory(ticker, category, tenant_id).relative_to(
            self.local_root
        ).parts
        directory = self.local_root
        for part in parts:
            self._validate_path_component(part)
            directory = directory / part
        filename_safe = self._safe_filename(filename)
        self._validate_path_component(filename_safe)
        # Validate every existing parent before mkdir: a pre-existing symlink
        # must be rejected before it can cause an out-of-root directory write.
        candidate = root
        for part in parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise ValueError("Unsafe local document storage path")
        path = (directory / filename_safe).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise ValueError("Unsafe local document storage path") from None
        directory.mkdir(parents=True, exist_ok=True)

        path.write_bytes(content)
        return str(path)

    def put_bytes(
        self,
        ticker: str,
        category: str,
        filename: str,
        content: bytes,
        tenant_id: int | None = None,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Persist an immutable original; production uses MinIO as canonical storage."""
        if (
            self.settings.app_env.lower() in {"production", "prod"}
            and self.settings.document_storage_backend != "minio"
        ):
            raise RuntimeError("Production document originals must use MinIO")
        if self.settings.app_env == "test" or self.settings.document_storage_backend == "local":
            return self.put_bytes_local(ticker, category, filename, content, tenant_id)
        if tenant_id is None:
            raise ValueError("Tenant context is required to store a document")

        bucket = self.settings.minio_bucket
        object_name = "/".join(
            [
                self._safe_path_part(f"tenant-{tenant_id}"),
                self._safe_path_part(ticker.upper()),
                self._safe_path_part(category),
                self._safe_filename(filename),
            ]
        )
        client = self._client()
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        client.put_object(
            bucket,
            object_name,
            BytesIO(content),
            length=len(content),
            content_type=content_type,
        )
        return f"minio://{bucket}/{object_name}"

    def delete(self, storage_uri: str | None) -> bool:
        """Borra el original apuntado por ``storage_uri`` (idempotente).

        Acepta las dos formas que produce esta clase: ``minio://bucket/key``
        y una ruta local absoluta dentro de ``storage/raw``. Un objeto que ya
        no existe devuelve ``False`` sin error; una URI fuera del almacen es
        un error de seguridad, nunca un borrado silencioso de otro fichero.
        """
        if not storage_uri:
            return False
        if storage_uri.startswith("minio://"):
            bucket, _, object_name = storage_uri[len("minio://"):].partition("/")
            if not bucket or not object_name:
                raise ValueError("Unsafe document storage URI")
            client = self._client()
            if not client.bucket_exists(bucket):
                return False
            client.remove_object(bucket, object_name)
            return True

        root = self.local_root.resolve()
        path = Path(storage_uri).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise ValueError("Unsafe local document storage path") from None
        if not path.is_file():
            return False
        path.unlink()
        return True

    def delete_tenant_prefix(self, tenant_id: int) -> int:
        """Borra todos los originales de un tenant antes de eliminar sus filas.

        MinIO/Garage se limpia por prefijo ``tenant-<id>/``; el backend local
        borra el directorio equivalente dentro de ``storage/raw``. Es
        idempotente: un tenant ya limpio devuelve 0. Cualquier fallo del
        almacen se propaga para que el borrado de cuenta no publique exito
        dejando objetos huerfanos.
        """
        prefix = f"tenant-{int(tenant_id)}"
        if (
            self.settings.app_env == "test"
            or self.settings.document_storage_backend == "local"
        ):
            root = self.local_root.resolve()
            target = (self.local_root / prefix).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                raise ValueError("Unsafe local document storage path") from None
            if target.is_symlink():
                raise ValueError("Unsafe local document storage path")
            if not target.is_dir():
                return 0
            shutil.rmtree(target)
            return 1

        bucket = self.settings.minio_bucket
        client = self._client()
        if not client.bucket_exists(bucket):
            return 0
        removed = 0
        for item in client.list_objects(bucket, prefix=f"{prefix}/", recursive=True):
            client.remove_object(bucket, item.object_name)
            removed += 1
        return removed

    def _directory(
        self, ticker: str, category: str, tenant_id: int | None
    ) -> Path:
        base = self.local_root
        if tenant_id is not None:
            base = base / self._safe_path_part(f"tenant-{tenant_id}")
        return (
            base
            / self._safe_path_part(ticker)
            / self._safe_path_part(category)
        )

    _SAFE_COMPONENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}")

    @classmethod
    def _validate_path_component(cls, value: str) -> None:
        # Guard de whitelist reconocible por CodeQL: fullmatch de caracteres
        # seguros y rechazo explicito de "..".
        if (
            not cls._SAFE_COMPONENT_RE.fullmatch(value)
            or value in {".", ".."}
            or ".." in value
        ):
            raise ValueError("Unsafe local document storage path")

    @staticmethod
    def _validate_local_component(value: str) -> None:
        paths = (PurePosixPath(value), PureWindowsPath(value))
        if (
            any(path.is_absolute() for path in paths)
            or value in {".", ".."}
            or any(part == ".." for path in paths for part in path.parts)
            or any(separator in value for separator in ("/", "\\"))
        ):
            raise ValueError("Unsafe local document storage path")

    def _safe_path_part(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
        return cleaned[:120] or "unknown"

    def _safe_filename(self, value: str) -> str:
        cleaned = self._safe_path_part(value)
        if "." not in cleaned:
            return f"{cleaned}.bin"
        return cleaned
