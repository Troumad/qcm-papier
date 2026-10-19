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
    matrix = scanner.compute_viewport(page, project.variants, page.img.width, page.img.height)["matrix"]
    p = scanner._layout_of(project.variants, "p")
    points = []
    for i in range(5):
        adj = scanner.align_adjust_shape(page.img, matrix, p.shapes_x[i], p.shapes_y[i], 30, 200)
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


def test_load_all_pages_from_state(tmp_path):
    """Restauration directe d'une sauvegarde : pages et images, sans rescan."""
    from qcm_papier.scanner import ScannedPage, load_all_pages_from_state, save_correction_state

    page = ScannedPage()
    page.copy_path = str(tmp_path / "copie1.pdf")
    page.variant_id = 1234
    page.student_id = "p1234567"
    page.value = 12.0
    page.total = 20.0
    page.complete = True
    from qcm_papier.scanner import Matrix

    page.matrix = Matrix()
    page.matrix_inv = Matrix().inverse()
    page.marks = [{"e": 0, "q": 0, "c": 0, "x": 20.0, "y": 20.0, "r": 2.0, "checked": True}]
    from PIL import Image as PILImage

    from qcm_papier.scanner import PixelImage

    page.img = PixelImage(PILImage.new("RGB", (40, 40), "white"))

    state_path = str(tmp_path / "correction.json")
    save_correction_state([page], [page.copy_path], state_path, project_path=str(tmp_path / "qcm.json"))

    loaded = load_all_pages_from_state(state_path)
    assert str(tmp_path / "copie1.pdf") in loaded
    pages = loaded[str(tmp_path / "copie1.pdf")]
    assert len(pages) == 1
    p = pages[0]
    assert p.variant_id == 1234
    assert p.student_id == "p1234567"
    assert p.value == 12.0
    assert p.img is not None


def test_reparation_joker_perdu_dans_ancienne_sauvegarde(tmp_path):
    """Une ancienne sauvegarde sans « j » est réparée au rechargement.

    La case joker cochée doit être reconnue (ligne seconde chance) et
    la note recalculée : première ligne pénalisante → -0,5 ; joker
    correct → +2.
    """
    import json

    from qcm_papier.model import Choice, Exercise, Project, Question
    from qcm_papier.scanner import (
        Matrix,
        PixelImage,
        ScannedPage,
        load_all_pages_from_state,
        save_correction_state,
    )

    question = Question(
        name="Q",
        gain=2.0,
        penalty=0.5,
        single=True,
        choices=[
            Choice(name="A", penalty=True, neutral=False, index=0),
            Choice(name="B", correct=True, neutral=False, penalty=False, index=1),
        ],
    )
    project = Project(structure=[Exercise(name="Exo", questions=[question])])

    # Variante 1 : deux cases ligne 1 + deux cases joker (y + 6).
    marks = [
        {"x": 10.0, "y": 10.0, "r": 2.3, "e": 0, "q": 0, "c": 0},
        {"x": 16.0, "y": 10.0, "r": 2.3, "e": 0, "q": 0, "c": 1},
        {"x": 10.0, "y": 16.0, "r": 2.3, "e": 0, "q": 0, "c": 0, "joker": True},
        {"x": 16.0, "y": 16.0, "r": 2.3, "e": 0, "q": 0, "c": 1, "joker": True},
    ]
    from qcm_papier.model import Variant

    project.variants["1"] = Variant(id=1, marks=marks)

    # Page : l'étudiant a coché A (ligne 1) et B (joker).
    page = ScannedPage()
    page.copy_path = str(tmp_path / "copie.pdf")
    page.variant_id = 1
    page.matrix = Matrix()
    page.matrix_inv = Matrix().inverse()
    page.marks = [
        {
            "e": 0,
            "q": 0,
            "c": 0,
            "x": 10.0,
            "y": 10.0,
            "r": 2.3,
            "checked": True,
            "correct": False,
            "neutral": False,
            "penalty": True,
        },
        {
            "e": 0,
            "q": 0,
            "c": 1,
            "x": 16.0,
            "y": 16.0,
            "r": 2.3,
            "checked": True,
            "correct": True,
            "neutral": False,
            "penalty": False,
        },
    ]
    from PIL import Image as PILImage

    page.img = PixelImage(PILImage.new("RGB", (40, 40), "white"))
    state_path = str(tmp_path / "correction.json")
    save_correction_state([page], [page.copy_path], state_path)

    # Simuler l'ancien bug : retirer les « j » de la sauvegarde.
    with open(state_path, encoding="utf-8") as f:
        data = json.load(f)
    for m in data["copies"][0]["page"]["marks"]:
        m.pop("j", None)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    loaded = load_all_pages_from_state(state_path, project=project)
    p = loaded[str(tmp_path / "copie.pdf")][0]
    # La case joker est reconnue et la note prend la seconde chance : +2.
    assert any(m.get("j") and m.get("checked") for m in p.marks)
    assert p.value == 2.0


def test_decompte_coherent_avec_la_note_apres_reparation(tmp_path):
    """Le décompte affiché doit correspondre exactement à la note de la copie.

    Après rechargement-réparation d'une ancienne sauvegarde, la somme du
    décompte (question par question) doit égaler la note recalculée —
    même source de calcul, même état de marks.
    """
    from PIL import Image as PILImage

    from qcm_papier.mailing import question_breakdown
    from qcm_papier.model import Choice, Exercise, Project, Question, Variant
    from qcm_papier.scanner import (
        Matrix,
        PixelImage,
        ScannedPage,
        load_all_pages_from_state,
        save_correction_state,
    )

    question = Question(
        name="Q",
        gain=2.0,
        penalty=0.5,
        single=True,
        choices=[
            Choice(name="A", penalty=True, neutral=False, index=0),
            Choice(name="B", correct=True, neutral=False, penalty=False, index=1),
        ],
    )
    project = Project(structure=[Exercise(name="Exo", questions=[question])])
    marks = [
        {"x": 10.0, "y": 10.0, "r": 2.3, "e": 0, "q": 0, "c": 0},
        {"x": 16.0, "y": 10.0, "r": 2.3, "e": 0, "q": 0, "c": 1},
        {"x": 10.0, "y": 16.0, "r": 2.3, "e": 0, "q": 0, "c": 0, "joker": True},
        {"x": 16.0, "y": 16.0, "r": 2.3, "e": 0, "q": 0, "c": 1, "joker": True},
    ]
    project.variants["1"] = Variant(id=1, marks=marks)

    # Étudiant : B en ligne 1 (correct, +2), pas de joker coché.
    page = ScannedPage()
    page.copy_path = str(tmp_path / "copie.pdf")
    page.variant_id = 1
    page.student_id = "p1234567"
    page.matrix = Matrix()
    page.matrix_inv = Matrix().inverse()
    page.marks = [
        {
            "e": 0,
            "q": 0,
            "c": 1,
            "x": 16.0,
            "y": 10.0,
            "r": 2.3,
            "checked": True,
            "correct": True,
            "neutral": False,
            "penalty": False,
        },
    ]
    # Note calculée lors de la correction fraîche (jokers connus) et stockée.
    from qcm_papier.marking import score_page

    score = score_page(project, page.marks, variant_id=1, student_id="p1234567")
    page.value = score.value
    page.total = score.total
    page.complete = score.complete
    page.img = PixelImage(PILImage.new("RGB", (40, 40), "white"))
    state_path = str(tmp_path / "correction.json")
    save_correction_state([page], [page.copy_path], state_path)

    loaded = load_all_pages_from_state(state_path, project=project)
    p = loaded[str(tmp_path / "copie.pdf")][0]
    # La note stockée (calculée à la correction fraîche) est exacte : 2/2.
    assert p.value == 2.0
    breakdown = question_breakdown(project, p)
    assert "Exo : 2/2" in breakdown
    assert "- Q : 2/2" in breakdown
    # Les anciennes sauvegardes ne stockent pas les cases non cochées :
    # l'étiquette « (incomplète) » peut apparaître sans impact sur la note.
    # (artefat d'affichage seulement, les valeurs de points restent exactes)


def test_image_exif_est_chargee_droite(tmp_path):
    """Une photo avec orientation EXIF 6 (90°) est chargée droite.

    Sans exif_transpose, les pixels restent tournés et l'image
    sauvegardée dans la correction apparaît de travers.
    """
    from PIL import Image as PILImage

    from qcm_papier.scanner import load_pages_from_file

    # Image brute « paysage » avec l'EXIF qui dit « tourner de 90° ».
    img = PILImage.new("RGB", (40, 20), "white")
    exif = PILImage.Exif()
    exif[274] = 6  # Orientation : tourner 90° CV
    path = str(tmp_path / "photo.jpg")
    img.save(path, exif=exif)
    pages = load_pages_from_file(path, dpi=150)
    assert len(pages) == 1
    assert pages[0].img.width == 20  # pivotée : 40x20 -> 20x40
    assert pages[0].img.height == 40


def test_render_redresse_une_page_tournee():
    """Le rendu final est remis à l'endroit (repères 3 points à gauche).

    Une page photographiée tournée d'un quart de tour (Ox page vers le bas
    de l'image) doit donner un rendu final avec la page droite.
    """
    from PIL import Image as PILImage

    from qcm_papier.scanner import Matrix, PixelImage, ScannedPage, render_marked_page

    # matrix_inv : Ox page -> bas de l'image (a=0, b=1), Oy page -> gauche.
    m = Matrix(a=0.0, b=1.0, c=-1.0, d=0.0, e=20.0, f=0.0)

    page = ScannedPage()
    page.img = PixelImage(PILImage.new("RGB", (20, 40), "white"))
    page.matrix_inv = m
    page.marks = [{"e": 0, "q": 0, "c": 0, "x": 10.0, "y": 100.0, "r": 2.0, "checked": True}]

    # Validation par pixel : un point noir placé en (3, 5) page (haut-gauche)
    # doit se retrouver en haut-gauche du rendu final, quelle que soit
    # l'orientation de la photo d'origine (test sur les 4 rotations).
    import numpy as np
    from PIL import Image as PILImage
    from PIL import ImageDraw

    from qcm_papier.scanner import Matrix, PixelImage

    for rot in (0, 90, 180, 270):
        W, H = (40, 20) if rot in (90, 270) else (20, 40)
        m = Matrix.compose(W / 2, H / 2, 1.0, rot, 10, 20)
        ix, iy = m.apply(3, 5)
        img = PILImage.new("RGB", (W, H), "white")
        ImageDraw.Draw(img).ellipse([ix - 2, iy - 2, ix + 2, iy + 2], fill="black")
        p = ScannedPage()
        p.matrix_inv = m
        p.img = PixelImage(img)
        out = render_marked_page(p).convert("RGB")
        a = np.asarray(out)
        ys, xs = np.where((a[:, :, 0] < 100) & (a[:, :, 1] < 100) & (a[:, :, 2] < 100))
        assert abs(xs.mean() - 3) <= 1.5, f"rot {rot}: x={xs.mean()}"
        assert abs(ys.mean() - 5) <= 1.5, f"rot {rot}: y={ys.mean()}"
        assert out.width == 20 and out.height == 40  # page portrait redressée
