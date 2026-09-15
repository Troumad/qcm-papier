"""Règles d'édition partagées (mêmes règles que l'éditeur GTK)."""

import pytest

from qcm_papier import editing
from qcm_papier.model import Project, ProjectSettings


def _states(question):
    return [editing.choice_state(c) for c in question.choices]


def test_add_exercise_cree_une_question_et_8_choix():
    project = Project()
    exercise = editing.add_exercise(project)
    assert exercise.name == "Exercice 1"
    question = exercise.questions[0]
    assert [c.name for c in question.choices] == list("ABCDEFGH")
    assert _states(question)[:3] == ["correct", "penalty", "neutral"]
    assert editing.add_question(exercise).name == "Question 2"


def test_choix_unique_ne_retire_pas_le_dernier_correct():
    question = editing.add_exercise(Project()).questions[0]
    assert editing.set_choice_state(question, 0, "neutral") is False
    assert _states(question)[0] == "correct"


def test_choix_unique_un_seul_correct():
    question = editing.add_exercise(Project()).questions[0]
    assert editing.set_choice_state(question, 2, "correct") is True
    assert _states(question)[:3] == ["neutral", "penalty", "correct"]


def test_choix_multiples_plusieurs_corrects_puis_retour_unique():
    question = editing.add_exercise(Project()).questions[0]
    editing.set_question_type(question, "multiple_exact")
    editing.set_choice_state(question, 2, "correct")
    assert _states(question).count("correct") == 2
    editing.set_question_type(question, "single")
    assert _states(question).count("correct") == 1


def test_add_et_remove_choice():
    question = editing.add_exercise(Project()).questions[0]
    assert editing.add_choice(question).name == "I"
    while len(question.choices) > 1:
        assert editing.remove_choice(question)
    assert editing.remove_choice(question) is False
    assert _states(question) == ["correct"]


def test_update_refuse_un_champ_inconnu():
    exercise = editing.add_exercise(Project())
    editing.update_exercise(exercise, {"name": "Dérivées", "gain": "2.5", "min0": True})
    assert (exercise.name, exercise.gain, exercise.min0) == ("Dérivées", 2.5, True)
    with pytest.raises(ValueError):
        editing.update_exercise(exercise, {"questions": []})


def test_structure_view_intervalles():
    project = Project()
    editing.add_exercise(project)
    view = editing.structure_view(project)
    assert view["range"] == [-0.5, 1.0]
    assert view["exercises"][0]["questions"][0]["type"] == "single"


def test_settings_form_aller_retour():
    settings = ProjectSettings()
    form = editing.settings_form(settings)
    assert form["exercise_dir"] == "both"
    assert form["exercise_order"] == "never"
    form.update(
        {"exercise_dir": "top", "choice_checked": "sometimes", "paper_format": "a3", "paper_orientation": "landscape"}
    )
    editing.apply_settings_form(settings, form)
    assert settings.exercise_dir_top and not settings.exercise_dir_both
    assert settings.choice_checked_sometimes and not settings.choice_checked_always
    assert settings.paper_a3 and not settings.paper_a4
    assert settings.paper_landscape and not settings.paper_portrait
    assert editing.settings_form(settings) == form


def test_settings_form_refuse_une_valeur_invalide():
    with pytest.raises(ValueError):
        editing.apply_settings_form(ProjectSettings(), {"exercise_dir": "diagonale"})


def test_apply_info_defaults_ne_remplace_que_les_vides():
    settings = ProjectSettings(establishment="Lyon 2")
    editing.apply_info_defaults(settings)
    assert settings.establishment == "Lyon 2"
    assert settings.duration == "1h"
