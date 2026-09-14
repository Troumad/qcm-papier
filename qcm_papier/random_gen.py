"""Génération pseudo-aléatoire reproductible et insertion d'éléments fantômes.

Reproduit fidèlement l'algorithme du code JavaScript original
(``pseudoRandom``, ``insertChoices``, ``insertQuestions``, ``insertExercises``,
index.html lignes ~6046-6188) afin que les variantes générées soient
**strictement identiques** à celles du code original pour un même id de
variante et un même jeu de paramètres.

Principe : un générateur déterministe basé sur un « seed » entier (id de
variante) auquel on ajoute le nombre premier 32771 (premier > 2^15) à chaque
itération. Les décisions binaires (sens de lecture, ajout fantôme, ordre
aléatoire) se font en testant un bit du seed.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

# Nombre premier supérieur à 2^15 = 32768, utilisé dans le code original.
PRIME = 32771


class TriChoice(str, Enum):
    """Choix parmi 3 boutons mutuellement exclusifs.

    Modélise les triplets de boutons ``button_base`` / ``button_alt`` /
    ``button_random`` du code original (un seul coché à la fois).

    * ``BASE``   : renvoie toujours False (valeur de base / non-alt)
    * ``ALT``    : renvoie toujours True  (valeur alternative)
    * ``RANDOM`` : décision pseudo-aléatoire (bit du seed)
    """

    BASE = "base"
    ALT = "alt"
    RANDOM = "random"


def tri_from_flags(base: bool, alt: bool, random_flag: bool) -> TriChoice:
    """Construit un TriChoice à partir de 3 booléens (au plus un True).

    Si aucun n'est True, on retombe sur BASE (comportement par défaut du code
    original : le bouton base est coché par défaut).
    """
    if alt:
        return TriChoice.ALT
    if random_flag:
        return TriChoice.RANDOM
    return TriChoice.BASE


def pseudo_random(seed: int, delta: int, bit: int,
                  choice: TriChoice) -> bool:
    """Décision binaire reproductible (renvoie True si « alt »).

    Reproduit ``pseudoRandom(seed, delta, bit, button_base, button_alt,
    button_random)`` du code original.

    * ``choice == ALT``    → True
    * ``choice == BASE``   → False
    * ``choice == RANDOM`` → ``(seed + delta*PRIME) & (1 << bit) != 0``
    """
    if choice is TriChoice.ALT:
        return True
    if choice is TriChoice.BASE:
        return False
    # mode random : on ajoute delta fois PRIME au seed, puis on teste un bit.
    s = seed
    d = delta
    while d > 0:
        s += PRIME
        d -= 1
    return (s & (1 << bit)) != 0


# ---------------------------------------------------------------------------
# Insertion d'éléments « fantômes »
# ---------------------------------------------------------------------------

def insert_choices(variant_id: int, choice_list: list,
                   additional: int = 0,
                   new_choices_name: str = "X",
                   new_choices_count: int = 1) -> None:
    """Insère ``new_choices_count + additional`` choix fantômes neutres.

    Reproduit ``insertChoices(variant_id, choice_list, additional)``
    (index.html ~6065). Les choix sont insérés à des positions pseudo-aléatoires
    et sont marqués ``index=-1`` (fantôme), ``neutral=True``.
    """
    seed = variant_id
    nb = len(choice_list)
    for _ in range(nb):
        seed += PRIME
    for _ in range(int(new_choices_count) + additional):
        choice_index = seed % len(choice_list) if choice_list else 0
        seed += PRIME
        choice_list.insert(choice_index, {
            "index": -1,
            "name": new_choices_name,
            "correct": False,
            "neutral": True,
            "penalty": False,
        })


def insert_questions(variant_id: int, question_list: list,
                     new_questions: int = 1,
                     new_choices: int = 4,
                     new_questions_name: str = "Question",
                     new_choices_name: str = "X") -> None:
    """Insère ``new_questions`` questions fantômes.

    Reproduit ``insertQuestions(variant_id, question_list)`` (index.html ~6087).
    Chaque question fantôme contient ``new_choices`` choix neutres.
    """
    seed = variant_id
    for _ in range(len(question_list)):
        seed += PRIME
    for _ in range(int(new_questions)):
        question_index = seed % len(question_list) if question_list else 0
        seed += PRIME
        question = {
            "index": -1,
            "name": new_questions_name,
            "gain": 0,
            "penalty": 0,
            "check": True,
            "single": True,
            "multiple_exact": False,
            "multiple_progressive": False,
            "manual": False,
            "width": 0,
            "height": 0,
            "choices": [],
        }
        for _ in range(int(new_choices)):
            question["choices"].append({
                "index": 0,
                "name": new_choices_name,
                "correct": False,
                "neutral": True,
                "penalty": False,
            })
        question_list.insert(question_index, question)


def insert_exercises(variant_id: int, exercise_list: list,
                     new_exercises: int = 1,
                     new_questions: int = 1,
                     new_choices: int = 4,
                     new_exercises_name: str = "Exercice",
                     new_questions_name: str = "Question",
                     new_choices_name: str = "X") -> None:
    """Insère ``new_exercises`` exercices fantômes.

    Reproduit ``insertExercises(variant_id, exercise_list)`` (index.html ~6126).
    """
    seed = variant_id
    for _ in range(len(exercise_list)):
        seed += PRIME
    for _ in range(int(new_exercises)):
        exercise_index = seed % len(exercise_list) if exercise_list else 0
        exercise = {
            "index": -1,
            "name": new_exercises_name,
            "header": "",
            "sum": True,
            "sum_bias": False,
            "validation": False,
            "bias": 0,
            "threshold": 0,
            "gain": 0,
            "min0": False,
            "nomin": True,
            "noscale": True,
            "scale": False,
            "max": 0,
            "questions": [],
        }
        seed += PRIME
        for _ in range(int(new_questions)):
            question = {
                "index": 0,
                "name": new_questions_name,
                "gain": 0,
                "penalty": 0,
                "check": True,
                "single": True,
                "multiple_exact": False,
                "multiple_progressive": False,
                "manual": False,
                "width": 0,
                "height": 0,
                "choices": [],
            }
            for _ in range(int(new_choices)):
                question["choices"].append({
                    "index": 0,
                    "name": new_choices_name,
                    "correct": False,
                    "neutral": True,
                    "penalty": False,
                })
            exercise["questions"].append(question)
        exercise_list.insert(exercise_index, exercise)


# ---------------------------------------------------------------------------
# Choix d'index pseudo-aléatoire pour l'ordre
# ---------------------------------------------------------------------------

def random_index(seed: int, length: int) -> int:
    """Renvoie ``seed % length`` (sélection d'index pour l'ordre aléatoire).

    Reproduit ``variant_id % exercise_list.length`` du code original.
    """
    if length <= 0:
        return 0
    return seed % length
