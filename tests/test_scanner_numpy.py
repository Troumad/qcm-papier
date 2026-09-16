"""Équivalence des calculs numpy du scanner avec la lecture pixel par pixel.

Les fonctions de référence ci-dessous sont les boucles d'origine (avant numpy) :
les versions numpy doivent donner exactement les mêmes résultats, y compris
pour des zones qui débordent de l'image et des pixels non opaques.
"""

import math

import numpy as np
import pytest
from PIL import Image, ImageDraw

from qcm_papier import scanner

POSITIONS = [(30, 22), (2, 3), (58, 44), (-5, 10), (70, 50), (30.6, 21.4)]
MATRICES = [
    scanner.Matrix(),
    scanner.Matrix(a=1.2, b=0.3, c=-0.2, d=0.9, e=4.5, f=-2.7),
    scanner.Matrix(a=0, b=0.5, c=-0.5, d=0, e=40, f=3),
]


def _image(seed: int, w: int = 60, h: int = 45) -> scanner.PixelImage:
    """Image RGBA aléatoire, opaque à 90 % environ."""
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(h, w, 4), dtype=np.uint8)
    arr[..., 3] = np.where(rng.random((h, w)) < 0.9, 255, arr[..., 3])
    return scanner.PixelImage(Image.fromarray(arr))


def _align_adjust_shape_reference(pimg, matrix, page_x, page_y, range_mm, clair):
    mi = matrix.inverse()
    canvas_x = mi.a * page_x + mi.c * page_y + mi.e
    canvas_y = mi.b * page_x + mi.d * page_y + mi.f
    shape_rect_w = range_mm
    shape_rect_h = range_mm
    canvas_rect_w = max(round(abs(mi.a * shape_rect_w + mi.c * shape_rect_h)), 1)
    canvas_rect_h = max(round(abs(mi.b * shape_rect_w + mi.d * shape_rect_h)), 1)
    canvas_left = int(canvas_x - canvas_rect_w / 2)
    canvas_top = int(canvas_y - canvas_rect_h / 2)
    sum_x = 0.0
    sum_y = 0.0
    sum_c = 0
    for yy in range(canvas_top, canvas_top + canvas_rect_h):
        for xx in range(canvas_left, canvas_left + canvas_rect_w):
            grey, a = pimg.get_grey(xx, yy)
            if a == 255 and grey < clair:
                sum_x += xx - canvas_left
                sum_y += yy - canvas_top
                sum_c += 1
    canvas_radius = canvas_rect_w / shape_rect_w * 2 if shape_rect_w else 0
    if sum_c != 0:
        canvas_x = canvas_left + (sum_x / sum_c)
        canvas_y = canvas_top + (sum_y / sum_c)
    px, py = matrix.apply(canvas_x, canvas_y)
    score = sum_c / (math.pi * canvas_radius * canvas_radius) if canvas_radius else 0.0
    return {"page_x": px, "page_y": py, "canvas_x": canvas_x, "canvas_y": canvas_y, "score": score}


def _read_mark_reference(pimg, matrix_inv, page_x, page_y, radius, clair):
    canvas_radius = max(abs(round(matrix_inv.a * radius + matrix_inv.b * radius)), 1)
    cx, cy = matrix_inv.apply(page_x, page_y)
    canvas_left = int(cx - canvas_radius)
    canvas_top = int(cy - canvas_radius)
    canvas_w = 2 * canvas_radius + 1
    canvas_h = 2 * canvas_radius + 1
    dark = medium = bright = 0
    for yy in range(canvas_top, canvas_top + canvas_h):
        for xx in range(canvas_left, canvas_left + canvas_w):
            grey, alpha = pimg.get_mark_grey(xx, yy)
            if alpha == 255:
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
    return (dark + medium) >= 0.31 * total


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_grey_regions_identiques_aux_pixels(seed):
    pimg = _image(seed)
    for left, top, w, h in [(0, 0, 60, 45), (-4, -3, 12, 9), (50, 40, 20, 15), (70, 60, 5, 5), (10, 5, 1, 1)]:
        grey, opaque = pimg.grey_region(left, top, w, h)
        mark_grey, mark_opaque = pimg.mark_grey_region(left, top, w, h)
        for j in range(h):
            for i in range(w):
                g, a = pimg.get_grey(left + i, top + j)
                mg, _ = pimg.get_mark_grey(left + i, top + j)
                assert grey[j, i] == g
                assert mark_grey[j, i] == mg
                assert opaque[j, i] == (a == 255) == mark_opaque[j, i]


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("matrix", MATRICES, ids=["identite", "affine", "quart-de-tour"])
def test_align_adjust_shape_identique_a_la_boucle(seed, matrix):
    pimg = _image(seed)
    for page_x, page_y in POSITIONS:
        for range_mm in (1, 10, 25):
            for clair in (0, 90, 140, 210, 300):
                expected = _align_adjust_shape_reference(pimg, matrix, page_x, page_y, range_mm, clair)
                assert scanner.align_adjust_shape(pimg, matrix, page_x, page_y, range_mm, clair) == expected


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("matrix_inv", MATRICES, ids=["identite", "affine", "quart-de-tour"])
def test_read_mark_identique_a_la_boucle(seed, matrix_inv):
    pimg = _image(seed)
    results = set()
    for page_x, page_y in POSITIONS:
        for radius in (0.4, 2.3, 6):
            for clair in range(0, 400, 20):
                expected = _read_mark_reference(pimg, matrix_inv, page_x, page_y, radius, clair)
                assert scanner.read_mark(pimg, matrix_inv, page_x, page_y, radius, clair) is expected
                results.add(expected)
    assert results == {True, False}  # les deux issues sont bien couvertes


@pytest.mark.parametrize("angle", [-12, 0, 12])
def test_recherche_globale_sur_reperes_synthetiques(angle):
    """Le pré-filtre retrouve les cinq repères malgré rotation et faux candidats.

    Cette régression tourne aussi en CI, sans les copies réelles locales.
    """
    layout = scanner.Layout(
        shapes_x=[15, 15, 15, 195, 195],
        shapes_y=[15, 145, 282, 282, 15],
    )
    img = Image.new("RGBA", (700, 800), "white")
    draw = ImageDraw.Draw(img)
    rad = math.radians(angle)
    expected = [
        (
            round(150 + 1.8 * (x * math.cos(rad) - y * math.sin(rad))),
            round(100 + 1.8 * (x * math.sin(rad) + y * math.cos(rad))),
        )
        for x, y in zip(layout.shapes_x, layout.shapes_y, strict=False)
    ]
    for x, y in [*expected, (330, 300), (600, 500), (550, 720)]:
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="black")
    page = scanner.ScannedPage(img=scanner.PixelImage(img))
    assert scanner.align_auto_global(page, {"p": layout.to_dict()})
    assert page.adjust is not None
    assert len(page.shapes) == 5
    actual = {(shape["canvas_x"], shape["canvas_y"]) for shape in page.shapes}
    assert actual == set(expected)


def test_recherche_globale_sans_reperes():
    page = scanner.ScannedPage(img=scanner.PixelImage(Image.new("RGBA", (100, 140), "white")))
    assert scanner.align_auto_global(page, {"p": scanner.Layout().to_dict()}) is False
    assert page.adjust is None
