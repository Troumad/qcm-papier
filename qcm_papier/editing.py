"""Règles d'édition du projet, indépendantes de l'interface.

Reprend le comportement de l'interface GTK (``ui/editor.py`` et les onglets
Informations / Génération de ``ui/app.py``) pour que l'interface web applique
exactement les mêmes règles : choix par défaut, mode « choix unique »,
paramètres à trois états stockés sous forme de booléens, etc.
"""

from __future__ import annotations

from typing import Any

from . import generator
from .model import Choice, Exercise, Project, ProjectSettings, Question

# ---------------------------------------------------------------------------
# Structure : exercices, questions, choix
# ---------------------------------------------------------------------------

CHOICE_STATES = ("correct", "neutral", "penalty")
QUESTION_TYPES = ("single", "multiple_exact", "multiple_progressive", "manual")


def _default_choices() -> list[Choice]:
    """8 choix A à H : A correct, B pénalisant, les autres neutres."""
    choices = [
        Choice(name="A", correct=True, neutral=False, index=0),
        Choice(name="B", correct=False, neutral=False, penalty=True, index=1),
    ]
    for i, name in enumerate("CDEFGH", start=2):
        choices.append(Choice(name=name, correct=False, neutral=True, index=i))
    return choices


def normalize_single_choices(question: Question) -> None:
    """En mode choix unique, garantit exactement un choix correct."""
    if not (question.single and question.choices):
        return
    correct = [c for c in question.choices if c.correct]
    if not correct:
        first = question.choices[0]
        first.correct, first.neutral, first.penalty = True, False, False
    for c in correct[1:]:
        c.correct, c.neutral, c.penalty = False, True, False


def add_exercise(project: Project) -> Exercise:
    n = len(project.structure)
    exercise = Exercise(name=f"Exercice {n + 1}", index=n)
    exercise.questions = [Question(name="Question 1", gain=1.0, penalty=0.5, single=True, index=0)]
    exercise.questions[0].choices = _default_choices()
    project.structure.append(exercise)
    return exercise


def add_question(exercise: Exercise) -> Question:
    n = len(exercise.questions)
    question = Question(name=f"Question {n + 1}", gain=1.0, penalty=0.5, single=True, index=n)
    question.choices = _default_choices()
    exercise.questions.append(question)
    return question


def add_choice(question: Question) -> Choice:
    n = len(question.choices)
    choice = Choice(name=chr(ord("A") + n), correct=False, neutral=True, index=n)
    question.choices.append(choice)
    if question.single and n == 0:
        choice.correct, choice.neutral, choice.penalty = True, False, False
    normalize_single_choices(question)
    return choice


def remove_choice(question: Question) -> bool:
    """Supprime le dernier choix s'il en reste au moins deux."""
    if len(question.choices) <= 1:
        return False
    question.choices.pop()
    normalize_single_choices(question)
    return True


def remove_exercise(project: Project, index: int) -> bool:
    """Supprime un exercice. Renvoie False s'il est le dernier du projet.

    Comme dans l'éditeur GTK, un projet garde toujours au moins un exercice.
    """
    _check_index(project.structure, index)
    if len(project.structure) <= 1:
        return False
    del project.structure[index]
    _reindex(project.structure)
    return True


def remove_question(exercise: Exercise, index: int) -> bool:
    """Supprime une question. Renvoie False si elle est la dernière de l'exercice."""
    _check_index(exercise.questions, index)
    if len(exercise.questions) <= 1:
        return False
    del exercise.questions[index]
    _reindex(exercise.questions)
    return True


def move_exercise(project: Project, index: int, delta: int) -> bool:
    """Déplace un exercice d'un cran (−1 = monter, +1 = descendre).

    Renvoie False quand le déplacement sortirait de la liste.
    """
    return _move(project.structure, index, delta)


def move_question(exercise: Exercise, index: int, delta: int) -> bool:
    """Déplace une question d'un cran dans son exercice."""
    return _move(exercise.questions, index, delta)


def _check_index(items: list[Any], index: int) -> None:
    """Refuse un rang hors de la liste, y compris négatif (IndexError : 404 côté web)."""
    if not 0 <= index < len(items):
        raise IndexError(f"Rang hors de la liste : {index}")


def _reindex(items: list[Any]) -> None:
    for i, item in enumerate(items):
        item.index = i


def _move(items: list[Any], index: int, delta: int) -> bool:
    if delta not in (-1, 1):
        raise ValueError(f"Déplacement d'un seul cran attendu : {delta}")
    _check_index(items, index)
    target = index + delta
    if not 0 <= target < len(items):
        return False
    items[index], items[target] = items[target], items[index]
    _reindex(items)
    return True


def set_choice_state(question: Question, choice_index: int, state: str) -> bool:
    """Change l'état d'un choix. Renvoie False si le changement est refusé.

    En choix unique, on ne peut pas retirer le dernier choix correct, et rendre
    un choix correct rend les autres neutres.
    """
    if state not in CHOICE_STATES:
        raise ValueError(f"État de choix inconnu : {state}")
    choice = question.choices[choice_index]
    if question.single and state != "correct":
        correct = [c for c in question.choices if c.correct]
        if len(correct) == 1 and correct[0] is choice:
            return False
    if question.single and state == "correct":
        for c in question.choices:
            if c is not choice and c.correct:
                c.correct, c.neutral, c.penalty = False, True, False
    choice.correct = state == "correct"
    choice.neutral = state == "neutral"
    choice.penalty = state == "penalty"
    normalize_single_choices(question)
    return True


def choice_state(choice: Choice) -> str:
    if choice.correct:
        return "correct"
    if choice.penalty and not choice.neutral:
        return "penalty"
    return "neutral"


def question_type(question: Question) -> str:
    if question.manual:
        return "manual"
    if question.single:
        return "single"
    if question.multiple_exact:
        return "multiple_exact"
    return "multiple_progressive"


def set_question_type(question: Question, kind: str) -> None:
    if kind not in QUESTION_TYPES:
        raise ValueError(f"Type de question inconnu : {kind}")
    question.single = kind == "single"
    question.multiple_exact = kind == "multiple_exact"
    question.multiple_progressive = kind == "multiple_progressive"
    question.manual = kind == "manual"
    normalize_single_choices(question)


EXERCISE_FIELDS = {"name": str, "header": str, "validation": bool, "gain": float, "threshold": float, "min0": bool}
QUESTION_FIELDS = {"name": str, "gain": float, "penalty": float}


def _update(obj: Any, fields: dict[str, type], data: dict[str, Any]) -> None:
    for key, value in data.items():
        if key not in fields:
            raise ValueError(f"Champ non modifiable : {key}")
        setattr(obj, key, fields[key](value))


def update_exercise(exercise: Exercise, data: dict[str, Any]) -> None:
    _update(exercise, EXERCISE_FIELDS, data)


def update_question(question: Question, data: dict[str, Any]) -> None:
    data = dict(data)
    kind = data.pop("type", None)
    _update(question, QUESTION_FIELDS, data)
    if kind is not None:
        set_question_type(question, kind)


def structure_view(project: Project) -> dict[str, Any]:
    """Structure avec intervalles de notes, pour l'affichage."""
    global_min, global_max = project.get_mark_range()
    exercises = []
    for exercise in project.structure:
        ex_min, ex_max = exercise.get_mark_range()
        questions = []
        for question in exercise.questions:
            q_min, q_max = question.get_mark_range()
            questions.append(
                {
                    "name": question.name,
                    "gain": question.gain,
                    "penalty": question.penalty,
                    "type": question_type(question),
                    "range": [q_min, q_max],
                    "choices": [{"name": c.name, "state": choice_state(c)} for c in question.choices],
                }
            )
        exercises.append(
            {
                "name": exercise.name,
                "header": exercise.header,
                "validation": exercise.validation,
                "gain": exercise.gain,
                "threshold": exercise.threshold,
                "min0": exercise.min0,
                "range": [ex_min, ex_max],
                "questions": questions,
            }
        )
    return {"range": [global_min, global_max], "exercises": exercises}


# ---------------------------------------------------------------------------
# Paramètres : informations et génération
# ---------------------------------------------------------------------------

INFO_FIELDS = (
    "establishment", "institute", "formation", "year", "semester", "teaching_unit",
    "module_full", "module_short", "evaluation_full", "evaluation_short",
    "teachers", "date", "duration",
)  # fmt: skip

# Valeurs proposées par l'interface GTK quand un champ est vide.
INFO_DEFAULTS = {
    "establishment": "Université Lyon 1",
    "institute": "IUT LYON 1",
    "formation": "Département GEii",
    "year": "2026",
    "semester": "S1",
    "teaching_unit": "UE3",
    "module_full": "Mathématiques",
    "module_short": "OML1",
    "evaluation_full": "QCM Mathématiques",
    "evaluation_short": "OML1",
    "teachers": "BS",
    "date": "09/10/2026",
    "duration": "1h",
}

# Groupes « sens de lecture » : left / top / both (aléatoire).
DIR_GROUPS = ("identification_dir", "exercise_dir", "question_dir", "choice_dir")
DIR_VALUES = ("left", "top", "both")

# Groupes à trois états : never / always / sometimes.
TRI_GROUPS = (
    "exercise_new", "question_new", "choice_new", "choice_checked",
    "exercise_order", "question_order", "choice_order",
)  # fmt: skip
TRI_VALUES = ("never", "always", "sometimes")

GENERATION_FIELDS = {
    "exercise_new_exercises": int,
    "exercise_new_exercises_name": str,
    "exercise_new_questions": int,
    "exercise_new_questions_name": str,
    "exercise_new_choices": int,
    "exercise_new_choices_name": str,
    "question_new_questions": int,
    "question_new_questions_name": str,
    "question_new_choices": int,
    "question_new_choices_name": str,
    "choice_new_choices": int,
    "choice_new_choices_name": str,
    "choice_joker_always": bool,
    "generate_students": int,
    "generate_count": int,
    "generate_variants": str,
}

MARGINS = ("margin_top", "margin_left", "margin_right", "margin_bottom")

# En-tête et pied de page : textes avec macros ``${...}`` (onglet GTK « Entête et pied de page »).
HEADER_FOOTER_DEFAULTS = {
    "header_left": generator.HEADER_LEFT_DEFAULT,
    "header_middle": generator.HEADER_MIDDLE_DEFAULT,
    "header_right": generator.HEADER_RIGHT_DEFAULT,
    "footer_left": generator.FOOTER_LEFT_DEFAULT,
    "footer_middle": generator.FOOTER_MIDDLE_DEFAULT,
    "footer_right": generator.FOOTER_RIGHT_DEFAULT,
}


def apply_info_defaults(settings: ProjectSettings) -> None:
    """Remplit les informations vides avec les valeurs proposées (comme GTK à l'ouverture)."""
    for key, default in INFO_DEFAULTS.items():
        if not getattr(settings, key):
            setattr(settings, key, default)


def _dir_value(settings: ProjectSettings, group: str) -> str:
    if getattr(settings, f"{group}_both"):
        return "both"
    if getattr(settings, f"{group}_top"):
        return "top"
    return "left"


def _tri_value(settings: ProjectSettings, group: str) -> str:
    if getattr(settings, f"{group}_sometimes"):
        return "sometimes"
    if getattr(settings, f"{group}_always"):
        return "always"
    return "never"


def settings_form(settings: ProjectSettings) -> dict[str, Any]:
    """Paramètres sous forme de formulaire (un choix par groupe de booléens)."""
    form: dict[str, Any] = {key: getattr(settings, key) for key in INFO_FIELDS}
    form.update({key: getattr(settings, key) for key in GENERATION_FIELDS})
    form.update({key: float(getattr(settings, key) or 10) for key in MARGINS})
    form.update({key: getattr(settings, key) for key in HEADER_FOOTER_DEFAULTS})
    form["footer_enabled"] = bool(settings.footer_enabled)
    form["paper_format"] = settings.paper_format
    if settings.paper_both:
        form["paper_orientation"] = "both"
    elif settings.paper_landscape:
        form["paper_orientation"] = "landscape"
    else:
        form["paper_orientation"] = "portrait"
    for group in DIR_GROUPS:
        form[group] = _dir_value(settings, group)
    for group in TRI_GROUPS:
        form[group] = _tri_value(settings, group)
    return form


def apply_settings_form(settings: ProjectSettings, form: dict[str, Any]) -> None:
    """Applique un formulaire (partiel) sur les paramètres."""
    for key, value in form.items():
        if key in INFO_FIELDS:
            setattr(settings, key, str(value))
        elif key in GENERATION_FIELDS:
            setattr(settings, key, GENERATION_FIELDS[key](value))
        elif key in MARGINS:
            setattr(settings, key, float(value))
        elif key in HEADER_FOOTER_DEFAULTS:
            setattr(settings, key, str(value))
        elif key == "footer_enabled":
            settings.footer_enabled = bool(value)
        elif key == "paper_format":
            if value not in ("a3", "a4", "a5"):
                raise ValueError(f"Format de papier inconnu : {value}")
            for fmt in ("a3", "a4", "a5"):
                setattr(settings, f"paper_{fmt}", fmt == value)
        elif key == "paper_orientation":
            if value not in ("portrait", "landscape", "both"):
                raise ValueError(f"Orientation inconnue : {value}")
            for orientation in ("portrait", "landscape", "both"):
                setattr(settings, f"paper_{orientation}", orientation == value)
        elif key in DIR_GROUPS:
            if value not in DIR_VALUES:
                raise ValueError(f"Sens de lecture inconnu : {value}")
            for v in DIR_VALUES:
                setattr(settings, f"{key}_{v}", v == value)
        elif key in TRI_GROUPS:
            if value not in TRI_VALUES:
                raise ValueError(f"Valeur inconnue pour {key} : {value}")
            for v in TRI_VALUES:
                setattr(settings, f"{key}_{v}", v == value)
        else:
            raise ValueError(f"Paramètre inconnu : {key}")


def header_footer_view(settings: ProjectSettings) -> dict[str, Any]:
    """Modèles par défaut et macros disponibles, avec la valeur que chacune prendra."""
    macros = [
        {"macro": macro, "value": str(getattr(settings, field) or "") or INFO_DEFAULTS.get(field, "")}
        for macro, field in generator._HEADER_MACROS.items()
    ]
    return {"defaults": HEADER_FOOTER_DEFAULTS, "macros": macros}
