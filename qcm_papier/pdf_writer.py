"""Génération du PDF sujet (ReportLab).

Reproduit la fonction ``FileView`` du code JavaScript original
(index.html lignes ~6839-7050) : pour chaque copie demandée, on dessine
l'en-tête, le pied de page (lignes inversées), les repères d'alignement, le
code-barres Code 39, les cases du numéro étudiant, puis les textes, cercles
et rectangles de la variante.
"""

from __future__ import annotations

import io
from typing import IO, Any

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as canvaslib
from reportlab.lib.pagesizes import A4, landscape

from .code39 import CODE39
from .model import Layout, Project, Variant, VariantStore

# Format ReportLab : 'A3', 'A4', 'A5' en majuscule.
_REPORTLAB_FORMATS = {"a3": "A3", "a4": "A4", "a5": "A5"}

def _page_size(layout: Layout) -> tuple[float, float]:
    """Taille de page ReportLab (largeur, hauteur en points) selon le layout."""
    fmt = _REPORTLAB_FORMATS.get(layout.paper_format, "A4")
    from reportlab.lib.pagesizes import A3, A4, A5, landscape, portrait
    sizes = {"A3": A3, "A4": A4, "A5": A5}
    base = sizes[fmt]
    if layout.orientation == "l":
        return landscape(base)
    return portrait(base)

def _draw_code39(c: canvaslib.Canvas, variant: Variant, layout: Layout) -> None:
    """Dessine le code-barres Code 39 de la variante."""
    page_h = layout.page_height
    bar_left = variant.barcode_left * mm
    res = layout.barcode_resolution * mm
    bar_top = (page_h - layout.barcode_top - layout.barcode_height) * mm
    bar_h = layout.barcode_height * mm
    c.setFillColorRGB(0, 0, 0)
    for char in variant.barcode_text:
        code = CODE39.get(char, CODE39[" "])
        for i, bit in enumerate(code):
            width = res * (3 if bit == "1" else 1)
            if i % 2 == 0:  # barre pleine (noire)
                c.rect(bar_left, bar_top, width, bar_h, stroke=0, fill=1)
            bar_left += width
        bar_left += res  # espace inter-caractère

def _reverse_lines(text: str) -> str:
    """Inverse l'ordre des lignes (pied de page)."""
    lines = text.split("\n")
    return "\n".join(reversed(lines))

def _draw_header_footer(c: canvaslib.Canvas, layout: Layout) -> None:
    """Dessine l'en-tête (en haut) et le pied de page (en bas, lignes inversées)."""
    margin_left = layout.margin_left
    margin_top = layout.margin_top
    margin_right = layout.margin_right
    page_w = layout.page_width
    page_h = layout.page_height
    center = layout.page_center
    margin_bottom = layout.margin_bottom

    c.setFont("Helvetica", 12)
    line_height_mm = 7  # Espacement entre les lignes

    # En-tête (avec décalage vertical pour éviter la superposition)
    if layout.header_left:
        lines = layout.header_left.split('\n')
        for i, line in enumerate(lines):
            y = (page_h - margin_top - i * line_height_mm) * mm
            c.drawString(margin_left * mm, y, line.strip())
    if layout.header_middle:
        lines = layout.header_middle.split('\n')
        for i, line in enumerate(lines):
            y = (page_h - margin_top - i * line_height_mm) * mm
            c.drawCentredString(center * mm, y, line.strip())
    if layout.header_right:
        lines = layout.header_right.split('\n')
        for i, line in enumerate(lines):
            y = (page_h - margin_top - i * line_height_mm) * mm
            c.drawRightString((page_w - margin_right) * mm, y, line.strip())

    # Pied de page (lignes inversées)
    if layout.footer_left:
        c.drawString(margin_left * mm, margin_bottom * mm,
                     _reverse_lines(layout.footer_left))
    if layout.footer_middle:
        c.drawCentredString(center * mm, margin_bottom * mm,
                            _reverse_lines(layout.footer_middle))
    if layout.footer_right:
        c.drawRightString((page_w - margin_right) * mm, margin_bottom * mm,
                          _reverse_lines(layout.footer_right))

def _draw_shapes(c: canvaslib.Canvas, layout: Layout) -> None:
    """Dessine les 5 repères d'alignement (cercles pleins noirs)."""
    for i in range(len(layout.shapes_x)):
        x = layout.shapes_x[i] * mm
        y = layout.page_height * mm - layout.shapes_y[i] * mm
        r = layout.shapes_r[i] * mm
        c.circle(x, y, r, stroke=0, fill=1)

def _draw_variant(c: canvaslib.Canvas, variant: Variant,
                  layout: Layout, page_height_mm: float) -> None:
    """Dessine tous les éléments d'une variante sur la page courante."""
    def to_pdf_y(y_mm: float) -> float:
        # Le JS utilise y croissant vers le bas ; PDF y croissant vers le haut.
        return (page_height_mm - y_mm) * mm

    # Repères.
    _draw_shapes(c, layout)

    # Code-barres.
    _draw_code39(c, variant, layout)

    # Cases d'identification (cercles contour + étiquettes).
    c.setFont("Helvetica", 7)
    for i, x in enumerate(variant.id_columns):
        for j, y in enumerate(variant.id_lines):
            label = "_"
            if j > 0 and len(variant.id_lines) == 11:
                label = chr(47 + j)
            elif i > 0 and len(variant.id_columns) == 11:
                label = chr(47 + i)
            # Centrage vertical dans les cercles
            c.drawCentredString(x * mm, to_pdf_y(y) - 1 * mm, label)
            if ((j > 0 and len(variant.id_lines) == 11)
                    or (i > 0 and len(variant.id_columns) == 11)):
                c.setStrokeColorRGB(0, 0, 0)
                c.setLineWidth(0.2)
                c.circle(x * mm, to_pdf_y(y), 2.3 * mm, stroke=1, fill=0)

    # Textes de la variante (noms de questions/choix).
    c.setFont("Helvetica", 12)
    for text in variant.texts:
        if text.get("center"):
            c.setFont("Helvetica", 7)
            # Centrage vertical dans les cercles
            c.drawCentredString(text["x"] * mm, to_pdf_y(text["y"]) - 1 * mm,
                                text.get("t", ""))
            c.setFont("Helvetica", 12)
        else:
            c.drawString(text["x"] * mm, to_pdf_y(text["y"]), text.get("t", ""))

    # Cercles (cases à cocher).
    import time
    nb = int(time.time() * 1000) % 1000
    coups = 1
    c.setLineWidth(0.2)
    for circle in variant.circles:
        r = circle.get("r", 2.3)
        x = circle.get("x", 0) * mm
        y = to_pdf_y(circle.get("y", 0))
        if circle.get("dash"):
            c.setDash(0.5, 0.5)
        else:
            c.setDash()
        if r > 0:
            c.circle(x, y, abs(r) * mm, stroke=1, fill=0)
        else:
            coups += 2
            if (nb % coups) % 2 == 0:
                c.setFillColorRGB(0, 0, 0)
                c.circle(x, y, abs(r) * mm, stroke=1, fill=1)
                c.setFillColorRGB(0, 0, 0)
            else:
                c.circle(x, y, abs(r) * mm, stroke=1, fill=0)
    c.setDash()

    # Rectangles (cadres de questions/exercices, zones manuelles).
    c.setLineWidth(0.2)
    for rect in variant.rects:
        x = rect.get("x", 0) * mm
        y = to_pdf_y(rect.get("y", 0))  # Coin haut-gauche pour encadrer correctement
        c.rect(x, y, rect.get("w", 0) * mm, -rect.get("h", 0) * mm,
               stroke=1, fill=0)
        
def generate_pdf(project: Project, output: str | IO[bytes] | None = None,
                 per_student: bool = False) -> bytes:
    """Génère le PDF sujet pour toutes les variantes du projet."""
    from reportlab.lib.pagesizes import A4, landscape

    variant_ids = [k for k in project.variants.keys() if k not in ("p", "l")]
    if not variant_ids:
        raise ValueError("Aucune variante à générer : lancez d'abord la "
                         "génération des variantes.")

    copy_count = project.settings.generate_students if per_student else len(variant_ids)

    buffer = io.BytesIO()
    c = None

    for i in range(copy_count):
        variant = project.variants.variant(variant_ids[i % len(variant_ids)])
        if variant is None:
            continue
        layout = project.variants.layout(variant.layout)
        if layout is None:
            continue

        # 1. Détermination unique du format de la page
        page_size = landscape(A4) if variant.layout == "l" else A4

        # 2. Initialisation ou création d'une nouvelle page avec la bonne taille
        if c is None:
            c = canvaslib.Canvas(buffer, pagesize=page_size)
        else:
            c.setPageSize(page_size)  # On change la taille AVANT de dessiner la nouvelle page

        # 3. Dessin sur la page courante
        _draw_header_footer(c, layout)
        _draw_variant(c, variant, layout, layout.page_height)
        
        # 4. On valide la page (sauf si c'est la toute dernière, géré par le save)
        if i < copy_count - 1:
            c.showPage()

    if c is not None:
        c.save()

    data = buffer.getvalue()
    if output is not None:
        if isinstance(output, str):
            with open(output, "wb") as f:
                f.write(data)
        else:
            output.write(data)
    return data
