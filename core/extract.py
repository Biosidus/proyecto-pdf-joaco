"""Extrae las páginas de un archivo de entrada como imágenes en disco.

Acepta archivos comprimidos de cómic (.cbr/.cbz/.rar/.zip) y PDF. Las imágenes
de un archivo comprimido se copian tal cual, sin recomprimir, para no perder
calidad. Las páginas de un PDF se rasterizan respetando su rotación, que es lo
que ve el lector.
"""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pymupdf
from PIL import Image, UnidentifiedImageError

LOSSLESS_FORMATS = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
}

Image.init()
_IMAGE_EXTENSIONS = set(Image.registered_extensions())

ProgressCallback = Callable[[int, int], None]


class ExtractionError(RuntimeError):
    """La entrada no se pudo interpretar como cómic o PDF."""


@dataclass
class PageImage:
    number: int
    source_name: str
    path: Path
    width: int
    height: int
    mime: str

    @property
    def is_landscape(self) -> bool:
        return self.width > self.height

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()


def extract_pages(
    source: Path,
    pages_dir: Path,
    *,
    pdf_dpi: int = 200,
    on_progress: ProgressCallback | None = None,
) -> list[PageImage]:
    """Devuelve las páginas de `source` en orden, guardadas dentro de `pages_dir`."""
    pages_dir.mkdir(parents=True, exist_ok=True)
    pages = _extract_any(source, pages_dir, pdf_dpi, on_progress)

    if not pages:
        raise ExtractionError(f"No se encontraron páginas en {source.name}")
    return pages


def _extract_any(
    source: Path, pages_dir: Path, pdf_dpi: int, on_progress: ProgressCallback | None
) -> list[PageImage]:
    """Elige el lector por la firma del archivo, no por la extensión.

    Pasa seguido que un `.cbr` sea en realidad un zip, o que un `.cbr` sea un PDF
    ya convertido. Mirar los primeros bytes evita fallar por el nombre.
    """
    formato = sniff(source)
    intentos = {
        "zip": lambda: _extract_from_zip(source, pages_dir, on_progress),
        "rar": lambda: _extract_from_rar(source, pages_dir, on_progress),
        "pdf": lambda: _extract_from_pdf(source, pages_dir, pdf_dpi, on_progress),
    }
    if formato is None:
        raise ExtractionError(
            f"No se reconoce el formato de {source.name}. Se esperaba un .cbr, "
            ".cbz o .pdf."
        )

    try:
        return intentos[formato]()
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"{source.name} dice ser un zip pero está dañado.") from exc
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - se traduce a un mensaje claro
        raise ExtractionError(f"No se pudo leer {source.name}: {exc}") from exc


def sniff(source: Path) -> str | None:
    """Devuelve "zip", "rar" o "pdf" según los primeros bytes del archivo."""
    with source.open("rb") as handle:
        cabecera = handle.read(8)

    if cabecera.startswith(b"%PDF"):
        return "pdf"
    if cabecera.startswith(b"PK\x03\x04") or cabecera.startswith(b"PK\x05\x06"):
        return "zip"
    if cabecera.startswith(b"Rar!\x1a\x07"):
        return "rar"
    return None


def _extract_from_zip(
    source: Path, pages_dir: Path, on_progress: ProgressCallback | None
) -> list[PageImage]:
    with zipfile.ZipFile(source) as archive:
        entries = [name for name in archive.namelist() if _looks_like_image(name)]
        entries.sort(key=_natural_key)
        total = len(entries)
        pages = []
        for index, name in enumerate(entries, start=1):
            page = _store_bytes(pages_dir, index, name, archive.read(name))
            if page is not None:
                pages.append(page)
            _notify(on_progress, index, total)
        return pages


def _extract_from_rar(
    source: Path, pages_dir: Path, on_progress: ProgressCallback | None
) -> list[PageImage]:
    rarfile = _load_rarfile()

    try:
        archive = rarfile.RarFile(source)
    except rarfile.NeedFirstVolume as exc:
        raise ExtractionError(f"{source.name} es una parte de un CBR multivolumen.") from exc
    except rarfile.Error as exc:
        raise ExtractionError(f"No se pudo abrir {source.name}: {exc}") from exc

    with archive:
        if archive.needs_password():
            raise ExtractionError(f"{source.name} está protegido con contraseña.")
        entries = [info.filename for info in archive.infolist() if _looks_like_image(info.filename)]
        entries.sort(key=_natural_key)
        total = len(entries)
        pages = []
        for index, name in enumerate(entries, start=1):
            with archive.open(name) as handle:
                page = _store_bytes(pages_dir, index, name, handle.read())
            if page is not None:
                pages.append(page)
            _notify(on_progress, index, total)
        return pages


def _extract_from_pdf(
    source: Path, pages_dir: Path, dpi: int, on_progress: ProgressCallback | None
) -> list[PageImage]:
    try:
        document = pymupdf.open(source)
    except Exception as exc:  # noqa: BLE001 - pymupdf lanza errores variados
        raise ExtractionError(f"No se pudo abrir {source.name} como PDF: {exc}") from exc

    pages: list[PageImage] = []
    with document:
        if document.needs_pass:
            raise ExtractionError(f"{source.name} está protegido con contraseña.")
        total = document.page_count
        for index, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(dpi=dpi)
            path = pages_dir / f"{index:04d}.jpg"
            path.write_bytes(pixmap.tobytes("jpg", jpg_quality=92))
            pages.append(
                PageImage(
                    number=index,
                    source_name=f"página {index}",
                    path=path,
                    width=pixmap.width,
                    height=pixmap.height,
                    mime="image/jpeg",
                )
            )
            _notify(on_progress, index, total)
    return pages


def _store_bytes(pages_dir: Path, number: int, name: str, data: bytes) -> PageImage | None:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            fmt = (image.format or "").upper()
            if fmt in LOSSLESS_FORMATS and image.mode not in ("RGBA", "P", "LA"):
                extension, mime = LOSSLESS_FORMATS[fmt]
                payload = data
            else:
                buffer = io.BytesIO()
                if image.mode in ("RGBA", "P", "LA"):
                    image.convert("RGBA").save(buffer, format="PNG")
                    extension, mime = ".png", "image/png"
                else:
                    image.convert("RGB").save(buffer, format="JPEG", quality=92)
                    extension, mime = ".jpg", "image/jpeg"
                payload = buffer.getvalue()
            width, height = image.size
    except (UnidentifiedImageError, OSError):
        return None

    path = pages_dir / f"{number:04d}{extension}"
    path.write_bytes(payload)
    return PageImage(
        number=number,
        source_name=name,
        path=path,
        width=width,
        height=height,
        mime=mime,
    )


def _load_rarfile():
    """Deja configurada la herramienta que rarfile usa para descomprimir.

    rarfile busca unrar, unar, 7z y bsdtar en el PATH por su cuenta, pero en
    Windows WinRAR no queda en el PATH, así que además se prueban sus rutas
    típicas. Si no se encuentra nada se sigue igual: si el archivo es un zip o un
    PDF, la ruta de lectura ni lo toca, y si es un RAR sin herramienta el error
    aparece al abrirlo.
    """
    try:
        import rarfile
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise ExtractionError("Falta la librería `rarfile` para leer archivos .cbr.") from exc

    unrar = _find_unrar()
    if unrar:
        rarfile.UNRAR_TOOL = unrar
        try:
            rarfile.tool_setup(force=True)
        except rarfile.Error:
            pass
    return rarfile


def _find_unrar() -> str | None:
    candidatos = [
        shutil.which("unrar"),
        r"C:\Program Files\WinRAR\UnRAR.exe",
        r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
        "/usr/bin/unrar",
        "/usr/local/bin/unrar",
        "/opt/homebrew/bin/unrar",
    ]
    for candidato in candidatos:
        if candidato and Path(candidato).exists():
            return candidato
    return None


def _looks_like_image(name: str) -> bool:
    if name.endswith("/"):
        return False
    stem = name.rsplit("/", 1)[-1]
    if stem.startswith("."):
        return False
    return Path(stem).suffix.lower() in _IMAGE_EXTENSIONS


def _natural_key(name: str):
    """Ordena 1.jpg, 2.jpg, 10.jpg como espera un lector de cómics."""
    return [
        (1, int(chunk)) if chunk.isdigit() else (0, chunk)
        for chunk in re.split(r"(\d+)", name.lower())
    ]


def _notify(callback: ProgressCallback | None, done: int, total: int) -> None:
    if callback is not None:
        callback(done, total)
