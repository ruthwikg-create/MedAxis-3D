from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class ObjectStorage:
    def __init__(self, local_root: Path):
        self.local_root = local_root.resolve()
        self.local_root.mkdir(parents=True, exist_ok=True)
        self.bucket = os.getenv("S3_BUCKET", "").strip()
        self.endpoint_url = os.getenv("S3_ENDPOINT_URL", "").strip() or None
        self.region = os.getenv("S3_REGION", "us-east-1")
        self.enabled = bool(self.bucket)
        self.strict = os.getenv("S3_STRICT", "false").strip().lower() in {"1", "true", "yes", "on"}
        self._client = None
        if self.enabled:
            try:
                import boto3
                self._client = boto3.client(
                    "s3",
                    region_name=self.region,
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID") or None,
                    aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY") or None,
                )
            except Exception:
                self._client = None
        if self.strict and self.enabled and self._client is None:
            raise RuntimeError("S3_STRICT=true but the configured S3 client could not initialize. Check boto3 credentials/endpoint configuration.")

    @property
    def mode(self) -> str:
        return "S3" if self.enabled and self._client is not None else "LOCAL"

    def put_file(self, fileobj: BinaryIO, key: str) -> dict[str, str]:
        key = key.replace("\\", "/").lstrip("/")
        if self.enabled and self._client is not None:
            self._client.upload_fileobj(fileobj, self.bucket, key)
            return {"mode": "S3", "bucket": self.bucket, "key": key}
        target = self.local_root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as out:
            while True:
                chunk = fileobj.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        return {"mode": "LOCAL", "path": str(target)}

    def put_path(self, source: Path, key: str) -> dict[str, str]:
        with source.open("rb") as fh:
            return self.put_file(fh, key)

    def exists(self, key: str) -> bool:
        key = key.replace("\\", "/").lstrip("/")
        if self.enabled and self._client is not None:
            try:
                self._client.head_object(Bucket=self.bucket, Key=key)
                return True
            except Exception:
                return False
        return (self.local_root / key).is_file()

    def get_path(self, key: str) -> Path:
        key = key.replace("\\", "/").lstrip("/")
        if self.enabled and self._client is not None:
            local = self.local_root / "s3-cache" / key
            local.parent.mkdir(parents=True, exist_ok=True)
            self._client.download_file(self.bucket, key, str(local))
            return local
        return self.local_root / key


    def delete_prefix(self, prefix: str) -> None:
        prefix = prefix.replace("\\", "/").lstrip("/")
        if self.enabled and self._client is not None:
            token = None
            while True:
                kwargs = {"Bucket": self.bucket, "Prefix": prefix}
                if token:
                    kwargs["ContinuationToken"] = token
                page = self._client.list_objects_v2(**kwargs)
                objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if objects:
                    self._client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects, "Quiet": True})
                if not page.get("IsTruncated"):
                    break
                token = page.get("NextContinuationToken")
            return
        target = self.local_root / prefix
        if target.exists():
            import shutil
            shutil.rmtree(target) if target.is_dir() else target.unlink(missing_ok=True)

    def health(self) -> str:
        if self.enabled and self._client is None:
            return "WARNING — S3 configured but boto3 client could not initialize"
        if self.enabled and self._client is not None:
            try:
                self._client.head_bucket(Bucket=self.bucket)
                return "ONLINE — S3"
            except Exception as exc:
                return f"WARNING — S3 configured but not reachable: {type(exc).__name__}"
        return "LOCAL — development storage"
