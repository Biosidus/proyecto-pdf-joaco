"""Servidor local: recibe un CBR/CBZ/PDF, endereza las páginas dobles y devuelve
un PDF con esas páginas en horizontal de verdad.

No usa ninguna API externa: la forma de las páginas alcanza para encontrarlas.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from core.config import settings
from core.pipeline import registry

ALLOWED_SUFFIXES = {".cbr", ".cbz", ".rar", ".zip", ".pdf"}

# Margen para el encabezado multipart al comparar contra Content-Length
MULTIPART_SLACK = 64 * 1024
COPY_CHUNK = 1024 * 1024

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 3

HOST = "127.0.0.1"
PORT = 8000

logger = logging.getLogger("enderezador")


def configurar_logs() -> None:
    """Manda el registro a workdir/logs además de la consola.

    Tiene que quedar en disco: si algo falla al arrancar, la ventana se cierra
    y no queda nada para mirar después.
    """
    settings.ensure_dirs()
    formato = logging.Formatter(LOG_FORMAT)

    archivo = RotatingFileHandler(
        settings.logs_dir / "servidor.log",
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUPS,
        encoding="utf-8",
    )
    archivo.setFormatter(formato)

    consola = logging.StreamHandler()
    consola.setFormatter(formato)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers[:] = [archivo, consola]


configurar_logs()


def mensaje_limite() -> str:
    return (
        f"El archivo supera el límite de {settings.max_upload_mb} MB. "
        "Se puede subir el límite con MAX_UPLOAD_MB en el .env."
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_dirs()
    registry.purge()
    yield


app = FastAPI(title="Enderezador de páginas dobles", lifespan=lifespan)


@app.middleware("http")
async def rechazar_subidas_grandes(request: Request, call_next):
    """Corta la subida antes de leerla si ya se sabe que supera el límite."""
    if request.method == "POST" and request.url.path == "/api/jobs":
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > settings.max_upload_bytes + MULTIPART_SLACK:
            return JSONResponse(status_code=413, content={"detail": mensaje_limite()})
    return await call_next(request)


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "giro_dobles": settings.giro_dobles,
        "max_upload_mb": settings.max_upload_mb,
    }


@app.post("/api/jobs", status_code=201)
async def create_job(file: UploadFile = File(...)) -> dict:
    name = Path(file.filename or "comic.cbr").name
    suffix = Path(name).suffix.lower()

    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado ({suffix or 'sin extensión'}). "
            "Se aceptan .cbr, .cbz, .rar, .zip y .pdf.",
        )

    if file.size is not None and file.size > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail=mensaje_limite())

    settings.ensure_dirs()
    target = settings.uploads_dir / f"{uuid.uuid4().hex}{suffix}"
    written = 0
    try:
        with target.open("wb") as handle:
            while True:
                chunk = file.file.read(COPY_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail=mensaje_limite())
                handle.write(chunk)
    except BaseException:  # noqa: BLE001 - si la subida falla o se corta, no queda basura
        target.unlink(missing_ok=True)
        raise

    return registry.create(name, target).snapshot()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    return job.snapshot()


@app.post("/api/jobs/{job_id}/flip")
def flip_job(job_id: str) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if job.status != "done":
        raise HTTPException(status_code=409, detail="Todavía no hay un PDF para rehacer.")
    registry.flip(job)
    return job.snapshot()


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str) -> FileResponse:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if job.status != "done" or not job.output_path.exists():
        raise HTTPException(status_code=409, detail="El PDF todavía no está listo.")
    return FileResponse(
        job.output_path,
        media_type="application/pdf",
        filename=f"{job.title} - orientado.pdf",
    )


@app.get("/api/jobs/{job_id}/thumbs/{number}")
def thumbnail(job_id: str, number: int) -> Response:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if number < 1 or number > len(job.pages):
        raise HTTPException(status_code=404, detail="Esa página no existe.")
    path = job.thumbs_dir / f"{number:04d}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Miniatura no encontrada.")
    return Response(
        path.read_bytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")


if __name__ == "__main__":
    settings.ensure_dirs()
    logger.info(
        "Arrancando: dobles a %s°, subida máxima %s MB",
        settings.giro_dobles,
        settings.max_upload_mb,
    )
    print(f"\n  Enderezador de páginas dobles listo en http://{HOST}:{PORT}")
    print(f"  Las dobles se giran {settings.giro_dobles}° (se cambia con un botón)")
    print(f"  Registro: {settings.logs_dir / 'servidor.log'}\n")
    # log_config=None: sin esto uvicorn no deja que sus mensajes lleguen al archivo.
    uvicorn.run(app, host=HOST, port=PORT, log_config=None)
