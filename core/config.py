"""Configuración de la aplicación, cargada desde variables de entorno y `.env`."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

GIROS_VALIDOS = (90, 270)


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _giro(name: str, default: int) -> int:
    valor = _int(name, default)
    return valor if valor in GIROS_VALIDOS else default


class Settings:
    def __init__(self) -> None:
        self.base_dir = BASE_DIR
        self.workdir = BASE_DIR / "workdir"
        self.uploads_dir = self.workdir / "uploads"
        self.jobs_dir = self.workdir / "jobs"
        self.static_dir = BASE_DIR / "static"

        # Para qué lado se giran las dobles guardadas acostadas: 90 o 270.
        # La forma no lo puede decidir (girar 90 o 270 deja la misma forma), así
        # que es un valor por tomo y se cambia con un botón desde la interfaz.
        self.giro_dobles = _giro("GIRO_DOBLES", 270)

        self.pdf_render_dpi = _int("PDF_RENDER_DPI", 200)
        self.page_height_pt = _float("PAGE_HEIGHT_PT", 756.0)

        # Tope de subida en MB: un tomo escaneado puede pesar cientos.
        self.max_upload_mb = max(1, _int("MAX_UPLOAD_MB", 2048))

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        for directory in (self.uploads_dir, self.jobs_dir):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
