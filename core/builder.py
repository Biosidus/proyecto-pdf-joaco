"""Arma el PDF final a partir de las páginas extraídas y el plan de orientación.

La regla es simple: primero se gira la imagen según lo que dijo el detector y
después la página del PDF se crea con la forma que quedó. Una doble guardada
acostada termina siendo una página horizontal de verdad, sin depender de
`/Rotate`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pymupdf

from core.extract import PageImage
from core.orientation import PagePlan

ANCHO_MINIATURA = 150
CALIDAD_MINIATURA = 80


def to_pdf_rotate(rotation: int) -> int:
    """Traduce grados horarios a los de PyMuPDF.

    `Page.insert_image(rotate=...)` gira en sentido antihorario, así que hay que
    invertir el ángulo para que la página quede derecha.
    """
    return (360 - rotation) % 360


def build_pdf(
    pages: Sequence[PageImage],
    planes: Sequence[PagePlan],
    output_path: Path,
    *,
    page_height_pt: float = 756.0,
    title: str = "",
    thumbs_dir: Path | None = None,
) -> dict:
    by_number = {plan.number: plan for plan in planes}
    document = pymupdf.open()
    report: list[dict] = []

    if thumbs_dir is not None:
        thumbs_dir.mkdir(parents=True, exist_ok=True)

    for page in pages:
        plan = by_number[page.number]
        width, height = plan.ancho_final, plan.alto_final
        scale = page_height_pt / height
        page_width = width * scale

        pdf_page = document.new_page(width=page_width, height=page_height_pt)
        pdf_page.insert_image(
            pymupdf.Rect(0, 0, page_width, page_height_pt),
            stream=page.read_bytes(),
            rotate=to_pdf_rotate(plan.giro),
        )

        report.append(
            {
                "numero": page.number,
                "giro": plan.giro,
                "confianza": round(plan.confianza, 3),
                "ratio": round(plan.ratio, 4),
                "imagen": f"{plan.ancho}x{plan.alto}",
                "pagina": f"{round(page_width)}x{round(page_height_pt)}",
                "orientacion": "horizontal" if page_width > page_height_pt else "vertical",
                "motivo": plan.motivo,
                "origen": page.source_name,
            }
        )

    if thumbs_dir is not None:
        _write_thumbnails(document, thumbs_dir)

    document.set_metadata({"title": title, "producer": "cbr2pdf", "creator": "cbr2pdf"})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path, garbage=4, deflate=True)
    document.close()

    return {"paginas": len(report), "detalle": report, "resumen": summarize(report)}


def _write_thumbnails(document: pymupdf.Document, thumbs_dir: Path) -> None:
    """Miniaturas de cada página ya armada, para poder revisar el resultado."""
    for index, pdf_page in enumerate(document, start=1):
        scale = ANCHO_MINIATURA / pdf_page.rect.width
        pixmap = pdf_page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
        (thumbs_dir / f"{index:04d}.jpg").write_bytes(
            pixmap.tobytes("jpg", jpg_quality=CALIDAD_MINIATURA)
        )


def summarize(report: Sequence[dict]) -> dict:
    return {
        "total": len(report),
        "horizontales": sum(1 for item in report if item["orientacion"] == "horizontal"),
        "giradas": sum(1 for item in report if item["giro"]),
        "dudosas": sum(1 for item in report if item["confianza"] < 0.25),
    }
