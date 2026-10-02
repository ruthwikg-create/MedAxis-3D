from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
CASES_DIR = DATA_DIR / "cases"
MODELS_DIR = BASE_DIR / "models"

# Load project-local .env before importing services that read environment settings.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=False)
except Exception:
    pass

CASES_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
