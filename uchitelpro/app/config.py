"""Пути и настройки приложения."""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
CASES_DIR = APP_DIR / "cases"
MK_DIR = APP_DIR / "mk"
APP_NAME = "УчительPRO"
APP_VERSION = "0.1.0-mvp"

ASSET_KINDS = {
    "backgrounds": "Фон сцены",
    "characters": "Персонаж",
    "ui": "Интерфейс (талисман и др.)",
}
ASSET_EXTS = (".png", ".webp", ".jpg", ".jpeg", ".svg", ".gif")


def default_data_dir() -> Path:
    env = os.environ.get("UCHITELPRO_DATA")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "UchitelPRO"
    return Path.home() / ".uchitelpro"


def prepare_data_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for kind in ASSET_KINDS:
        (path / "assets" / kind).mkdir(parents=True, exist_ok=True)
    (path / "backups").mkdir(exist_ok=True)
    return path
