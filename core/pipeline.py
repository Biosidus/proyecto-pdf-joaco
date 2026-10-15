"""Orquesta el trabajo: extraer las páginas, medir su forma y armar el PDF.

Cada conversión es un `Job` que reporta su avance. Como las páginas quedan
extraídas en disco, dar vuelta las dobles no vuelve a leer el archivo original:
sólo se rehace el PDF.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.builder import build_pdf
from core.config import settings
from core.extract import PageImage, extract_pages
from core.orientation import Layout, detect_layout, giro_opuesto

logger = logging.getLogger(__name__)

PHASE_QUEUED = "en cola"
PHASE_EXTRACTING = "extrayendo páginas"
PHASE_DETECTING = "midiendo la forma de las páginas"
PHASE_BUILDING = "armando el PDF"
PHASE_DONE = "listo"


class Job:
    def __init__(self, job_id: str, filename: str, source_path: Path, title: str) -> None:
        self.id = job_id
        self.filename = filename
        self.title = title
        self.source_path = source_path
        self.directory = settings.jobs_dir / job_id
        self.pages_dir = self.directory / "pages"
        self.thumbs_dir = self.directory / "thumbs"
        self.output_path = self.directory / f"{title} - orientado.pdf"

        self.status = "queued"
        self.phase = PHASE_QUEUED
        self.message = "En cola"
        self.done = 0
        self.total = 0
        self.error: str | None = None
        self.report: dict | None = None
        self.created_at = time.time()
        self.finished_at: float | None = None

        self.pages: list[PageImage] = []
        self.layout: Layout | None = None
        self.giro_dobles = settings.giro_dobles

        self._lock = threading.Lock()

    def update(self, **fields) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self, key, value)

    def bump(self, done: int, total: int, message: str | None = None) -> None:
        with self._lock:
            self.done = done
            self.total = total
            if message:
                self.message = message

    @property
    def resumen(self) -> dict:
        if self.report is None:
            return {}
        return self.report["resumen"]

    def snapshot(self) -> dict:
        with self._lock:
            progress = (self.done / self.total) if self.total else 0.0
            resumen = self.report["resumen"] if self.report else {}
            payload = {
                "id": self.id,
                "archivo": self.filename,
                "estado": self.status,
                "fase": self.phase,
                "mensaje": self.message,
                "hechas": self.done,
                "total": self.total,
                "progreso": round(min(progress, 1.0), 4),
                "paginas": len(self.pages) or resumen.get("total", 0),
                "horizontales": resumen.get("horizontales", 0),
                "giradas": resumen.get("giradas", 0),
                "dudosas": resumen.get("dudosas", 0),
                "giro_dobles": self.giro_dobles,
                "base": round(self.layout.base, 4) if self.layout and self.layout.base else None,
                "separacion_clara": self.layout.clara if self.layout else None,
                "error": self.error,
                "descarga": f"/api/jobs/{self.id}/download" if self.status == "done" else None,
                "miniaturas": f"/api/jobs/{self.id}/thumbs",
            }
            if self.report is not None:
                payload["resumen"] = resumen
                payload["detalle"] = self.report["detalle"]
            return payload

    def discard_source(self) -> None:
        """Borra el archivo subido: una vez extraídas las páginas no se usa más."""
        if self.source_path.parent == settings.uploads_dir:
            self.source_path.unlink(missing_ok=True)

    def destroy(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)
        self.discard_source()


class JobRegistry:
    def __init__(self, max_workers: int = 2) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")

    def create(self, filename: str, source_path: Path) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id, filename, source_path, Path(filename).stem)
        job.directory.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[job_id] = job
        self.purge()
        logger.info("Trabajo %s recibido: %s", job.id, filename)
        self._executor.submit(run_job, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def flip(self, job: Job) -> bool:
        """Rehace el PDF girando las dobles para el otro lado."""
        if job.status != "done":
            return False
        job.update(status="running", phase=PHASE_BUILDING, message="Dando vuelta las dobles")
        self._executor.submit(run_flip, job)
        return True

    def purge(self, max_age_hours: float = 12.0) -> None:
        cutoff = time.time() - max_age_hours * 3600
        with self._lock:
            stale = [job for job in self._jobs.values() if job.created_at < cutoff]
            for job in stale:
                self._jobs.pop(job.id, None)
            live_ids = {job.id for job in self._jobs.values()}
            live_sources = {job.source_path for job in self._jobs.values()}
        for job in stale:
            job.destroy()
        self._sweep_stale(cutoff, live_ids, live_sources)

    def _sweep_stale(self, cutoff: float, live_ids: set[str], live_sources: set[Path]) -> None:
        """Borra lo que dejó un cierre forzado: trabajos y subidas sin dueño."""
        if settings.jobs_dir.exists():
            for entry in settings.jobs_dir.iterdir():
                if not entry.is_dir() or entry.name in live_ids:
                    continue
                try:
                    old = entry.stat().st_mtime < cutoff
                except OSError:
                    continue
                if old:
                    shutil.rmtree(entry, ignore_errors=True)
        if settings.uploads_dir.exists():
            for entry in settings.uploads_dir.iterdir():
                if not entry.is_file() or entry in live_sources:
                    continue
                try:
                    old = entry.stat().st_mtime < cutoff
                except OSError:
                    continue
                if old:
                    entry.unlink(missing_ok=True)


def run_job(job: Job) -> None:
    try:
        job.update(status="running", phase=PHASE_EXTRACTING, message="Leyendo el archivo")
        pages = extract_pages(
            job.source_path,
            job.pages_dir,
            pdf_dpi=settings.pdf_render_dpi,
            on_progress=lambda done, total: job.bump(done, total, f"Leyendo páginas ({done}/{total})"),
        )
        job.update(pages=pages)
        build(job)
    except Exception as exc:  # noqa: BLE001 - el error se informa en la interfaz
        logger.exception("Falló el trabajo %s (%s)", job.id, job.filename)
        job.update(status="error", phase="error", error=str(exc), message=str(exc),
                   finished_at=time.time())
    finally:
        job.discard_source()


def run_flip(job: Job) -> None:
    try:
        job.update(giro_dobles=giro_opuesto(job.giro_dobles))
        build(job)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falló el giro del trabajo %s", job.id)
        job.update(status="error", phase="error", error=str(exc), message=str(exc),
                   finished_at=time.time())


def build(job: Job) -> None:
    total = len(job.pages)
    job.update(phase=PHASE_DETECTING, message="Midiendo la forma de cada página")
    job.bump(0, total, "Midiendo la forma de cada página")
    layout = detect_layout(job.pages, giro_dobles=job.giro_dobles)
    job.update(layout=layout)

    job.update(phase=PHASE_BUILDING, message="Escribiendo el PDF")
    job.bump(0, total, "Escribiendo el PDF")
    report = build_pdf(
        job.pages,
        layout.planes,
        job.output_path,
        page_height_pt=settings.page_height_pt,
        title=job.title,
        thumbs_dir=job.thumbs_dir,
    )

    resumen = report["resumen"]
    mensaje = f"{resumen['giradas']} páginas dobles enderezadas de {resumen['total']}"
    if layout.dudosas:
        mensaje += f" · {layout.dudosas} sin poder decidir"
    job.update(report=report, status="done", phase=PHASE_DONE, message=mensaje,
               finished_at=time.time())
    job.bump(total, total)
    logger.info("Trabajo %s listo: %s", job.id, mensaje)


registry = JobRegistry()
