"""Tests du modèle de données et de la sérialisation JSON."""

import json

from qcm_papier import model, project as projmod


def _make_project() -> model.Project:
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
    return p


def test_model_round_trip():
    """Un projet sérialisé puis rechargé est identique."""
    p = _make_project()
    p.students = {"p0000001": model.Student(id="p0000001", eid="123",
                                            nip="p0000001", name="Doe",
                                            firstname="John")}
    data = p.to_dict()
    p2 = model.Project.from_dict(data)
    assert len(p2.structure) == 1
    assert p2.structure[0].name == "Exercice 1"
    assert len(p2.structure[0].questions) == 1
    assert p2.structure[0].questions[0].gain == 2.0
    assert len(p2.structure[0].questions[0].choices) == 4
    assert p2.structure[0].questions[0].choices[0].correct is True
    assert "p0000001" in p2.students
    assert p2.students["p0000001"].name == "Doe"


def test_project_json_round_trip(tmp_path):
    """Sauvegarde/chargement via fichier JSON, compatible format original."""
    p = _make_project()
    path = tmp_path / "qcm.json"
    projmod.save_project(p, str(path))
    # Le fichier est du JSON valide.
    with open(path) as f:
        data = json.load(f)
    # Format attendu : {settings, variants, structure, students}.
    assert "settings" in data
    assert "variants" in data
    assert "structure" in data
    # Rechargement.
    p2 = projmod.load_project(str(path))
    assert len(p2.structure) == 1
    assert p2.settings.evaluation_short == "TEST"


def test_project_json_round_numbers(tmp_path):
    """Les nombres sont arrondis à 1 décimale (compatible JS)."""
    p = _make_project()
    p.settings.margin_left = 12.3456789
    path = tmp_path / "qcm.json"
    projmod.save_project(p, str(path))
    with open(path) as f:
        data = json.load(f)
    assert data["settings"]["margin_left"] == 12.3  # arrondi à 1 décimale


def test_paper_formats():
    """Les formats A3/A4/A5 ont les bonnes dimensions portrait."""
    assert model.PAPER_FORMATS["a3"] == (297.0, 420.0)
    assert model.PAPER_FORMATS["a4"] == (210.0, 297.0)
    assert model.PAPER_FORMATS["a5"] == (148.5, 210.0)


def test_settings_defaults():
    """Les valeurs par défaut correspondent au code JS (boutons cochés)."""
    s = model.ProjectSettings()
    # Format papier A4 portrait par défaut.
    assert s.paper_a4 is True
    assert s.paper_portrait is True
    # Direction identification : left.
    assert s.identification_dir_left is True
    # Directions exercices/questions/choix : both (aléatoire).
    assert s.exercise_dir_both is True
    assert s.question_dir_both is True
    assert s.choice_dir_both is True
    # Ajouts fantômes : always.
    assert s.exercise_new_always is True
    assert s.question_new_always is True
    assert s.choice_new_always is True
    # Joker (seconde chance) et pré-coche : always.
    assert s.choice_joker_always is True
    assert s.choice_checked_always is True
    # Ordre aléatoire : never.
    assert s.exercise_order_never is True
    assert s.question_order_never is True
    assert s.choice_order_never is True
    # Réessai et une copie par variante.
    assert s.generate_retry is True
    assert s.generate_per_variant is True


def test_paper_format_property():
    s = model.ProjectSettings()
    assert s.paper_format == "a4"
    s.paper_a4 = False
    s.paper_a3 = True
    assert s.paper_format == "a3"
    assert s.paper_dimensions == (297.0, 420.0)


def test_variant_store_layout_variant():
    """VariantStore récupère layouts et variantes typés."""
    store = model.VariantStore()
    store["p"] = model.Layout(orientation="p", page_width=210, page_height=297)
    store["42"] = model.Variant(id=42, barcode_text="*TEST-0042*")
    layout = store.layout("p")
    assert layout is not None
    assert layout.page_width == 210
    variant = store.variant(42)
    assert variant is not None
    assert variant.id == 42
    # Round-trip plain dict (format JSON).
    plain = store.to_plain_dict()
    store2 = model.VariantStore.from_plain_dict(plain)
    assert store2.layout("p").page_height == 297
    assert store2.variant(42).barcode_text == "*TEST-0042*"
