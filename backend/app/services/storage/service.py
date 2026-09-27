import hashlib
import uuid
from pathlib import Path

from app.core.config import get_settings

settings = get_settings()


class LocalStorageBackend:
    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = Path(base_dir or settings.UPLOAD_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, filename: str, content: bytes) -> tuple[str, str, int]:
        """Returns (storage_key, sha256, size_bytes)."""
        sha256 = hashlib.sha256(content).hexdigest()
        ext = Path(filename).suffix
        storage_key = f"{uuid.uuid4()}{ext}"
        path = self.base_dir / storage_key
        path.write_bytes(content)
        return storage_key, sha256, len(content)

    def read(self, storage_key: str) -> bytes:
        return (self.base_dir / storage_key).read_bytes()

    def path_for(self, storage_key: str) -> Path:
        return self.base_dir / storage_key


class StorageService:
    """Interface kept stable so production can swap in an S3 backend
    without changing callers."""

    def __init__(self) -> None:
        self.backend = LocalStorageBackend()

    def save(self, filename: str, content: bytes) -> tuple[str, str, int]:
        return self.backend.save(filename, content)

    def read(self, storage_key: str) -> bytes:
        return self.backend.read(storage_key)


_storage: StorageService | None = None


def get_storage_service() -> StorageService:
    global _storage
    if _storage is None:
        _storage = StorageService()
    return _storage
