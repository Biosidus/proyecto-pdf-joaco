"""Detector de páginas dobles, sin IA.

Una página doble es un escaneo apaisado, con dos páginas del tomo una al lado de
la otra. Muchos escaneos la guardan girada 90° dentro de un lienzo vertical, y
ahí es donde el lector la muestra acostada y hay que enderezarla.

La pista está en la forma. Si una página simple del tomo mide P de ancho sobre
alto, el escaneo de una doble medía el doble de ancho que de alto, así que
guardado acostado mide 1/(2P): para una página 2:3 (P = 0,667) la doble da 0,75.
Son formas distintas y no se superponen.

Para no depender de ningún valor fijo, el detector saca la proporción dominante
del propio archivo y después, para cada página, compara dos hipótesis: "está
derecha" y "está girada". Gana la que deja la página parecida a una página del
tomo (P) o a una doble (2P).

Lo único que la forma no puede decir es para qué lado girar, porque girar 90° o
270° deja la misma forma (la diferencia es si la doble queda boca abajo). Eso es
una sola decisión por tomo y la resuelve quien mira el resultado.

Ojo con las páginas de proporción 1/raíz(2) ≈ 0,707: quedan justo en el medio
entre las dos hipótesis. Ahí el detector no adivina, deja la página como está y
lo marca con confianza baja para que se revise.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Sequence

from core.extract import PageImage

GIROS_VALIDOS = (90, 270)

# Cuánto mejor tiene que ser la hipótesis "girada" para aceptarla. Evita dar
# vuelta páginas por diferencias de forma que son puro ruido de escaneo.
MARGEN_MEJORA = 0.25

# Tolerancia para agrupar páginas que comparten forma (2%).
TOLERANCIA_GRUPO = 0.02

# Cuántas páginas hacen falta para aceptar una forma como "la página del tomo".
MINIMO_GRUPO = 3

# Por debajo de esta confianza la decisión es dudosa y hay que mirarla.
CONFIANZA_MINIMA = 0.25


@dataclass
class PagePlan:
    number: int
    giro: int
    nombre: str
    ancho: int
    alto: int
    ratio: float
    motivo: str
    confianza: float

    @property
    def ancho_final(self) -> int:
        return self.alto if self.giro else self.ancho

    @property
    def alto_final(self) -> int:
        return self.ancho if self.giro else self.alto

    @property
    def horizontal(self) -> bool:
        return self.ancho_final > self.alto_final

    @property
    def girada(self) -> bool:
        return self.giro != 0

    @property
    def dudosa(self) -> bool:
        return self.confianza < CONFIANZA_MINIMA


@dataclass
class Layout:
    planes: list[PagePlan]
    base: float | None

    @property
    def giradas(self) -> int:
        return sum(1 for plan in self.planes if plan.girada)

    @property
    def horizontales(self) -> int:
        return sum(1 for plan in self.planes if plan.horizontal)

    @property
    def dudosas(self) -> int:
        return sum(1 for plan in self.planes if plan.dudosa)

    @property
    def confianza_minima(self) -> float:
        return min((plan.confianza for plan in self.planes), default=1.0)

    @property
    def clara(self) -> bool:
        """¿La forma del archivo alcanza para separar dobles de simples?"""
        return self.dudosas == 0


def detect_layout(pages: Sequence[PageImage], giro_dobles: int = 270) -> Layout:
    """Decide qué páginas hay que girar y cuánto.

    Sólo se giran páginas que están verticales y quedarían horizontales. Una
    página que ya viene horizontal se deja como está: si es una doble, ya se ve
    como tiene que verse, y girarla la volvería vertical, que es justo lo
    contrario de lo que buscamos.
    """
    ratios = [page.width / page.height for page in pages]
    base = proporcion_dominante(ratios)

    if base is None:
        # Sin una forma de página clara no se puede comparar nada: mejor no
        # tocar ninguna página que girar las simples por error.
        return Layout(planes=[_sin_decidir(page) for page in pages], base=None)

    planes: list[PagePlan] = []
    for page in pages:
        ratio = page.width / page.height
        como_esta = fit(ratio, base)
        girada = fit(1 / ratio, base)

        ya_horizontal = ratio > 1
        gana_girada = (
            not ya_horizontal and girada < como_esta * (1 - MARGEN_MEJORA)
        )

        a_favor, en_contra = (girada, como_esta) if gana_girada else (como_esta, girada)
        planes.append(
            PagePlan(
                number=page.number,
                giro=giro_dobles if gana_girada else 0,
                nombre=page.source_name,
                ancho=page.width,
                alto=page.height,
                ratio=ratio,
                motivo=_motivo(ratio, base, gana_girada, ya_horizontal),
                confianza=_confianza(a_favor, en_contra),
            )
        )

    return Layout(planes=planes, base=base)


def _sin_decidir(page: PageImage) -> PagePlan:
    return PagePlan(
        number=page.number,
        giro=0,
        nombre=page.source_name,
        ancho=page.width,
        alto=page.height,
        ratio=page.width / page.height,
        motivo="no se pudo determinar la forma de página del tomo",
        confianza=0.0,
    )


def fit(value: float, base: float) -> float:
    """Cuán lejos está `value` de parecerse a una página simple (P) o a una doble (2P)."""
    return min(abs(value - base) / base, abs(value - 2 * base) / (2 * base))


def proporcion_dominante(ratios: Sequence[float]) -> float | None:
    """La forma que más se repite en el archivo: la página simple del tomo.

    Devuelve None cuando no hay una mayoría clara. Con pocas páginas, o con un
    archivo donde las simples y las dobles están empatadas, la forma sola no
    alcanza para decir cuál de las dos es cuál: adivinar ahí sale peor que no
    hacer nada, porque termina girando las simples y dejando las dobles como
    estaban.
    """
    if not ratios:
        return None

    candidatos = []
    for ratio in ratios:
        cerca = [otro for otro in ratios if abs(otro - ratio) <= ratio * TOLERANCIA_GRUPO]
        candidatos.append((len(cerca), ratio, cerca))

    cantidad, _, grupo = max(candidatos, key=lambda item: item[0])
    if cantidad < MINIMO_GRUPO:
        return None
    return median(grupo)


def confianza_esperada(base: float) -> float:
    """La proporción de una página que queda justo entre las dos hipótesis.

    Es el punto donde "está derecha" y "está girada" calzan igual de bien, o sea
    la media armónica entre P y 1/(2P). Para una página 2:3 da 1/raíz(2) ≈ 0,707.
    """
    return 1 / (base + 1 / (2 * base))


def giro_opuesto(giro: int) -> int:
    return 270 if giro == 90 else 90


def _confianza(a_favor: float, en_contra: float) -> float:
    """0 cuando las dos hipótesis empatan, 1 cuando la elegida calza perfecto."""
    if en_contra <= 0:
        return 1.0
    return max(0.0, min(1.0, 1 - a_favor / en_contra))


def _motivo(ratio: float, base: float, girada: bool, ya_horizontal: bool) -> str:
    if girada:
        return (
            f"mide {ratio:.3f} de ancho sobre alto y la página tipo del tomo mide "
            f"{base:.3f}: es una doble guardada acostada"
        )
    if ya_horizontal:
        return (
            f"mide {ratio:.3f}: ya viene horizontal, así que se deja como está"
        )
    return f"mide {ratio:.3f}, igual a la página tipo del tomo ({base:.3f})"
