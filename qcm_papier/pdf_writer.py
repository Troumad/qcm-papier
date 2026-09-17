"""Génération du PDF sujet (ReportLab).

Reproduit la fonction ``FileView`` du code JavaScript original
(index.html lignes ~6839-7050) : pour chaque copie demandée, on dessine
l'en-tête, le pied de page (lignes inversées), les repères d'alignement, le
code-barres Code 39, les cases du numéro étudiant, puis les textes, cercles
et rectangles de la variante.
"""

from __future__ import annotations

import io
from typing import IO

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as canvaslib

from .code39 import CODE39
from .model import Layout, Project, Variant

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


def _footer_lines(text: str) -> list[str]:
    """Lignes du pied de page dans l'ordre de dessin (du haut vers le bas).

    La dernière ligne du texte est dessinée à ``margin_bottom`` et les
    précédentes au-dessus, pour que le pied de page grandisse vers le haut
    comme la hauteur réservée (``footer_height``) le suppose.
    """
    return [line.strip() for line in text.split("\n") if line.strip()]


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
    # Interligne identique à la hauteur réservée par build_layout
    # (LINE_HEIGHT * 1.15 = 12/2.835 * 1.15 ≈ 4.87 mm), sinon l'en-tête dessiné
    # déborde sur la hauteur réservée et chevauche les cadres.
    from .generator import LINE_HEIGHT

    line_height_mm = LINE_HEIGHT * 1.15

    # En-tête (avec décalage vertical pour éviter la superposition)
    if layout.header_left:
        lines = layout.header_left.split("\n")
        for i, line in enumerate(lines):
            y = (page_h - margin_top - i * line_height_mm) * mm
            c.drawString(margin_left * mm, y, line.strip())
    if layout.header_middle:
        lines = layout.header_middle.split("\n")
        for i, line in enumerate(lines):
            y = (page_h - margin_top - i * line_height_mm) * mm
            c.drawCentredString(center * mm, y, line.strip())
    if layout.header_right:
        lines = layout.header_right.split("\n")
        for i, line in enumerate(lines):
            y = (page_h - margin_top - i * line_height_mm) * mm
            c.drawRightString((page_w - margin_right) * mm, y, line.strip())

    # Pied de page : la dernière ligne est à margin_bottom, les précédentes
    # au-dessus (le pied de page grandit vers le haut, comme footer_height).
    if layout.footer_left:
        for i, line in enumerate(_footer_lines(layout.footer_left)):
            y = (margin_bottom + (len(_footer_lines(layout.footer_left)) - 1 - i) * line_height_mm) * mm
            c.drawString(margin_left * mm, y, line)
    if layout.footer_middle:
        lines = _footer_lines(layout.footer_middle)
        for i, line in enumerate(lines):
            y = (margin_bottom + (len(lines) - 1 - i) * line_height_mm) * mm
            c.drawCentredString(center * mm, y, line)
    if layout.footer_right:
        lines = _footer_lines(layout.footer_right)
        for i, line in enumerate(lines):
            y = (margin_bottom + (len(lines) - 1 - i) * line_height_mm) * mm
            c.drawRightString((page_w - margin_right) * mm, y, line)


def _draw_shapes(c: canvaslib.Canvas, layout: Layout) -> None:
    """Dessine les 5 repères d'alignement (cercles pleins noirs)."""
    for i in range(len(layout.shapes_x)):
        x = layout.shapes_x[i] * mm
        y = layout.page_height * mm - layout.shapes_y[i] * mm
        r = layout.shapes_r[i] * mm
        c.circle(x, y, r, stroke=0, fill=1)


def _draw_variant(c: canvaslib.Canvas, variant: Variant, layout: Layout, page_height_mm: float) -> None:
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
            if (j > 0 and len(variant.id_lines) == 11) or (i > 0 and len(variant.id_columns) == 11):
                c.setStrokeColorRGB(0, 0, 0)
                c.setLineWidth(0.2)
                c.circle(x * mm, to_pdf_y(y), 2.3 * mm, stroke=1, fill=0)

    # Textes de la variante (noms de questions/choix).
    c.setFont("Helvetica", 12)
    for text in variant.texts:
        if text.get("center"):
            c.setFont("Helvetica", 6)
            # Centrage vertical dans les cercles. Police plus petite que
            # les labels d'identification : on remonte légèrement la baseline
            # pour compenser l'espace sous la baseline (centre optique).
            c.drawCentredString(text["x"] * mm, to_pdf_y(text["y"]) - 0.6 * mm, text.get("t", ""))
            c.setFont("Helvetica", 12)
        elif text.get("i"):
            # Texte en italique (introduction/header)
            c.setFont("Helvetica-Oblique", 12)
            c.drawString(text["x"] * mm, to_pdf_y(text["y"]), text.get("t", ""))
            c.setFont("Helvetica", 12)
        else:
            c.drawString(text["x"] * mm, to_pdf_y(text["y"]), text.get("t", ""))

    # Cercles (cases à cocher).
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
            c.circle(x, y, r * mm, stroke=1, fill=0)
        else:
            c.circle(x, y, -r * mm, stroke=1, fill=1)
    c.setDash()

    # Rectangles (cadres de questions/exercices, zones manuelles).
    c.setLineWidth(0.2)
    for rect in variant.rects:
        x = rect.get("x", 0) * mm
        y = to_pdf_y(rect.get("y", 0))  # Coin haut-gauche pour encadrer correctement
        c.rect(x, y, rect.get("w", 0) * mm, -rect.get("h", 0) * mm, stroke=1, fill=0)

    # Lignes de séparation pointillées (entre questions empilées).
    c.setLineWidth(0.2)
    for line in variant.lines:
        x = line.get("x", 0) * mm
        y = to_pdf_y(line.get("y", 0))
        w = line.get("w", 0) * mm
        c.setDash(0.5, 0.5)
        c.line(x, y, x + w, y)
    c.setDash()


def _shift_variant_y(variant: Variant, dy: float) -> None:
    """Translate verticalement (en mm) tous les éléments d'une variante.

    Les coordonnées des textes, cadres, cercles, lignes et de la boîte
    d'identification sont stockées en absolu (déjà décalées de ``id_y`` au
    moment de la génération). Quand la hauteur de l'en-tête ou du pied de
    page change après génération (projet chargé depuis JSON puis rendu sans
    --regenerate), ``id_y`` et tout ce qui en dérive doivent suivre le même
    décalage pour ne pas chevaucher le nouvel en-tête ni déborder sur le
    code-barres du bas de page.
    """
    if dy == 0:
        return
    variant.id_y += dy
    variant.id_lines = [y + dy for y in variant.id_lines]
    for array in (variant.texts, variant.rects, variant.circles, variant.marks, variant.lines):
        for item in array:
            if "y" in item:
                item["y"] += dy


def generate_pdf(project: Project, output: str | IO[bytes] | None = None, per_student: bool = False) -> bytes:
    """Génère le PDF sujet pour toutes les variantes du projet."""
    from reportlab.lib.pagesizes import A4, landscape

    # L'en-tête/pied de page est rafraîchi avant le rendu pour refléter les
    # champs d'information courants, même si le projet a été chargé avec des
    # layouts pré-générés (chemin `qcm-papier pdf` sans --regenerate, GTK, web).
    from .generator import _refresh_header_footer

    # Hauteurs d'en-tête et de pied de page AVANT rafraîchissement : servent
    # à translater les variantes déjà générées quand la hauteur réservée
    # change, sinon les cadres (calculés à partir de header_height) restent à
    # l'ancienne position et l'en-tête actualisé les chevauche. Le pied de
    # page est compensé symétriquement pour préserver l'espace vertical
    # disponible entre l'identification et le code-barres du bas.
    old_header_height: dict[str, float] = {}
    old_footer_height: dict[str, float] = {}
    for orientation in ("p", "l"):
        layout = project.variants.layout(orientation)
        if layout is not None:
            old_header_height[orientation] = layout.header_height
            old_footer_height[orientation] = layout.footer_height
            _refresh_header_footer(layout, project.settings)

    variant_ids = []
    for k in project.variants:
        if k not in ("p", "l"):
            variant_ids.append(k)

    if not variant_ids:
        raise ValueError("Aucune variante à générer : lancez d'abord la " "génération des variantes.")

    # Repositionnement des variantes déjà générées si l'en-tête ou le pied
    # de page a changé depuis leur génération. La translation est
    # (dh - df) : le haut suit la croissance de l'en-tête (vers le bas) et le
    # bas est remonté d'autant que le pied de page grandit, pour préserver
    # l'espace vertical disponible. Le décalage est nul pour une variante
    # générée après le rafraîchissement (déjà à la bonne position).
    for vid in variant_ids:
        variant = project.variants.variant(vid)
        if variant is None:
            continue
        layout = project.variants.layout(variant.layout)
        if layout is None:
            continue
        dh = layout.header_height - old_header_height.get(variant.layout, layout.header_height)
        df = layout.footer_height - old_footer_height.get(variant.layout, layout.footer_height)
        _shift_variant_y(variant, dh - df)

    copy_count = project.settings.generate_students if per_student else len(variant_ids)

    buffer = io.BytesIO()
    c = None

    for i in range(copy_count):
        variant_id = variant_ids[i % len(variant_ids)]
        variant = project.variants.variant(variant_id)
        if variant is None:
            c = None  # Réinitialiser le canvas si variante invalide
            continue
        layout = project.variants.layout(variant.layout)
        if layout is None:
            c = None  # Réinitialiser le canvas si layout invalide
            continue

        # 1. Détermination unique du format de la page
        page_size = landscape(A4) if variant.layout == "l" else A4

        # 2. Initialisation ou création d'une nouvelle page avec la bonne taille
        if c is None:
            c = canvaslib.Canvas(buffer, pagesize=page_size)
        else:
            c.setPageSize(page_size)  # On change la taille AVANT de dessiner la nouvelle page

        # ✅ NOUVELLE LIGNE : Rotation anti-trigonométrique (90°)
        # c.setPageRotation(90)

        # 3. Nommer la page avec numéro de page et ID de variante
        page_number = i + 1
        c.setTitle(f"Page {page_number} - Variante {variant_id}")

        # 4. Dessin sur la page courante
        _draw_header_footer(c, layout)
        _draw_variant(c, variant, layout, layout.page_height)

        # 5. On valide la page (sauf si c'est la toute dernière, géré par le save)
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
