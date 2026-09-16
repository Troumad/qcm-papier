"""Tests du scanner : alignement manuel des 5 repères + correction.

Couvre le point « si le programme ne trouve pas les 5 points d'orientation,
il demande qu'on les mette à la main et après, il peut essayer de corriger la
feuille en faisant une transformation affine de la page ».
"""

import pytest

from qcm_papier import generator, model, pdf_writer, scanner


def _make_project(count: int = 2) -> model.Project:
    p = model.Project()
    p.settings.evaluation_short = "TEST"
    p.settings.module_short = "M"
    p.settings.year = "24"
    ex = model.Exercise(name="Exercice 1", index=0)
    q = model.Question(name="Q1", gain=2.0, penalty=1.0, single=True, index=0)
    q.choices = [
        model.Choice(name="A", correct=True, neutral=False, index=0),
        model.Choice(name="B", correct=False, neutral=False, penalty=True, index=1),
        model.Choice(name="C", correct=False, neutral=True, index=2),
        model.Choice(name="D", correct=False, neutral=True, index=3),
    ]
    ex.questions = [q]
    p.structure = [ex]
    p.settings.generate_count = count
    p.settings.generate_variants = ""
    p.settings.header_left = ""
    p.settings.header_middle = ""
    p.settings.header_right = ""
    return p


def _project_and_page(tmp_path):
    """Génère un projet + PDF, renvoie (projet, première page scannée)."""
    p = _make_project(count=1)
    p.settings.generate_variants = "4"
    generator.generate_all(p, retry=False)
    out = tmp_path / "sujet.pdf"
    pdf_writer.generate_pdf(p, str(out))
    pages = scanner.load_pages_from_file(str(out), dpi=150)
    assert len(pages) >= 1
    return p, pages[0]


def _layout_points_pixels(page, project):
    """Calcule les 5 positions des repères en pixels canvas (sans rotation),
    comme si l'utilisateur les cliquait sur l'image scannée alignée."""
    matrix = scanner.compute_viewport(page, project.variants,
                                       page.img.width, page.img.height)["matrix"]
    p = scanner._layout_of(project.variants, "p")
    points = []
    for i in range(5):
        adj = scanner.align_adjust_shape(page.img, matrix,
                                          p.shapes_x[i], p.shapes_y[i], 30, 200)
        points.append((adj["canvas_x"], adj["canvas_y"]))
    return points


def test_align_manual_calcule_adjust(tmp_path):
    """align_manual place 5 repères et calcule page.adjust (transformation affine)."""
    project, page = _project_and_page(tmp_path)
    # L'auto-alignement réussit sur le PDF généré ; on l'efface pour forcer
    # le scénario manuel (repères introuvables par l'auto).
    page.clear_marks()
    points = _layout_points_pixels(page, project)
    assert len(points) == 5
    ok = scanner.align_manual(page, project.variants, points)
    assert ok
    assert page.adjust is not None
    assert len(page.shapes) == 5


def test_correct_with_manual_align(tmp_path):
    """correct_with_manual_align aligne à la main puis corrige la page."""
    project, page = _project_and_page(tmp_path)
    page.clear_marks()
    points = _layout_points_pixels(page, project)
    ok = scanner.correct_with_manual_align(page, project, points, clair=140)
    assert ok
    assert page.variant_id is not None  # code-barres lu après alignement manuel
    assert page.matrix is not None
    assert page.matrix_inv is not None
    assert page.value is not None


def test_align_manual_rejette_mauvais_nombre_points(tmp_path):
    """align_manual refuse autre chose que 5 points."""
    project, page = _project_and_page(tmp_path)
    page.clear_marks()
    assert scanner.align_manual(page, project.variants, [(10, 10)]) is False
    assert scanner.align_manual(page, project.variants, [(0, 0)] * 6) is False


def test_auto_check_refactore_compatble(tmp_path):
    """auto_check conserve son comportement (alignement auto → correction)."""
    project, page = _project_and_page(tmp_path)
    page.clear_marks()
    assert scanner.auto_check(page, project) is True
    assert page.variant_id is not None


def test_align_auto_global_recupere_page_mal_scannee():
    """La 6e copie de correction3.pdf est mal scannée (fortement
    décalée/rotée) : l'alignement local échoue mais la recherche globale
    des 5 repères la récupère et permet la correction.

    Reprend le cas de test réel signalé par l'utilisateur (copie 6 de
    math/2026/correction3.pdf avec math/2026/OML1_bis.json).
    """
    import os
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdf = os.path.join(repo, "math", "2026", "correction3.pdf")
    jsonf = os.path.join(repo, "math", "2026", "OML1_bis.json")
    if not (os.path.exists(pdf) and os.path.exists(jsonf)):
        # Signalé comme « ignoré » (et non comme réussi) : sans les copies de
        # test, rien n'est vérifié.
        pytest.skip("correction3.pdf ou OML1_bis.json absent : données de test indisponibles")
    from qcm_papier.project import load_project
    project = load_project(jsonf)
    pages = scanner.load_pages_from_file(pdf)
    assert len(pages) >= 6
    page = pages[5]  # 6e copie (index 5)
    # La recherche globale des repères récupère cette page mal scannée
    # (que l'alignement local seul ne peut pas aligner).
    assert scanner.align_auto_global(page, project.variants) is True
    assert page.adjust is not None
    # auto_check (qui enchaîne align_auto + repli global + correction)
    # corrige la page : variante lue, note calculée.
    page.clear_marks()
    assert scanner.auto_check(page, project) is True
    assert page.variant_id is not None
    assert page.value is not None
