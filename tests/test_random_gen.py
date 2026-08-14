"""Tests du générateur pseudo-aléatoire (reproductibilité vs code JS)."""

from qcm_papier import random_gen as rg


def test_pseudo_random_base_returns_false():
    """Mode BASE → toujours False (valeur de base / non-alt)."""
    assert rg.pseudo_random(42, 0, 0, rg.TriChoice.BASE) is False
    assert rg.pseudo_random(0, 5, 3, rg.TriChoice.BASE) is False


def test_pseudo_random_alt_returns_true():
    """Mode ALT → toujours True."""
    assert rg.pseudo_random(42, 0, 0, rg.TriChoice.ALT) is True
    assert rg.pseudo_random(0, 99, 7, rg.TriChoice.ALT) is True


def test_pseudo_random_random_reproductible():
    """Mode RANDOM : (seed + delta*PRIME) & (1 << bit) != 0, reproductible."""
    # seed=42, delta=0, bit=0 : (42 & 1) = 0 → False
    assert rg.pseudo_random(42, 0, 0, rg.TriChoice.RANDOM) is False
    # seed=43, delta=0, bit=0 : (43 & 1) = 1 → True
    assert rg.pseudo_random(43, 0, 0, rg.TriChoice.RANDOM) is True
    # seed=42, delta=1, bit=0 : ((42+32771) & 1) = (32813 & 1) = 1 → True
    assert rg.pseudo_random(42, 1, 0, rg.TriChoice.RANDOM) is True
    # bit=1 : (42 & 2) = 2 → True
    assert rg.pseudo_random(42, 0, 1, rg.TriChoice.RANDOM) is True


def test_pseudo_random_deterministe():
    """Deux appels identiques donnent le même résultat (pas d'aléatoire réel)."""
    r1 = rg.pseudo_random(1234, 7, 5, rg.TriChoice.RANDOM)
    r2 = rg.pseudo_random(1234, 7, 5, rg.TriChoice.RANDOM)
    assert r1 == r2


def test_tri_from_flags():
    assert rg.tri_from_flags(False, True, False) is rg.TriChoice.ALT
    assert rg.tri_from_flags(False, False, True) is rg.TriChoice.RANDOM
    assert rg.tri_from_flags(True, False, False) is rg.TriChoice.BASE
    # Aucun coché → BASE par défaut.
    assert rg.tri_from_flags(False, False, False) is rg.TriChoice.BASE


def test_random_index():
    assert rg.random_index(42, 10) == 2  # 42 % 10
    assert rg.random_index(7, 3) == 1   # 7 % 3
    assert rg.random_index(100, 0) == 0  # longueur nulle


def test_insert_choices_ajoute_neutres():
    """insert_choices ajoute des choix fantômes neutres à des positions pseudo-aléatoires."""
    choice_list = [{"index": 0, "name": "A", "correct": True, "neutral": False, "penalty": False}]
    rg.insert_choices(42, choice_list, additional=0,
                      new_choices_name="X", new_choices_count=3)
    # On doit avoir 1 + 3 = 4 choix.
    assert len(choice_list) == 4
    # Les 3 nouveaux sont neutres et index -1.
    fantomes = [c for c in choice_list if c["index"] == -1]
    assert len(fantomes) == 3
    for c in fantomes:
        assert c["neutral"] is True
        assert c["correct"] is False
        assert c["name"] == "X"


def test_insert_questions_structure():
    """insert_questions ajoute des questions fantômes avec des choix neutres."""
    question_list = [{"index": 0, "name": "Q", "choices": []}]
    rg.insert_questions(42, question_list,
                        new_questions=2, new_choices=4,
                        new_questions_name="FQ", new_choices_name="C")
    assert len(question_list) == 3
    fantomes = [q for q in question_list if q["index"] == -1]
    assert len(fantomes) == 2
    for q in fantomes:
        assert q["check"] is True
        assert len(q["choices"]) == 4
        assert q["name"] == "FQ"
