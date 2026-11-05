import abc
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class BaseStorage(abc.ABC):
    """Abstract storage backend for uploads and attachments."""

    @abc.abstractmethod
    def init_storage(self) -> None:
        """Initialize the storage provider (e.g. create dirs, test access)."""
        pass

    @abc.abstractmethod
    def put_object(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
        """Store an object and return a metadata dictionary with path, size, content_type."""
        pass

    @abc.abstractmethod
    def get_object(self, path: str) -> Tuple[bytes, str]:
        """Retrieve object bytes and content_type. Raises FileNotFoundError if missing."""
        pass

    @abc.abstractmethod
    def object_exists(self, path: str) -> bool:
        """Return True if the object exists in storage."""
        pass

    @abc.abstractmethod
    def delete_object(self, path: str) -> bool:
        """Delete object if it exists. Return True if deleted."""
        pass


class LocalStorage(BaseStorage):
    """Local filesystem storage with path-traversal prevention."""

    def __init__(self, upload_dir: Optional[str] = None):
        base = upload_dir or os.environ.get("UPLOAD_DIR", "./data/uploads")
        self.base_dir = Path(base).resolve()

    def _resolve_path(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute() or p.drive:
            raise ValueError(f"Path traversal detected: {path}")
        clean_path = path.replace("\\", "/")
        if clean_path.startswith("/"):
            raise ValueError(f"Path traversal detected: {path}")
        target = (self.base_dir / clean_path).resolve()
        try:
            if not target.is_relative_to(self.base_dir):
                raise ValueError(f"Path traversal detected: {path} escapes {self.base_dir}")
        except AttributeError:
            if not str(target).startswith(str(self.base_dir)):
                raise ValueError(f"Path traversal detected: {path} escapes {self.base_dir}")
        return target

    def init_storage(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def put_object(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
        target = self._resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

        # Store content type in a companion metadata file
        meta_file = target.with_suffix(target.suffix + ".meta")
        try:
            meta_file.write_text(json.dumps({"content_type": content_type}), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to write metadata for %s: %s", path, e)

        return {
            "path": path,
            "size": len(data),
            "content_type": content_type,
        }

    def get_object(self, path: str) -> Tuple[bytes, str]:
        try:
            target = self._resolve_path(path)
        except ValueError as err:
            raise FileNotFoundError(f"File not found: {err}")

        if not target.is_file():
            raise FileNotFoundError(f"File not found: {path}; re-upload required")

        data = target.read_bytes()
        content_type = "application/octet-stream"

        meta_file = target.with_suffix(target.suffix + ".meta")
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                content_type = meta.get("content_type", content_type)
            except Exception:
                pass
        else:
            guessed, _ = mimetypes.guess_type(target.name)
            if guessed:
                content_type = guessed

        return data, content_type

    def object_exists(self, path: str) -> bool:
        if not path or "emergent" in path.lower():
            return False
        try:
            target = self._resolve_path(path)
            return target.is_file()
        except Exception:
            return False

    def delete_object(self, path: str) -> bool:
        try:
            target = self._resolve_path(path)
            if target.is_file():
                target.unlink(missing_ok=True)
                meta_file = target.with_suffix(target.suffix + ".meta")
                meta_file.unlink(missing_ok=True)
                return True
        except Exception as e:
            logger.warning("Failed to delete %s: %s", path, e)
        return False


class S3Storage(BaseStorage):
    """S3-compatible object storage (AWS S3, Cloudflare R2, MinIO)."""

    def __init__(
        self,
        bucket: Optional[str] = None,
        region: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
    ):
        self.bucket = bucket or os.environ.get("S3_BUCKET", "applypilot-uploads")
        self.region = region or os.environ.get("S3_REGION", "us-east-1")
        self.endpoint_url = endpoint_url or os.environ.get("S3_ENDPOINT_URL")
        self.access_key_id = access_key_id or os.environ.get("AWS_ACCESS_KEY_ID")
        self.secret_access_key = secret_access_key or os.environ.get("AWS_SECRET_ACCESS_KEY")
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3

            client_kwargs = {
                "service_name": "s3",
                "region_name": self.region,
                "aws_access_key_id": self.access_key_id,
                "aws_secret_access_key": self.secret_access_key,
            }
            if self.endpoint_url:
                client_kwargs["endpoint_url"] = self.endpoint_url
            self._client = boto3.client(**client_kwargs)
        return self._client

    def init_storage(self) -> None:
        try:
            client = self._get_client()
            client.head_bucket(Bucket=self.bucket)
        except Exception as exc:
            logger.warning("S3 head_bucket check failed (bucket may not exist yet or lacks permissions): %s", exc)

    def put_object(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
        client = self._get_client()
        key = path.replace("\\", "/").lstrip("/")
        client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return {
            "path": path,
            "size": len(data),
            "content_type": content_type,
        }

    def get_object(self, path: str) -> Tuple[bytes, str]:
        from botocore.exceptions import ClientError

        client = self._get_client()
        key = path.replace("\\", "/").lstrip("/")
        try:
            resp = client.get_object(Bucket=self.bucket, Key=key)
            data = resp["Body"].read()
            content_type = resp.get("ContentType", "application/octet-stream")
            return data, content_type
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("404", "NoSuchKey"):
                raise FileNotFoundError(f"File not found: {path}; re-upload required")
            raise e

    def object_exists(self, path: str) -> bool:
        from botocore.exceptions import ClientError

        if not path or "emergent" in path.lower():
            return False
        client = self._get_client()
        key = path.replace("\\", "/").lstrip("/")
        try:
            client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False
        except Exception:
            return False

    def delete_object(self, path: str) -> bool:
        client = self._get_client()
        key = path.replace("\\", "/").lstrip("/")
        try:
            client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            logger.warning("Failed to delete S3 object %s: %s", path, e)
            return False


_STORAGE_INSTANCE: Optional[BaseStorage] = None


def get_storage_backend() -> BaseStorage:
    global _STORAGE_INSTANCE
    if _STORAGE_INSTANCE is None:
        backend_type = os.environ.get("STORAGE_BACKEND", "local").lower().strip()
        if backend_type == "s3":
            _STORAGE_INSTANCE = S3Storage()
        else:
            _STORAGE_INSTANCE = LocalStorage()
    return _STORAGE_INSTANCE


def reset_storage_backend():
    """Reset the singleton instance (useful for testing)."""
    global _STORAGE_INSTANCE
    _STORAGE_INSTANCE = None


def init_storage(force: bool = False) -> str:
    """Initialize storage. Returns a status string."""
    backend = get_storage_backend()
    backend.init_storage()
    return "initialized"


def put_object(path: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
    backend = get_storage_backend()
    return backend.put_object(path, data, content_type)


def get_object(path: str) -> Tuple[bytes, str]:
    backend = get_storage_backend()
    return backend.get_object(path)


def object_exists(path: str) -> bool:
    backend = get_storage_backend()
    return backend.object_exists(path)


def delete_object(path: str) -> bool:
    backend = get_storage_backend()
    return backend.delete_object(path)
