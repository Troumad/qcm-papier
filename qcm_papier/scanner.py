"""Correction automatique des copies scannées.

Reproduit les méthodes de la classe ``Page`` du code JavaScript original
(index.html lignes ~2155-3645) :

* **Chargement** d'un PDF ou d'une image (PyMuPDF / Pillow).
* **Alignement** : localisation des 5 repères noirs (``alignAuto`` +
  ``alignAdjustShape``), calcul d'une matrice de transformation page→canvas
  (``computeViewport``) et détermination de l'orientation/rotation
  (``alignViewer``).
* **Lecture du code-barres** Code 39 par corrélation (``readBarcode`` +
  ``readBarcodeLine``) via un tracé de Bresenham.
* **Lecture du numéro étudiant** (``readStudentId`` + ``readMark``).
* **Détection des cases cochées** (``autoMarks``).
* **Calcul de la note** via :mod:`qcm_papier.marking`.

Les accès pixels utilisent Pillow (mode ``RGBA``). La matrice de transformation
est une matrice affine 2×3 (a, b, c, d, e, f) comme ``DOMMatrix`` du JS.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Iterable

from PIL import Image

from .code39 import CODE39
from .marking import score_page, PageScore
from .model import Layout, Project, Variant, VariantStore


def _variant_store(variants) -> VariantStore:
    if isinstance(variants, VariantStore):
        return variants
    return VariantStore.from_plain_dict(variants)


def _layout_of(variants, orientation):
    store = _variant_store(variants)
    v = store.get(orientation)
    if v is None:
        return None
    return v if isinstance(v, Layout) else Layout.from_dict(v)



# ---------------------------------------------------------------------------
# Matrice affine 2×3 (équivalent DOMMatrix)
# ---------------------------------------------------------------------------

@dataclass
class Matrix:
    """Matrice affine 2D (a, b, c, d, e, f) au format DOMMatrix.

    Transformation : ``[x', y'] = [a*x + c*y + e, b*x + d*y + f]``.
    """

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return (self.a * x + self.c * y + self.e,
                self.b * x + self.d * y + self.f)

    def inverse(self) -> "Matrix":
        det = self.a * self.d - self.b * self.c
        if det == 0:
            return Matrix()
        ia = self.d / det
        ib = -self.b / det
        ic = -self.c / det
        id_ = self.a / det
        ie = -(ic * self.e - id_ * self.f) if False else (-self.c * self.e + self.a * self.f) / det
        ie = (self.c * self.f - self.d * self.e) / det
        if_ = (self.b * self.e - self.a * self.f) / det
        return Matrix(a=ia, b=ib, c=ic, d=id_, e=ie, f=if_)

    @staticmethod
    def compose(cx2: float, cy2: float, scale: float, rotate_deg: float,
                cx1: float, cy1: float) -> "Matrix":
        """Construit la matrice translate(cx2,cy2) * scale * rotate *
        translate(-cx1,-cy1) comme ``computeViewport`` du JS."""
        m = Matrix()
        # translateSelf(cx2, cy2)
        m.e = cx2
        m.f = cy2
        # scaleSelf(scale)
        m.a *= scale
        m.d *= scale
        # rotateSelf(rotate)
        rad = math.radians(rotate_deg)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        a, b, c, d = m.a, m.b, m.c, m.d
        m.a = a * cos_r - b * sin_r
        m.b = a * sin_r + b * cos_r
        m.c = c * cos_r - d * sin_r
        m.d = c * sin_r + d * cos_r
        # translateSelf(-cx1, -cy1)
        m.e += -m.a * cx1 - m.c * cy1
        m.f += -m.b * cx1 - m.d * cy1
        return m


# ---------------------------------------------------------------------------
# Accès pixels via Pillow
# ---------------------------------------------------------------------------

class PixelImage:
    """Encapsule un Pillow Image RGBA pour l'accès aux pixels (x, y)."""

    def __init__(self, img: Image.Image):
        self.img = img.convert("RGBA")
        self.width = self.img.width
        self.height = self.img.height
        self._pixels = None

    @property
    def pixels(self):
        if self._pixels is None:
            self._pixels = self.img.load()
        return self._pixels

    def get_grey(self, x: int, y: int) -> tuple[float, float]:
        """Retourne (grey, alpha) d'un pixel. grey = 0.299R + 0.587G + 0.114B."""
        if 0 <= x < self.width and 0 <= y < self.height:
            r, g, b, a = self.pixels[x, y]
        else:
            r, g, b, a = 255, 255, 255, 255
        grey = 0.299 * r + 0.587 * g + 0.114 * b
        return grey, a

    def get_mark_grey(self, x: int, y: int) -> tuple[float, float]:
        """Retourne (grey, alpha) d'un pixel avec la formule de readMark du JS.

        ``grey = 2*min(r,g,b)/3 + (0.299*r + 0.587*g + 0.114*b)/3`` :
        donne plus de poids au canal le plus faible (noir/gris foncé), pour
        mieux distinguer les cases cochées des contours imprimés.
        """
        if 0 <= x < self.width and 0 <= y < self.height:
            r, g, b, a = self.pixels[x, y]
        else:
            r, g, b, a = 255, 255, 255, 255
        grey = 2 * min(r, g, b) / 3 + (0.299 * r + 0.587 * g + 0.114 * b) / 3
        return grey, a

    def get_region(self, x: int, y: int, w: int, h: int) -> list[tuple[int, int, int, int]]:
        """Retourne les pixels RGBA d'une région (liste linéaire)."""
        region = []
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                region.append(self.pixels[xx, yy] if 0 <= xx < self.width and 0 <= yy < self.height else (255, 255, 255, 255))
        return region


# ---------------------------------------------------------------------------
# Page corrigée
# ---------------------------------------------------------------------------

@dataclass
class ScannedPage:
    """Une page de copie scannée en cours de correction.

    Reproduit la classe ``Page`` du code original (index.html ~2155).
    """

    img: PixelImage | None = None
    rotate: int = 0
    ignore: bool = False
    shapes: list[dict] = field(default_factory=list)
    adjust: dict | None = None
    barcode: str = ""
    variant_id: int | None = None
    student_id: str | None = None
    student_eid: str | None = None
    student_name: str | None = None
    student_firstname: str | None = None
    marks: list[dict] = field(default_factory=list)
    matrix: Matrix | None = None
    matrix_inv: Matrix | None = None
    value: float | None = None
    total: float | None = None
    complete: bool = False

    def clear_marks(self) -> None:
        self.shapes = []
        self.adjust = None
        self.barcode = ""
        self.variant_id = None
        self.student_id = None
        self.student_eid = None
        self.student_name = None
        self.student_firstname = None
        self.marks = []
        self.value = None
        self.total = None
        self.complete = False


# ---------------------------------------------------------------------------
# Calcul du viewport (matrice page→canvas)
# ---------------------------------------------------------------------------

def compute_viewport(page: ScannedPage, variants: dict,
                     dest_x: int, dest_y: int) -> dict:
    """Calcule la matrice de transformation page→canvas.

    Reprend ``Page.computeViewport`` (index.html ~2200-2280).
    """
    orientation = "p" if dest_x <= dest_y else "l"
    if page.adjust is None and page.rotate in (90, 270):
        orientation = "l" if orientation == "p" else "p"

    layout_p = _layout_of(variants, "p")
    layout_l = _layout_of(variants, "l")

    value: dict = {}
    layout = _layout_of(variants, orientation)
    if layout is not None:
        value = {"width": layout.page_width, "height": layout.page_height,
                  "rotate": page.rotate}
    elif orientation == "p" and layout_l is not None:
        value = {"width": layout_l.page_height, "height": layout_l.page_width,
                  "rotate": page.rotate}
    elif orientation == "l" and layout_p is not None:
        value = {"width": layout_p.page_height, "height": layout_p.page_width,
                  "rotate": page.rotate}
    elif orientation == "p":
        value = {"width": 210, "height": 297, "rotate": page.rotate}
    else:
        value = {"width": 297, "height": 210, "rotate": page.rotate}

    value["scale"] = max(value["width"], value["height"]) / max(dest_x, dest_y)

    if page.adjust is not None:
        value["cx1"] = page.adjust["canvas_center_x"]
        value["cy1"] = page.adjust["canvas_center_y"]
        value["rotate"] = page.adjust["rotate_mean"] * 180 / math.pi
        value["scale"] = page.adjust["scale_mean"]
        value["cx2"] = page.adjust["center_x"]
        value["cy2"] = page.adjust["center_y"]
        rm = page.adjust["rotate_mean"]
        if 0.25 * math.pi <= rm <= 0.75 * math.pi:
            value["width"], value["height"] = value["height"], value["width"]
        elif 1.25 * math.pi <= rm <= 1.75 * math.pi:
            value["width"], value["height"] = value["height"], value["width"]
    else:
        value["cx1"] = dest_x / 2
        value["cy1"] = dest_y / 2
        value["cx2"] = value["width"] / 2
        value["cy2"] = value["height"] / 2

    value["matrix"] = Matrix.compose(value["cx2"], value["cy2"],
                                      value["scale"], value["rotate"],
                                      value["cx1"], value["cy1"])
    return value


# ---------------------------------------------------------------------------
# Ajustement d'un repère (centrage sur le centre de gravité sombre)
# ---------------------------------------------------------------------------

def align_adjust_shape(pimg: PixelImage, matrix: Matrix,
                       page_x: float, page_y: float, range_mm: float,
                       clair: float) -> dict:
    """Ajuste la position d'un repère en cherchant le centre de gravité sombre.

    Reprend ``Page.alignAdjustShape`` (index.html ~2284-2325).
    """
    mi = matrix.inverse()
    canvas_x = mi.a * page_x + mi.c * page_y + mi.e
    canvas_y = mi.b * page_x + mi.d * page_y + mi.f
    shape_rect_w = range_mm
    shape_rect_h = range_mm
    canvas_rect_w = round(abs(mi.a * shape_rect_w + mi.c * shape_rect_h))
    canvas_rect_h = round(abs(mi.b * shape_rect_w + mi.d * shape_rect_h))
    canvas_rect_w = max(canvas_rect_w, 1)
    canvas_rect_h = max(canvas_rect_h, 1)
    canvas_left = int(canvas_x - canvas_rect_w / 2)
    canvas_top = int(canvas_y - canvas_rect_h / 2)

    sum_x = 0.0
    sum_y = 0.0
    sum_c = 0
    for yy in range(canvas_top, canvas_top + canvas_rect_h):
        for xx in range(canvas_left, canvas_left + canvas_rect_w):
            grey, a = pimg.get_grey(xx, yy)
            if a == 255 and grey < clair:  # pixel sombre opaque
                sum_x += xx - canvas_left
                sum_y += yy - canvas_top
                sum_c += 1

    canvas_radius = canvas_rect_w / shape_rect_w * 2 if shape_rect_w else 0
    if sum_c != 0:
        canvas_x = canvas_left + (sum_x / sum_c)
        canvas_y = canvas_top + (sum_y / sum_c)

    px, py = matrix.apply(canvas_x, canvas_y)
    score = sum_c / (math.pi * canvas_radius * canvas_radius) if canvas_radius else 0.0
    return {
        "page_x": px,
        "page_y": py,
        "canvas_x": canvas_x,
        "canvas_y": canvas_y,
        "score": score,
    }


def _score_ok(score: float) -> bool:
    return 0.85 <= score <= 1.2


# ---------------------------------------------------------------------------
# Alignement automatique (recherche des 5 repères + orientation)
# ---------------------------------------------------------------------------

def align_auto(page: ScannedPage, variants: dict) -> bool:
    """Localise les 5 repères et détermine l'orientation/rotation.

    Reprend ``Page.alignAuto`` (index.html ~2660-2805). Teste les 4 rotations
    possibles (0°, 90°, 180°, 270°) en miroir portrait/paysage, et plusieurs
    seuils de clarté (clair de 0 à 220 par pas de 10).
    """
    if page.img is None:
        return False
    pimg = page.img
    matrix = compute_viewport(page, variants, pimg.width, pimg.height)["matrix"]
    success = False

    def test_shapes(shapes_x, shapes_y, clair):
        page.shapes = []
        val = 0
        val1 = 0
        for i in range(5):
            adj = align_adjust_shape(pimg, matrix, shapes_x[i], shapes_y[i], 10, clair)
            if _score_ok(adj["score"]):
                page.shapes.append(adj)
                val += 1
                if i == 1:
                    val1 = 2
            else:
                # Recherche dans une plage plus large.
                adj = align_adjust_shape(pimg, matrix, shapes_x[i], shapes_y[i], 15, clair)
                adj = align_adjust_shape(pimg, matrix, adj["page_x"], adj["page_y"], 10, clair)
                page.shapes.append(adj)
                if _score_ok(adj["score"]):
                    val += 1
                    if i == 1:
                        val1 = 1
        if (val1 == 2 and val > 3) or (val1 == 1 and val > 4):
            align_viewer(page, variants)
            return True
        return False

    p = _layout_of(variants, "p")
    l = _layout_of(variants, "l")
    if pimg.height > pimg.width:
        for clair in range(0, 220, 10):
            if not success and p is not None:
                success = test_shapes(p.shapes_x, p.shapes_y, clair)
            if not success and p is not None:
                sx = [p.page_width - x for x in p.shapes_x]
                sy = [p.page_height - y for y in p.shapes_y]
                success = test_shapes(sx, sy, clair)
            if not success and l is not None:
                sx = list(l.shapes_y)
                sy = [l.page_width - x for x in l.shapes_x]
                success = test_shapes(sx, sy, clair)
            if not success and l is not None:
                sx = [l.page_height - y for y in l.shapes_y]
                sy = list(l.shapes_x)
                success = test_shapes(sx, sy, clair)
            if success:
                clair = 230
                break
    else:
        for clair in range(0, 220, 10):
            if not success and l is not None:
                success = test_shapes(l.shapes_x, l.shapes_y, clair)
            if not success and l is not None:
                sx = [p.page_height - x for x in l.shapes_x] if p else [0] * 5
                sy = [p.page_width - y for y in l.shapes_y] if p else [0] * 5
                success = test_shapes(sx, sy, clair)
            if not success and p is not None:
                sx = list(p.shapes_y)
                sy = [p.page_width - x for x in p.shapes_x]
                success = test_shapes(sx, sy, clair)
            if not success and p is not None:
                sx = [p.page_height - y for y in p.shapes_y]
                sy = list(p.shapes_x)
                success = test_shapes(sx, sy, clair)
            if success:
                clair = 230
                break
    return success


def align_viewer(page: ScannedPage, variants: dict) -> None:
    """Détermine l'orientation et calcule ``page.adjust`` (rotation + échelle).

    Reprend ``Page.alignViewer`` (index.html ~2328-2660). Les 5 repères sont
    classés (haut-gauche, intérieur, bas-gauche, bas-droit, haut-droit) puis on
    calcule la rotation et l'échelle moyennes par rapport au layout de référence.
    """
    if len(page.shapes) != 5:
        return

    # 1. Les deux repères les plus proches (i1, i2).
    i1 = i2 = -1
    dist_min = float("inf")
    for i in range(5):
        for j in range(i + 1, 5):
            dx = page.shapes[i]["canvas_x"] - page.shapes[j]["canvas_x"]
            dy = page.shapes[i]["canvas_y"] - page.shapes[j]["canvas_y"]
            d = dx * dx + dy * dy
            if d < dist_min:
                i1, i2, dist_min = i, j, d

    # 2. Parmi les 3 autres, on cherche le plus éloigné d'un des deux (bottom_right)
    #    et le plus proche de l'autre (inner).
    others = [i for i in range(5) if i not in (i1, i2)]
    dist_max = 0
    i3 = i4 = i5 = -1
    for i in others:
        dx1 = page.shapes[i]["canvas_x"] - page.shapes[i1]["canvas_x"]
        dy1 = page.shapes[i]["canvas_y"] - page.shapes[i1]["canvas_y"]
        dist1 = dx1 * dx1 + dy1 * dy1
        dx2 = page.shapes[i]["canvas_x"] - page.shapes[i2]["canvas_x"]
        dy2 = page.shapes[i]["canvas_y"] - page.shapes[i2]["canvas_y"]
        dist2 = dx2 * dx2 + dy2 * dy2
        if dist1 > dist2:
            if dist1 > dist_max:
                i3, i5, i4, dist_max = i1, i2, i, dist1
        else:
            if dist2 > dist_max:
                i3, i5, i4, dist_max = i2, i1, i, dist2

    inner = i5
    top_left = i3
    bottom_right = i4
    # Les deux points restants → bottom_left et top_right (assignation puis vérif).
    remaining = [i for i in range(5) if i not in (inner, bottom_right, top_left)]
    if len(remaining) != 2:
        return
    bottom_left, top_right = remaining[0], remaining[1]

    # Vérification de l'assignation.
    def dist2(a, b):
        dx = page.shapes[a]["canvas_x"] - page.shapes[b]["canvas_x"]
        dy = page.shapes[a]["canvas_y"] - page.shapes[b]["canvas_y"]
        return dx * dx + dy * dy

    d1 = dist2(bottom_left, inner)
    d2 = dist2(bottom_left, top_left)
    if d2 < d1:
        bottom_left, top_right = top_right, bottom_left
        d1 = dist2(bottom_left, inner)
        d2 = dist2(bottom_left, top_left)
        if d2 < d1:
            return  # invalid shapes

    canvas_cx = (page.shapes[top_left]["canvas_x"] + page.shapes[top_right]["canvas_x"]
                 + page.shapes[bottom_left]["canvas_x"] + page.shapes[bottom_right]["canvas_x"]) / 4
    canvas_cy = (page.shapes[top_left]["canvas_y"] + page.shapes[top_right]["canvas_y"]
                 + page.shapes[bottom_left]["canvas_y"] + page.shapes[bottom_right]["canvas_y"]) / 4

    def delta_angle(idx):
        dx = page.shapes[idx]["canvas_x"] - canvas_cx
        dy = page.shapes[idx]["canvas_y"] - canvas_cy
        return math.atan2(dy, dx), math.sqrt(dx * dx + dy * dy)

    angles = {}
    dists = {}
    for name, idx in (("tl", top_left), ("tr", top_right),
                       ("bl", bottom_left), ("br", bottom_right)):
        angles[name], dists[name] = delta_angle(idx)

    def adjust_orientation(orientation):
        layout = _layout_of(variants, orientation)
        if layout is None:
            return None
        center_x = (layout.shapes_x[0] + layout.shapes_x[2] + layout.shapes_x[3] + layout.shapes_x[4]) / 4
        center_y = (layout.shapes_y[0] + layout.shapes_y[2] + layout.shapes_y[3] + layout.shapes_y[4]) / 4
        l_angles = {}
        l_dists = {}
        for name, idx in (("tl", 0), ("tr", 4), ("bl", 2), ("br", 3)):
            dx = layout.shapes_x[idx] - center_x
            dy = layout.shapes_y[idx] - center_y
            l_angles[name] = math.atan2(dy, dx)
            l_dists[name] = math.sqrt(dx * dx + dy * dy)

        M_2PI = 2.0 * math.pi
        M_M_PI_4 = -0.25 * math.pi
        M_9PI_4 = 2.25 * math.pi

        def norm(r):
            while r < M_M_PI_4:
                r += M_2PI
            while r >= M_9PI_4:
                r -= M_2PI
            return r

        rot = {}
        for name in ("tl", "tr", "bl", "br"):
            rot[name] = norm(l_angles[name] - angles[name])
        rotate_mean = sum(rot.values()) / 4
        sigma = math.sqrt(sum((rot[n] - rotate_mean) ** 2 for n in rot))
        scales = [l_dists[n] / dists[n] if dists[n] else 0 for n in dists]
        scale_mean = sum(scales) / 4
        scale_sigma = math.sqrt(sum((s - scale_mean) ** 2 for s in scales))
        return {
            "orientation": orientation,
            "center_x": center_x,
            "center_y": center_y,
            "canvas_center_x": canvas_cx,
            "canvas_center_y": canvas_cy,
            "rotate_mean": rotate_mean,
            "rotate_sigma": sigma,
            "scale_mean": scale_mean,
            "scale_sigma": scale_sigma,
        }

    ap = adjust_orientation("p")
    al = adjust_orientation("l")
    if ap is None and al is None:
        raise RuntimeError("Charger le projet avant de lancer la correction.")
    if al is None:
        page.adjust = ap
    elif ap is None:
        page.adjust = al
    elif (ap["rotate_sigma"] < al["rotate_sigma"]
          and ap["scale_sigma"] < al["scale_sigma"]):
        page.adjust = ap
    elif (al["rotate_sigma"] < ap["rotate_sigma"]
          and al["scale_sigma"] < ap["scale_sigma"]):
        page.adjust = al
    else:
        raise RuntimeError("Copie invalide.")


# ---------------------------------------------------------------------------
# Lecture du code-barres
# ---------------------------------------------------------------------------

def _bresenham_pixels(pimg: PixelImage, x1: int, y1: int, x2: int, y2: int,
                      scale: float, origin_x: float, origin_y: float) -> list[dict]:
    """Parcourt le segment (x1,y1)→(x2,y2) et collecte les pixels (x, g).

    Reprend l'algorithme de Bresenham du JS (index.html ~2890-3160) avec une
    implémentation Python simplifiée mais équivalente (parcours par pas entier).
    Chaque pixel est enregistré avec sa position ``x`` (distance mm depuis
    l'origine) et ``g`` (niveau de gris inversé : 128 - grey, positif = sombre).
    """
    pixels: list[dict] = []
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    err = dx - dy
    x, y = x1, y1
    while True:
        grey, a = pimg.get_grey(x, y)
        if a != 255:
            grey = 255
        # distance depuis l'extrémité (x2, y2)
        delta_x = x - x2
        delta_y = y - y2
        dist = math.sqrt(delta_x * delta_x + delta_y * delta_y)
        pixels.append({"x": scale * dist, "g": 128 - grey})
        if x == x2 and y == y2:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
        if x < 0 or y < 0 or x >= pimg.width or y >= pimg.height:
            break
    return pixels


def _correlate_character(pixels: list[dict], char: str, start: int,
                         barcode_resolution: float) -> float:
    """Corrélation d'un caractère Code 39 avec les pixels à partir de ``start``.

    Reprend ``correlate_character`` (index.html ~3140-3200).
    """
    code = CODE39.get(char)
    if code is None or start >= len(pixels):
        return 0.0
    i = start
    length = len(pixels)
    value = 0.0
    s = pixels[i]["x"]
    res3 = 3 * barcode_resolution
    for j, bit in enumerate(code):
        bar_width = res3 if bit == "1" else barcode_resolution
        if j % 2 == 0:  # barre noire : contribution positive
            while (s - pixels[i]["x"]) <= bar_width:
                value += pixels[i]["w"] * pixels[i]["g"] if "w" in pixels[i] else pixels[i]["g"]
                i += 1
                if i >= length:
                    return 0.0
        else:  # barre blanche : contribution négative
            while (s - pixels[i]["x"]) <= bar_width:
                value -= pixels[i]["w"] * pixels[i]["g"] if "w" in pixels[i] else pixels[i]["g"]
                i += 1
                if i >= length:
                    return 0.0
        s -= bar_width
    # Petite barre blanche finale.
    while i < length and (s - pixels[i]["x"]) <= barcode_resolution:
        value -= pixels[i]["w"] * pixels[i]["g"] if "w" in pixels[i] else pixels[i]["g"]
        i += 1
    return value


def read_barcode_line(pimg: PixelImage, matrix: Matrix, layout: Layout,
                      left_x: float, left_y: float,
                      right_x: float, right_y: float) -> str:
    """Lit une ligne de code-barres et renvoie le texte décodé.

    Reprend ``readBarcodeLine`` (index.html ~2806-3160) : tracé de Bresenham,
    calcul des poids, repérage des '*' de début/fin, puis corrélation caractère
    par caractère.
    """
    dist_x = right_x - left_x
    dist_y = right_y - left_y
    dist = math.sqrt(dist_x * dist_x + dist_y * dist_y)
    mi = matrix.inverse()
    cl_x, cl_y = mi.apply(left_x, left_y)
    cr_x, cr_y = mi.apply(right_x, right_y)
    cl_x, cl_y = round(cl_x), round(cl_y)
    cr_x, cr_y = round(cr_x), round(cr_y)
    canvas_left = min(cl_x, cr_x)
    canvas_top = min(cl_y, cr_y)
    canvas_w = abs(cr_x - cl_x) + 1
    canvas_h = abs(cr_y - cl_y) + 1
    canvas_dist = math.sqrt(canvas_w * canvas_w + canvas_h * canvas_h)
    scale = dist / canvas_dist if canvas_dist else 1.0

    pixels = _bresenham_pixels(pimg, cl_x, cl_y, cr_x, cr_y, scale, cl_x, cl_y)
    if len(pixels) < 2:
        return ""

    # Poids de chaque pixel (moyenne des distances aux voisins).
    pixels[0]["w"] = 0.0
    for i in range(1, len(pixels) - 1):
        pixels[i]["w"] = abs(pixels[i - 1]["x"] - pixels[i + 1]["x"]) / 2
    pixels[-1]["w"] = 0.0

    barcode_angle = math.atan2(left_y - right_y, left_x - right_x)
    cos_a = math.cos(barcode_angle)
    res = abs(layout.barcode_resolution / cos_a) if cos_a != 0 else layout.barcode_resolution

    correlate_threshold = 16 * layout.barcode_resolution * 128 * 0.5

    # Recherche du '*' de début.
    first_pos = None
    first_weight = None
    for i in range(len(pixels) // 2 - 1):
        c = _correlate_character(pixels, "*", i, res)
        if c >= correlate_threshold:
            if first_weight is None or c > first_weight:
                first_pos = i
                first_weight = c
        elif first_pos is not None:
            break

    # Recherche du '*' de fin.
    last_pos = None
    last_weight = None
    for i in range(len(pixels) - 1, len(pixels) // 2 + 1, -1):
        c = _correlate_character(pixels, "*", i, res)
        if c >= correlate_threshold:
            if last_weight is None or c > last_weight:
                last_pos = i
                last_weight = c
        elif last_pos is not None:
            break

    if first_pos is None or last_pos is None:
        return ""

    characters = list(CODE39.keys())
    first_x = pixels[first_pos]["x"]
    last_x = pixels[last_pos]["x"]
    nb_chars = layout.barcode_length
    result = ""
    left = 0
    for i in range(nb_chars):
        position = (first_x * (nb_chars - 1 - i) + last_x * i) / (nb_chars - 1)
        right = len(pixels) - 1
        # Recherche dichotomique du pixel le plus proche de ``position``.
        while left < right:
            middle = (left + right) // 2
            middle_pos = pixels[middle]["x"]
            if middle_pos == position:
                left = middle
                break
            elif middle_pos > position:
                left = middle + 1
            else:
                right = middle
        max_weight = 0.0
        max_char = ""
        for ch in characters:
            c = _correlate_character(pixels, ch, left, res)
            if c > max_weight:
                max_weight = c
                max_char = ch
        if max_weight == 0:
            if pixels[left]["g"] > 0:
                left -= 1
            else:
                left += 1
            for ch in characters:
                c = _correlate_character(pixels, ch, left, res)
                if c > max_weight:
                    max_weight = c
                    max_char = ch
        result += max_char
    return result


def read_barcode(page: ScannedPage, variants: dict, matrix: Matrix) -> bool:
    """Lit le code-barres de la page (teste 4 orientations de ligne).

    Reprend ``Page.readBarcode`` (index.html ~2806-2870).
    """
    layout = _layout_of(variants, page.adjust["orientation"]) if page.adjust else None
    if layout is None:
        return False
    bl_x = layout.shapes_x[2] + 3
    bl_y = layout.shapes_y[2]
    br_x = layout.shapes_x[3] - 3
    br_y = layout.shapes_y[3]
    pimg = page.img

    variant_ids = [k for k in variants if k not in ("p", "l")]

    def check_result(val: str) -> bool:
        for vid in variant_ids:
            variant = variants[vid]
            ref = "".join(c if c in CODE39 else " " for c in variant.barcode_text)
            if ref == val:
                page.barcode = val
                page.variant_id = variant.id
                return True
            if ref[-5:] == val[-5:]:
                page.barcode = val
                page.variant_id = variant.id
                return True
        return False

    for (lx, ly, rx, ry) in [
        (bl_x, bl_y, br_x, br_y),
        (bl_x, br_y, br_x, bl_y),
        (bl_x, bl_y, br_x, bl_y),
        (bl_x, br_y, br_x, br_y),
    ]:
        if check_result(read_barcode_line(pimg, matrix, layout, lx, ly, rx, ry)):
            return True
    return False


# ---------------------------------------------------------------------------
# Lecture d'une case (mark)
# ---------------------------------------------------------------------------

def read_mark(pimg: PixelImage, matrix_inv: Matrix,
              page_x: float, page_y: float, radius: float,
              clair: float) -> bool:
    """Détermine si une case (cercle) est cochée.

    Reprend ``Page.readMark`` (index.html ~3220-3270). Compte les pixels
    sombres/moyens/clairs dans le cercle et applique les seuils du code original.
    """
    canvas_radius = abs(round(matrix_inv.a * radius + matrix_inv.b * radius))
    canvas_radius = max(canvas_radius, 1)
    cx, cy = matrix_inv.apply(page_x, page_y)
    canvas_left = int(cx - canvas_radius)
    canvas_top = int(cy - canvas_radius)
    canvas_w = 2 * canvas_radius + 1
    canvas_h = 2 * canvas_radius + 1

    dark = 0
    medium = 0
    bright = 0
    for yy in range(canvas_top, canvas_top + canvas_h):
        for xx in range(canvas_left, canvas_left + canvas_w):
            grey, alpha = pimg.get_mark_grey(xx, yy)
            if alpha == 255:
                # Seuils du code original : sombre si grey < 2*clair/3,
                # moyen si grey < clair, sinon clair.
                if grey < 2 * clair / 3:
                    dark += 1
                elif grey < clair:
                    medium += 1
                else:
                    bright += 1
            else:
                bright += 1

    total = dark + medium + bright
    if total == 0:
        return False
    if dark >= 0.28 * total:
        return True
    if (dark + medium) >= 0.31 * total:
        return True
    return False


# ---------------------------------------------------------------------------
# Lecture du numéro étudiant
# ---------------------------------------------------------------------------

def read_student_id(page: ScannedPage, variants: dict,
                    matrix_inv: Matrix, clair_start: int = 10) -> bool:
    """Lit le numéro étudiant (7 chiffres) à partir des cases d'identification.

    Reprend ``Page.readStudentId`` (index.html ~3294-3365).
    """
    variant = variants.get(str(page.variant_id)) if page.variant_id is not None else None
    if variant is None:
        return False
    page.student_id = None
    id_val = 0
    pimg = page.img

    if len(variant.id_columns) > len(variant.id_lines):
        # haut→bas puis gauche→droite.
        for digit in range(7):
            id_val *= 10
            found = False
            for clair in range(20, 241, 10):
                for value in range(10):
                    if read_mark(pimg, matrix_inv,
                                  variant.id_columns[value + 1],
                                  variant.id_lines[digit], 2.3, clair):
                        if found:
                            return False
                        found = True
                        clair = 250
                        id_val += value
                        value = 11  # sortir de la boucle
                        break
                if found:
                    break
            if not found:
                return False
    else:
        # gauche→droite puis haut→bas.
        for digit in range(7):
            id_val *= 10
            found = False
            for clair in range(clair_start, 241, 10):
                for value in range(10):
                    if read_mark(pimg, matrix_inv,
                                  variant.id_columns[digit],
                                  variant.id_lines[value + 1], 2.3, clair):
                        if found:
                            return False
                        found = True
                        clair = 250
                        id_val += value
                        value = 11
                        break
                if found:
                    break
            if not found:
                return False

    if id_val != 0:
        n_zeros = 7 - (len(str(id_val)))
        page.student_id = "p" + "0" * n_zeros + str(id_val)
    else:
        page.student_id = "p0000000"
    return True


# ---------------------------------------------------------------------------
# Détection automatique des cases cochées
# ---------------------------------------------------------------------------

CLAIR = 140  # variable globale du JS (index.html ligne 4)


def auto_marks(page: ScannedPage, matrix_inv: Matrix) -> None:
    """Détecte les cases cochées parmi les marks de la page.

    Reprend ``Page.autoMarks`` (index.html ~3365-3375).
    """
    if page.img is None:
        return
    pimg = page.img
    for mark in page.marks:
        if (mark.get("e") is not None and mark.get("q") is not None
                and mark.get("c") is not None and mark.get("r") is not None):
            mark["checked"] = any(
                read_mark(pimg, matrix_inv, mark["x"], mark["y"],
                          mark["r"], clair)
                for clair in range(CLAIR, 241, 10)
            )


def show_marks(page: ScannedPage, project: Project) -> None:
    """Initialise les marks d'une page à partir de la variante correspondante.

    Reprend ``Page.showMarks`` (index.html ~3583-3630).
    """
    if page.variant_id is None:
        return
    variant = project.variants.variant(page.variant_id)
    if variant is None:
        return
    for vmark in variant.marks:
        mark = {"x": vmark["x"], "y": vmark["y"], "e": vmark["e"], "q": vmark["q"]}
        if "r" in vmark and vmark["r"] is not None:
            mark["r"] = vmark["r"]
            mark["c"] = vmark["c"]
            mark["j"] = vmark.get("joker")
            choice = project.structure[mark["e"]].questions[mark["q"]].choices[mark["c"]]
            mark["correct"] = choice.correct
            mark["neutral"] = choice.neutral
            mark["penalty"] = choice.penalty
            mark["checked"] = False
        elif "w" in vmark and vmark["w"] is not None:
            mark["w"] = vmark["w"]
            mark["h"] = vmark["h"]
            question = project.structure[mark["e"]].questions[mark["q"]]
            mark["gain"] = float(question.gain)
            mark["penalty"] = float(question.penalty)
            mark["value"] = None
        page.marks.append(mark)


# ---------------------------------------------------------------------------
# Correction automatique complète d'une page
# ---------------------------------------------------------------------------

def auto_check(page: ScannedPage, project: Project,
               check_manual_active: bool = False) -> bool:
    """Corrige automatiquement une page : aligne, lit code-barres, n° étudiant,
    détecte les cases, calcule la note.

    Reprend ``Page.autoCheck`` (index.html ~3631-3645). Renvoie True si la
    correction a réussi (alignement + code-barres lus).
    """
    if page.ignore:
        return False
    vs = project.variants
    if not align_auto(page, vs):
        return False
    matrix = compute_viewport(page, vs,
                              page.img.width, page.img.height)["matrix"]
    matrix_inv = matrix.inverse()
    page.matrix = matrix
    page.matrix_inv = matrix_inv
    if not read_barcode(page, vs, matrix):
        return False
    read_student_id(page, vs, matrix_inv)
    if page.student_id is not None:
        student = project.students.get(page.student_id)
        if student is not None:
            page.student_eid = student.eid
            page.student_name = student.name
            page.student_firstname = student.firstname
    show_marks(page, project)
    auto_marks(page, matrix_inv)
    score = score_page(project, page.marks, variant_id=page.variant_id,
                       student_id=page.student_id,
                       check_manual_active=check_manual_active)
    page.value = score.value
    page.total = score.total
    page.complete = score.complete
    return True


# ---------------------------------------------------------------------------
# Rendu d'une page corrigée (overlay vert/rouge/jaune sur les cases)
# ---------------------------------------------------------------------------

_MARK_COLORS = {
    "yellow": (255, 255, 0),
    "green": (0, 255, 0),
    "red": (255, 0, 0),
    "blue": (0, 0, 255),
}


def _mark_color(mark: dict) -> str:
    """Couleur d'une mark selon la logique de updateUserInterface (index.html
    ~4634-4655) : jaune par défaut, vert si correcte cochée, rouge si
    pénalisante cochée, bleu si neutre cochée ou mark manuelle nulle."""
    if mark.get("value") is not None:
        v = mark["value"]
        if v > 0:
            return "green"
        if v < 0:
            return "red"
        return "blue"
    if mark.get("checked"):
        if mark.get("neutral"):
            return "blue"
        if mark.get("correct"):
            return "green"
        if mark.get("penalty"):
            return "red"
    return "yellow"


def render_marked_page(page: ScannedPage, max_width: int = 0):
    """Renvoie une image Pillow de la page avec l'overlay des cases.

    Reprend le rendu SVG de ``updateUserInterface`` (index.html ~4518-4655) :
    chaque mark (case à cocher ou zone manuelle) est dessinée par-dessus
    l'image scannée, colorée selon la logique vert/rouge/jaune/bleu.
    Les coordonnées des marks sont en mm (système page) et converties en
    pixels canvas via ``matrix_inv``.

    ``max_width`` (si > 0) limite la largeur de l'image renvoyée (pour
    l'affichage dans le GUI) en conservant les proportions.
    """
    from PIL import ImageDraw, Image as PILImage

    base = page.img.img if page.img is not None else None
    if base is None:
        return None
    img = base.convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    matrix_inv = page.matrix_inv
    if matrix_inv is None:
        return img

    for mark in page.marks:
        color = _MARK_COLORS[_mark_color(mark)]
        outline = color + (255,)
        fill = color + (26,)
        r = mark.get("r")
        if r is not None:
            cx, cy = matrix_inv.apply(mark["x"], mark["y"])
            canvas_r = abs(round(matrix_inv.a * r + matrix_inv.b * r))
            canvas_r = max(canvas_r, 1)
            bbox = [cx - canvas_r, cy - canvas_r, cx + canvas_r, cy + canvas_r]
            draw.ellipse(bbox, outline=outline, fill=fill, width=2)
        else:
            w = mark.get("w")
            h = mark.get("h")
            if w is not None and h is not None:
                cx, cy = matrix_inv.apply(mark["x"], mark["y"])
                cw = abs(round(matrix_inv.a * w + matrix_inv.b * w))
                ch = abs(round(matrix_inv.c * h + matrix_inv.d * h))
                bbox = [cx, cy, cx + cw, cy + ch]
                draw.rectangle(bbox, outline=outline, fill=fill, width=2)

    if max_width and max_width > 0 and img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)),
                         PILImage.LANCZOS)
    return img


# ---------------------------------------------------------------------------
# Chargement d'un fichier (PDF ou image)
# ---------------------------------------------------------------------------

def load_pages_from_file(path: str, dpi: int = 150) -> list[ScannedPage]:
    """Charge les pages d'un fichier PDF ou d'une image.

    Renvoie une liste de ``ScannedPage`` (une par page du PDF, ou une seule
    pour une image). Utilise **PyMuPDF** de préférence ; sinon **pdf2image**
    (nécessite ``poppler-utils``) comme repli pour les PDF.
    """
    ext = os.path.splitext(path)[1].lower()
    pages: list[ScannedPage] = []
    if ext == ".pdf":
        loaded = False
        # 1) PyMuPDF (préférable : pas de dépendance système).
        try:
            import pymupdf
            doc = pymupdf.open(path)
            for pdf_page in doc:
                pix = pdf_page.get_pixmap(dpi=dpi)
                img = Image.frombytes("RGB" if pix.alpha == 0 else "RGBA",
                                      (pix.width, pix.height), pix.samples)
                pages.append(ScannedPage(img=PixelImage(img)))
            doc.close()
            loaded = True
        except ImportError:
            pass
        # 2) Repli : pdf2image (nécessite poppler-utils installé).
        if not loaded:
            try:
                from pdf2image import convert_from_path
                images = convert_from_path(path, dpi=dpi)
                for img in images:
                    pages.append(ScannedPage(img=PixelImage(img)))
                loaded = True
            except ImportError:
                pass
        if not loaded:
            raise RuntimeError(
                "Aucune bibliothèque de rendu PDF disponible. Installez "
                "PyMuPDF (``pip install --user pymupdf``) ou pdf2image + "
                "poppler-utils (``urpmi python3-pdf2image poppler``).")
    else:
        img = Image.open(path)
        pages.append(ScannedPage(img=PixelImage(img)))
    return pages
