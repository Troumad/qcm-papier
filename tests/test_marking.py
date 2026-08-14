"""Tests du calcul des notes / barèmes (score_page)."""

from qcm_papier import marking, model


def _make_project_single() -> model.Project:
    """Projet : 1 exercice, 1 question choix unique, 4 choix."""
    p = model.Project()
    ex = model.Exercise(name="Ex", index=0)
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


def _marks(checked: list[bool]) -> list[dict]:
    """Construit des marks pour 4 choix (checked[i] = l'étudiant a coché le choix i)."""
    return [{"e": 0, "q": 0, "c": i, "r": 2.3, "x": i, "y": 0, "checked": c}
            for i, c in enumerate(checked)]


def test_choix_unique_bonne_reponse():
    """L'étudiant coche A (correct) → note = gain = 2, complète."""
    p = _make_project_single()
    marks = _marks([True, False, False, False])
    sc = marking.score_page(p, marks, variant_id=1, student_id="p0000001")
    assert sc.value == 2.0
    assert sc.total == 2.0
    assert sc.complete is True


def test_choix_unique_mauvaise_reponse_penalisante():
    """L'étudiant coche B (pénalité) → note = -malus = -1."""
    p = _make_project_single()
    marks = _marks([False, True, False, False])
    sc = marking.score_page(p, marks, variant_id=1, student_id="p0000001")
    assert sc.value == -1.0
    assert sc.total == 2.0


def test_choix_unique_aucune_reponse():
    """Aucune case cochée → note = 0."""
    p = _make_project_single()
    marks = _marks([False, False, False, False])
    sc = marking.score_page(p, marks, variant_id=1, student_id="p0000001")
    assert sc.value == 0.0


def test_choix_multiple_gain_progressif():
    """Question à gain progressif : 2 bonnes sur 3 cochées → gain * 2/3."""
    p = model.Project()
    ex = model.Exercise(name="Ex", index=0)
    q = model.Question(name="Q", gain=3.0, penalty=1.0, single=False,
                       multiple_progressive=True, index=0)
    q.choices = [
        model.Choice(name="A", correct=True, neutral=False, index=0),
        model.Choice(name="B", correct=True, neutral=False, index=1),
        model.Choice(name="C", correct=True, neutral=False, index=2),
        model.Choice(name="D", correct=False, neutral=False, penalty=True, index=3),
    ]
    ex.questions = [q]
    p.structure = [ex]
    # A et B cochés (2 bonnes sur 3), D non coché (pas de pénalité).
    marks = _marks([True, True, False, False])
    sc = marking.score_page(p, marks, variant_id=1, student_id="p1")
    assert sc.value == 2.0  # 3 * 2/3
    assert sc.total == 3.0


def test_choix_multiple_correspondance_exacte():
    """Question à correspondance exacte : il faut TOUTES les bonnes cases."""
    p = model.Project()
    ex = model.Exercise(name="Ex", index=0)
    q = model.Question(name="Q", gain=4.0, penalty=1.0, single=False,
                       multiple_exact=True, index=0)
    q.choices = [
        model.Choice(name="A", correct=True, neutral=False, index=0),
        model.Choice(name="B", correct=True, neutral=False, index=1),
        model.Choice(name="C", correct=False, neutral=False, penalty=True, index=2),
    ]
    ex.questions = [q]
    p.structure = [ex]
    # Seulement A coché (1 sur 2) → pas de gain.
    sc = marking.score_page(p, _marks([True, False, False]),
                            variant_id=1, student_id="p1")
    assert sc.value == 0.0
    # A et B cochés (2 sur 2) → gain.
    sc = marking.score_page(p, _marks([True, True, False]),
                            variant_id=1, student_id="p1")
    assert sc.value == 4.0


def test_exercice_validation_seuil():
    """Exercice avec validation : si somme >= seuil, on prend le gain ; sinon 0."""
    p = model.Project()
    ex = model.Exercise(name="Ex", index=0, validation=True,
                        threshold=2.0, gain=10.0)
    q = model.Question(name="Q", gain=1.0, penalty=0.5, single=True, index=0)
    q.choices = [model.Choice(name="A", correct=True, neutral=False, index=0),
                 model.Choice(name="B", correct=False, neutral=False, penalty=True, index=1)]
    ex.questions = [q]
    p.structure = [ex]
    # A coché → question = 1, somme = 1 < seuil 2 → exercice = 0.
    sc = marking.score_page(p, _marks([True, False]), variant_id=1, student_id="p1")
    assert sc.value == 0.0
    assert sc.total == 10.0


def test_question_manuelle():
    """Question à correction manuelle : la note vient de la mark manuelle."""
    p = model.Project()
    ex = model.Exercise(name="Ex", index=0)
    q = model.Question(name="Q", gain=5.0, manual=True, index=0)
    ex.questions = [q]
    p.structure = [ex]
    marks = [{"e": 0, "q": 0, "value": 3.5, "total": 5.0}]
    sc = marking.score_page(p, marks, variant_id=1, student_id="p1")
    assert sc.value == 3.5
    assert sc.total == 5.0


def test_copie_incomplete_si_mark_manquante():
    """Si une case n'est pas lue (mark absente), la copie est incomplète."""
    p = _make_project_single()
    # Seulement 3 marks sur 4.
    marks = _marks([True, False, False])[:3]
    sc = marking.score_page(p, marks, variant_id=1, student_id="p1")
    assert sc.complete is False


def test_copie_incomplete_sans_variant_ou_etudiant():
    """Sans variante ni étudiant → incomplète."""
    p = _make_project_single()
    sc = marking.score_page(p, _marks([True, False, False, False]))
    assert sc.complete is False


def test_scale_note():
    """Ramène une note value/total à l'échelle /note_max.

    Formule : value * note_max / notemax (cf. export Scodoc du JS).
    """
    # 10/20 avec notemax=20 → 10*20/20 = 10.
    assert marking.scale_note(10.0, 20.0, 20.0, 20.0) == 10.0
    # 5/20 avec notemax=20 → 5*20/20 = 5.
    assert marking.scale_note(5.0, 20.0, 20.0, 20.0) == 5.0
    # Total nul → 0.
    assert marking.scale_note(10.0, 0.0, 20.0) == 0.0
    # note /20 ramenée à /20 : identique.
    assert marking.scale_note(15.0, 20.0, 20.0, 20.0) == 15.0
