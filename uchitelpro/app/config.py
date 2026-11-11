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
    copy_builtin_assets(path)
    return path


def copy_builtin_assets(data_path: Path) -> int:
    """Кладёт готовую графику из комплекта в data/assets, не трогая то, что загрузил админ."""
    src = APP_DIR / "assets_builtin"
    if not src.is_dir():
        return 0
    n = 0
    for kind_dir in src.iterdir():
        if not kind_dir.is_dir() or kind_dir.name not in ASSET_KINDS:
            continue
        dst_dir = data_path / "assets" / kind_dir.name
        for f in kind_dir.iterdir():
            if not f.is_file() or f.suffix.lower() not in ASSET_EXTS:
                continue
            dst = dst_dir / f.name
            if not dst.exists():
                dst.write_bytes(f.read_bytes())
                n += 1
    return n
