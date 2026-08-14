"""Calcul des notes / barèmes.

Reproduit la méthode ``Page.scoreMarks()`` du code JavaScript original
(index.html lignes ~3378-3580) :

* Pour chaque question à correction manuelle : la note vient de la mark
  manuelle (``value``).
* Pour chaque question à choix : on compte les cases cochées correctes/neutres/
  pénalisantes (cases normales et « joker » séparément), puis on applique la
  règle (choix unique / correspondance exacte / gain progressif).
* Pour chaque exercice : somme des questions, biais négatif, ou validation par
  seuil ; remise à l'échelle éventuelle ; plancher à 0 si demandé.
* La note globale est la somme des exercices.

La structure des ``marks`` d'une page suit le format du code original :
``{e, q, c, r, x, y, checked, joker, value, total, ...}``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model import Exercise, Project, Question


# ---------------------------------------------------------------------------
# Recherche d'une mark
# ---------------------------------------------------------------------------

def find_mark(marks: list[dict], e: int,
              q: int | None = None, c: int | None = None,
              joker: bool = False) -> dict | None:
    """Cherche une mark correspondant à (exercice, question, choix, joker).

    Reprend ``find_mark(e, q, c, joker)`` (index.html ~3381-3415). Les marks
    « joker » sont identifiées par ``j=True`` ; les marks normales ont
    ``j`` absent (None).
    """
    for mark in marks:
        if mark.get("e") != e:
            continue
        if q is not None and mark.get("q") != q:
            continue
        if c is not None and mark.get("c") != c:
            continue
        if joker and mark.get("j"):
            return mark
        if not joker and mark.get("j") is None and c is not None and mark.get("r") is not None:
            # mark de choix (a un rayon r)
            if mark.get("c") == c:
                return mark
        if not joker and mark.get("j") is None and c is None:
            # mark de question (pas de rayon r) ou d'exercice.
            if mark.get("r") is None and mark.get("w") is None and mark.get("q") is not None:
                return mark
            if mark.get("q") is None:
                return mark
    return None


def find_choice_mark(marks: list[dict], e: int, q: int, c: int,
                     joker: bool = False) -> dict | None:
    """Cherche la mark d'un choix (cases à cocher).

    Une mark de choix a un rayon ``r`` (et non une largeur ``w``). Les jokers
    ont ``j=True``.
    """
    for mark in marks:
        if (mark.get("e") == e and mark.get("q") == q
                and mark.get("c") == c and mark.get("r") is not None):
            if joker and mark.get("j"):
                return mark
            if not joker and mark.get("j") is None:
                return mark
    return None


def find_question_mark(marks: list[dict], e: int, q: int) -> dict | None:
    """Cherche la mark de score d'une question (manual ou synthèse)."""
    for mark in marks:
        if (mark.get("e") == e and mark.get("q") == q
                and mark.get("r") is None and mark.get("c") is None):
            return mark
    return None


def find_exercise_mark(marks: list[dict], e: int) -> dict | None:
    """Cherche la mark de score d'un exercice."""
    for mark in marks:
        if mark.get("e") == e and mark.get("q") is None and mark.get("c") is None:
            return mark
    return None


# ---------------------------------------------------------------------------
# Calcul du barème d'une question
# ---------------------------------------------------------------------------

def _question_score(question: Question, marks: list[dict],
                    e: int, q: int) -> tuple[float, float, bool]:
    """Calcule (value, total, ok) d'une question.

    ``ok`` indique si toutes les cases nécessaires ont été lues (False si une
    mark est absente → copie incomplète).
    """
    if question.manual:
        total = float(question.gain)
        mark = find_question_mark(marks, e, q)
        if mark is None or mark.get("value") is None:
            return 0.0, total, False
        return float(mark["value"]), total, True

    if not question.check:
        return 0.0, 0.0, True

    # Comptage des cases.
    q_correct = 0
    q_neutral = 0
    q_penalty = 0
    box_correct = 0
    box_neutral = 0
    box_penalty = 0
    joker_correct = 0
    joker_neutral = 0
    joker_penalty = 0
    ok = True

    for k, choice in enumerate(question.choices):
        if choice.correct:
            q_correct += 1
        if choice.neutral:
            q_neutral += 1
        if choice.penalty:
            q_penalty += 1

        box = find_choice_mark(marks, e, q, k, joker=False)
        if box is None:
            ok = False
        elif box.get("checked"):
            if choice.correct:
                box_correct += 1
            if choice.neutral:
                box_neutral += 1
            if choice.penalty:
                box_penalty += 1

        joker = find_choice_mark(marks, e, q, k, joker=True)
        if joker is not None and joker.get("checked"):
            if choice.correct:
                joker_correct += 1
            if choice.neutral:
                joker_neutral += 1
            if choice.penalty:
                joker_penalty += 1

    value = 0.0
    if joker_correct == 0 and joker_neutral == 0 and joker_penalty == 0:
        # Cases normales.
        if box_penalty > 0:
            value = -float(question.penalty)
        elif question.single and box_correct > 0:
            value = float(question.gain)
        elif question.multiple_exact and box_correct == q_correct:
            value = float(question.gain)
        elif question.multiple_progressive and box_correct > 0:
            value = float(question.gain) * (box_correct / q_correct) if q_correct else 0.0
    else:
        # Cases joker (seconde chance).
        if joker_penalty > 0:
            value = -float(question.penalty)
        elif question.single and joker_correct > 0:
            value = float(question.gain)
        elif question.multiple_exact and joker_correct == q_correct:
            value = float(question.gain)
        elif question.multiple_progressive and joker_correct > 0:
            value = float(question.gain) * (joker_correct / q_correct) if q_correct else 0.0

    total = float(question.gain) if q_correct > 0 else 0.0

    # Enregistre la mark de question.
    qmark = find_question_mark(marks, e, q)
    if qmark is None:
        marks.append({"e": e, "q": q, "value": value, "total": total})
    else:
        qmark["value"] = value
        qmark["total"] = total

    return value, total, ok


def _exercise_score(exercise: Exercise, marks: list[dict],
                    e: int) -> tuple[float, float, bool]:
    """Calcule (value, total, ok) d'un exercice.

    Reprend la logique ``if(exercise.validation) ... else if(exercise.sum_bias)
    ... if(exercise.scale) ... if(exercise.min0 ...)`` (index.html ~3536-3575).
    """
    value = 0.0
    total = 0.0
    ok = True
    for j, question in enumerate(exercise.questions):
        qv, qt, qok = _question_score(question, marks, e, j)
        value += qv
        total += qt
        if not qok:
            ok = False

    if exercise.validation:
        total = float(exercise.gain)
        if value >= float(exercise.threshold):
            value = total
        else:
            value = 0.0
    elif exercise.sum_bias:
        bias = float(exercise.bias)
        value -= bias
        total -= bias

    if exercise.scale:
        max_v = float(exercise.max)
        if total != 0:
            value *= max_v / total
        total = max_v

    if exercise.min0 and value < 0:
        value = 0.0

    emark = find_exercise_mark(marks, e)
    if emark is None:
        marks.append({"e": e, "value": value, "total": total})
    else:
        emark["value"] = value
        emark["total"] = total

    return value, total, ok


# ---------------------------------------------------------------------------
# Calcul de la note d'une page
# ---------------------------------------------------------------------------

@dataclass
class PageScore:
    """Résultat du scoring d'une page (une copie)."""

    value: float = 0.0
    total: float = 0.0
    complete: bool = False
    marks: list[dict] = field(default_factory=list)


def score_page(project: Project, marks: list[dict],
               variant_id: int | None = None,
               student_id: str | None = None,
               check_manual_active: bool = False) -> PageScore:
    """Calcule la note d'une page à partir de ses marks.

    Reprend ``Page.scoreMarks()`` (index.html ~3378-3580). ``marks`` est la
    liste des marks détectées (cases cochées + marks manuelles).

    Renvoie un ``PageScore`` avec la note, le total, et le statut « complète ».
    """
    value = 0.0
    total = 0.0
    complete = True
    if variant_id is None:
        complete = False
    if student_id is None:
        complete = False
    if check_manual_active:
        complete = False

    for i, exercise in enumerate(project.structure):
        ev, et, eok = _exercise_score(exercise, marks, i)
        value += ev
        total += et
        if not eok:
            complete = False

    return PageScore(value=value, total=total, complete=complete, marks=marks)


# ---------------------------------------------------------------------------
# Note finale ramenée à un maximum (Scodoc /20 par défaut)
# ---------------------------------------------------------------------------

def scale_note(value: float, total: float, note_max: float = 20.0,
               notemax: float = 20.0) -> float:
    """Ramène une note ``value/total`` à l'échelle ``/note_max``.

    Reprend ``Number.parseFloat(value*20/NOTEMAX)`` de l'export Scodoc
    (index.html ~7692).
    """
    if total == 0:
        return 0.0
    return value * note_max / notemax
