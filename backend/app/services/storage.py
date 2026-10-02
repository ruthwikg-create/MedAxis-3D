from __future__ import annotations

import json
import re
from pathlib import Path
from threading import RLock
from typing import Any


_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class CaseStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def validate_case_id(self, case_id: str) -> str:
        if not _CASE_ID.fullmatch(case_id):
            raise ValueError("Invalid case identifier.")
        candidate = (self.root / case_id).resolve()
        if candidate.parent != self.root:
            raise ValueError("Case path escapes the configured storage root.")
        return case_id

    def case_dir(self, case_id: str) -> Path:
        self.validate_case_id(case_id)
        return self.root / case_id

    def create_case(self, case_id: str) -> Path:
        path = self.case_dir(case_id)
        path.mkdir(parents=True, exist_ok=False)
        return path

    def delete_case(self, case_id: str) -> None:
        import shutil
        path = self.case_dir(case_id)
        with self._lock:
            if not path.is_dir():
                raise FileNotFoundError(case_id)
            shutil.rmtree(path)

    def write_meta(self, case_id: str, data: dict[str, Any]) -> None:
        self.write_json(case_id, "meta.json", data)

    def read_meta(self, case_id: str) -> dict[str, Any]:
        return self.read_json(case_id, "meta.json", default={})

    def write_json(self, case_id: str, name: str, data: Any) -> None:
        path = self.case_dir(case_id) / name
        temp = path.with_suffix(path.suffix + ".tmp")
        with self._lock:
            temp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            temp.replace(path)

    def read_json(self, case_id: str, name: str, default: Any) -> Any:
        path = self.case_dir(case_id) / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default

    def append_json_item(self, case_id: str, name: str, item: dict[str, Any]) -> None:
        with self._lock:
            items = self.read_json(case_id, name, default=[])
            if not isinstance(items, list):
                items = []
            items.append(item)
            self.write_json(case_id, name, items)

    def audit(self, case_id: str, action: str, details: dict[str, Any] | None = None) -> None:
        from datetime import datetime, timezone
        self.append_json_item(case_id, "audit.json", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user": "local-user",
            "action": action,
            "details": details or {},
        })

    def list_cases(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in sorted(self.root.iterdir(), key=lambda p: p.name.lower()):
            if not path.is_dir():
                continue
            try:
                self.validate_case_id(path.name)
            except ValueError:
                continue
            meta = self.read_meta(path.name)
            if meta:
                result.append(meta)
        return result
