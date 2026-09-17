"""Positionnement des cadres quand l'en-tête change après génération.

Un projet chargé depuis JSON a des variantes pré-générées : leurs cadres
(boîte d'identification, exercices) sont positionnés à partir de
``header_height`` au moment de la génération. Si l'en-tête est modifié
ensuite (champs d'information vides → modèles par défaut à 3 lignes) et
que le PDF est rendu sans ``--regenerate`` (chemin ``cmd_pdf``), le
rafraîchissement de l'en-tête doit repositionner les cadres, sinon le
texte de l'en-tête chevauche le cadre d'identification.
"""

import pymupdf

from qcm_papier import editing, generator, pdf_writer
from qcm_papier.model import Choice, Exercise, Project, Question

MM = 72 / 25.4  # points → mm


def _project_one_line_header() -> Project:
    """Variante générée avec un en-tête d'une seule ligne."""
    p = Project()
    ex = Exercise(name="Exercice 1", index=0)
    q = Question(name="Q1", gain=1.0, penalty=0.5, single=True, index=0)
    q.choices = [
        Choice(name="A", correct=True, neutral=False, index=0),
        Choice(name="B", correct=False, neutral=False, penalty=True, index=1),
    ]
    ex.questions = [q]
    p.structure = [ex]
    p.settings.generate_count = 1
    p.settings.generate_variants = ""
    p.settings.header_left = "Une seule ligne"
    p.settings.header_middle = "Une seule ligne"
    p.settings.header_right = "Une seule ligne"
    return p


def _reload(project: Project) -> Project:
    """Simule la sauvegarde puis le rechargement depuis JSON : fige les
    positions des variantes pré-générées (id_y, rects, etc.) telles
    qu'elles étaient à la génération."""
    return Project.from_dict(project.to_dict())


def _bbox_texts(page, needles):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            for s in line.get("spans", []):
                if any(k in s["text"] for k in needles):
                    out.append((s["bbox"], s["text"]))
    return out


def _id_rect(page):
    """Le cadre d'identification : le grand rectangle le plus en haut à
    gauche (x0 proche de la marge gauche)."""
    best = None
    for dr in page.get_drawings():
        r = dr["rect"]
        if r.width > 30 * MM and r.height > 30 * MM and r.x0 < 30 * MM and (best is None or r.y0 < best.y0):
            best = r
    return best


def _overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def test_en_tete_change_repositionne_cadre_identification():
    """L'en-tête à 3 lignes (défaut) ne chevauche pas le cadre d'identification
    d'une variante pré-générée avec un en-tête d'une ligne, sans regénération.

    Reproduit le chemin ``qcm-papier pdf`` (sans --regenerate) sur un projet
    sauvegardé puis rechargé : les cadres sont figés à la position de la
    génération, l'en-tête est rafraîchi au rendu.
    """
    p = _project_one_line_header()
    generator.generate_all(p, retry=True)
    # Sauvegarde/rechargement : fige id_y pour l'en-tête à 1 ligne.
    p = _reload(p)
    # L'en-tête passe au modèle par défaut (3 lignes) : la hauteur réservée
    # augmente, le cadre d'identification doit suivre au rendu PDF.
    p.settings.header_left = ""
    p.settings.header_middle = ""
    p.settings.header_right = ""
    editing.apply_info_defaults(p.settings)

    data = pdf_writer.generate_pdf(p)
    doc = pymupdf.open(stream=data, filetype="pdf")
    page = doc.load_page(0)
    header_texts = _bbox_texts(page, ["Année", "détacher", "Cette page"])
    id_rect = _id_rect(page)
    doc.close()

    assert header_texts, "L'en-tête par défaut devrait contenir le texte de détachement"
    assert id_rect is not None, "Le cadre d'identification devrait être présent"

    for bbox, text in header_texts:
        assert not _overlap(bbox, id_rect), (
            f"L'en-tête {text!r} (bas={bbox[3]/MM:.2f} mm) chevauche "
            f"le cadre d'identification (haut={id_rect.y0/MM:.2f} mm)"
        )


def test_numero_identifiant_dans_le_cadre():
    """Après repositionnement, le texte 'Numéro identifiant' reste bien
    à l'intérieur du cadre d'identification (et non au-dessus)."""
    p = _project_one_line_header()
    generator.generate_all(p, retry=True)
    p = _reload(p)
    p.settings.header_left = ""
    p.settings.header_middle = ""
    p.settings.header_right = ""
    editing.apply_info_defaults(p.settings)

    data = pdf_writer.generate_pdf(p)
    doc = pymupdf.open(stream=data, filetype="pdf")
    page = doc.load_page(0)
    numero = _bbox_texts(page, ["Numéro identifiant"])
    id_rect = _id_rect(page)
    doc.close()

    assert numero, "Le texte 'Numéro identifiant' devrait être présent"
    assert id_rect is not None
    bbox, _ = numero[0]
    assert bbox[1] >= id_rect.y0, (
        f"Le texte 'Numéro identifiant' (haut={bbox[1]/MM:.2f} mm) est "
        f"au-dessus du cadre (haut={id_rect.y0/MM:.2f} mm)"
    )


def test_repositionnement_nul_si_en_tete_stable():
    """Sans changement d'en-tête, le repositionnement ne déplace rien :
    le cadre reste à sa position de génération."""
    p = _project_one_line_header()
    generator.generate_all(p, retry=True)
    p = _reload(p)
    layout = p.variants.layout("p")
    vid = [int(k) for k in p.variants if k not in ("p", "l")][0]
    v = p.variants.variant(vid)
    id_y_before = v.id_y
    header_height_before = layout.header_height

    pdf_writer.generate_pdf(p)  # en-tête inchangé → décalage nul

    layout = p.variants.layout("p")
    v = p.variants.variant(vid)
    assert v.id_y == id_y_before
    assert layout.header_height == header_height_before


def test_repositionnement_paysage():
    """Le repositionnement s'applique aussi en orientation paysage ('l') :
    une variante paysage pré-générée avec un en-tête à une ligne voit son
    cadre d'identification translaté quand l'en-tête par défaut est appliqué
    au rendu."""
    p = Project()
    ex = Exercise(name="Exercice 1", index=0)
    q = Question(name="Q1", gain=1.0, penalty=0.5, single=True, index=0)
    q.choices = [
        Choice(name="A", correct=True, neutral=False, index=0),
        Choice(name="B", correct=False, neutral=False, penalty=True, index=1),
    ]
    ex.questions = [q]
    p.structure = [ex]
    p.settings.generate_count = 1
    p.settings.generate_variants = ""
    p.settings.paper_portrait = False
    p.settings.paper_landscape = True
    p.settings.paper_both = False
    p.settings.header_left = "Une seule ligne"
    p.settings.header_middle = "Une seule ligne"
    p.settings.header_right = "Une seule ligne"
    generator.generate_all(p, retry=True)
    p = _reload(p)
    layout = p.variants.layout("l")
    assert layout is not None, "Le layout paysage devrait exister"
    vid = [int(k) for k in p.variants if k not in ("p", "l")][0]
    v = p.variants.variant(vid)
    assert v.layout == "l"
    id_y_before = v.id_y
    header_height_before = layout.header_height

    p.settings.header_left = ""
    p.settings.header_middle = ""
    p.settings.header_right = ""
    editing.apply_info_defaults(p.settings)

    data = pdf_writer.generate_pdf(p)
    layout = p.variants.layout("l")
    v = p.variants.variant(vid)
    assert layout.header_height > header_height_before, "L'en-tête par défaut devrait être plus haut"
    assert v.id_y > id_y_before, "Le cadre paysage devrait avoir été translaté vers le bas"

    doc = pymupdf.open(stream=data, filetype="pdf")
    page = doc.load_page(0)
    header_texts = _bbox_texts(page, ["Année", "détacher", "Cette page"])
    id_rect = _id_rect(page)
    doc.close()
    assert id_rect is not None
    for bbox, text in header_texts:
        assert not _overlap(bbox, id_rect), (
            f"L'en-tête {text!r} (bas={bbox[3]/MM:.2f} mm) chevauche "
            f"le cadre d'identification paysage (haut={id_rect.y0/MM:.2f} mm)"
        )


def _project_full_page():
    """Page avec pied de page à plusieurs lignes (modèle par défaut).

    Sert à vérifier le rendu multi-lignes du pied de page au bas de la page.
    """
    p = Project()
    ex = Exercise(name="Exercice 1", index=0)
    q = Question(name="Q1", gain=1.0, penalty=0.5, single=True, index=0)
    q.choices = [
        Choice(name="A", correct=True, neutral=False, index=0),
        Choice(name="B", correct=False, neutral=False, penalty=True, index=1),
    ]
    ex.questions = [q]
    p.structure = [ex]
    p.settings.generate_count = 1
    p.settings.generate_variants = ""
    # Champs vides -> modèles par défaut (footer_middle sur 2 lignes).
    p.settings.header_left = ""
    p.settings.header_middle = ""
    p.settings.header_right = ""
    p.settings.footer_left = ""
    p.settings.footer_middle = ""
    p.settings.footer_right = ""
    return p


def test_pied_de_page_multiligne_rendu_sur_lignes_distinctes():
    """Le pied de page par défaut (2 lignes) est rendu sur deux lignes
    verticalement distinctes, et non collées sur une seule ligne avec un
    glyphe parasite (le ``\n`` n'est pas un saut de ligne pour ReportLab).

    Reproduit le bug : ``_reverse_lines`` concaténait les lignes inversées
    avec un ``\n`` passé à ``drawCentredString``, qui les affichait sur une
    seule ligne avec un carré noir au milieu.
    """
    p = _project_full_page()
    editing.apply_info_defaults(p.settings)
    generator.generate_all(p, retry=True)
    p = _reload(p)

    data = pdf_writer.generate_pdf(p)
    doc = pymupdf.open(stream=data, filetype="pdf")
    page = doc.load_page(0)
    # Lignes du pied de page (en bas, y PyMuPDF grand).
    ph = page.rect.height
    footer_spans = []
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            for s in line.get("spans", []):
                if s["bbox"][1] > ph - 20 * MM:
                    footer_spans.append((s["bbox"], s["text"]))
    doc.close()

    assert footer_spans, "Le pied de page par défaut devrait être rendu"
    texts = [t for _, t in footer_spans]
    # Les deux lignes du pied de page par défaut, sur des lignes distinctes.
    assert any("code barre" in t for t in texts), f"Premiere ligne du pied de page absente : {texts!r}"
    assert any("de la page des cadres" in t for t in texts), f"Deuxieme ligne du pied de page absente : {texts!r}"
    # Les deux lignes ont des y différents (lignes verticalement distinctes).
    ys = sorted({round(bbox[1]) for bbox, _ in footer_spans})
    assert len(ys) >= 2, (
        f"Le pied de page 2 lignes est rendu sur une seule ligne (y={ys}) : "
        f"le \n est traité comme un glyphe et non un saut de ligne"
    )
