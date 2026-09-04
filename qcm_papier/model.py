"""Modèle de données du QCM papier.

Reproduit fidèlement la structure JavaScript du code original (variables
``structure``, ``variants`` et paramètres de l'éditeur) afin de rester
compatible avec le format de projet JSON.

Schéma (extrait des commentaires du code original, index.html lignes ~2108-2138) :

* ``structure`` = liste d'exercices
* exercice = objet avec ``validation``, ``threshold``, ``gain``, ``sum_bias``,
  ``bias``, ``scale``, ``max``, ``min0``, ``questions``
* question = objet avec ``gain``, ``penalty``, ``manual``, ``width``, ``height``,
  ``check``, ``single``, ``multiple_progressive``, ``multiple_exact``,
  ``choices`` ; et les champs ``dessin`` / ``dessin_nom`` pour la correction
  manuelle avec image
* choice = objet avec ``name``, ``correct``, ``neutral``, ``penalty``
* ``variants`` = dict indexé par id de variante (et ``'p'``/``'l'`` pour les
  layout portrait/paysage) contenant layout, code-barres, textes, rects,
  circles, marks
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Choix
# ---------------------------------------------------------------------------

@dataclass
class Choice:
    """Un choix (case à cocher) d'une question."""

    name: str = ""
    correct: bool = False
    neutral: bool = True
    penalty: bool = False
    index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "correct": self.correct,
            "neutral": self.neutral,
            "penalty": self.penalty,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ProjectSettings":
        """Charge les paramètres depuis un dictionnaire.
        Gère les clés avec ou sans préfixe 'pos_'."""
        final_dict = {}
        for key, value in d.items():
            # Supprimer le préfixe 'pos_' si présent
            clean_key = key[4:] if key.startswith("pos_") else key
            final_dict[clean_key] = value
        return cls(**final_dict)

# ---------------------------------------------------------------------------
# Question
# ---------------------------------------------------------------------------

@dataclass
class Question:
    """Une question d'un exercice."""

    name: str = ""
    gain: float = 1.0
    penalty: float = 1.0
    manual: bool = False
    width: float = 0.0
    height: float = 0.0
    dessin: bool = False
    dessin_nom: str = ""
    check: bool = True
    single: bool = True
    multiple_exact: bool = False
    multiple_progressive: bool = False
    min0: bool = True  # Si True, la note minimale est 0 (pas de points négatifs)
    choices: list[Choice] = field(default_factory=list)
    index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "gain": self.gain,
            "penalty": self.penalty,
            "manual": self.manual,
            "width": self.width,
            "height": self.height,
            "dessin": self.dessin,
            "dessin_nom": self.dessin_nom,
            "check": self.check,
            "single": self.single,
            "multiple_exact": self.multiple_exact,
            "multiple_progressive": self.multiple_progressive,
            "min0": self.min0,
            "choices": [c.to_dict() for c in self.choices],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Question":
        return cls(
            index=int(d.get("index", 0)),
            name=str(d.get("name", "")),
            gain=float(d.get("gain", 1.0)),
            penalty=float(d.get("penalty", 1.0)),
            manual=bool(d.get("manual", False)),
            width=float(d.get("width", 0.0)),
            height=float(d.get("height", 0.0)),
            dessin=bool(d.get("dessin", False)),
            dessin_nom=str(d.get("dessin_nom", "")),
            check=bool(d.get("check", True)),
            single=bool(d.get("single", True)),
            multiple_exact=bool(d.get("multiple_exact", False)),
            multiple_progressive=bool(d.get("multiple_progressive", False)),
            min0=bool(d.get("min0", True)),
            choices=[Choice.from_dict(c) for c in d.get("choices", [])],
        )

    @property
    def multiple(self) -> bool:
        """Vrai si la question accepte plusieurs réponses (exact ou progressive)."""
        return self.multiple_exact or self.multiple_progressive

    def get_mark_range(self) -> tuple[float, float]:
        """Calcule l'intervalle de notes pour cette question (min, max).
        
        - max = gain si la question a au moins un choix correct, sinon 0
        - min = -penalty si la question a au moins un choix pénalisant, sinon 0
        """
        has_correct = any(c.correct for c in self.choices)
        has_penalty = any(c.penalty for c in self.choices)
        
        question_max = self.gain if has_correct else 0.0
        question_min = -self.penalty if has_penalty else 0.0
        
        return (question_min, question_max)


# ---------------------------------------------------------------------------
# Exercice
# ---------------------------------------------------------------------------

@dataclass
class Exercise:
    """Un exercice du QCM (regroupe plusieurs questions)."""

    name: str = ""
    header: str = ""
    # Barème : somme des questions (par défaut).
    sum: bool = True
    sum_bias: bool = False
    # Barème : validation par seuil.
    validation: bool = False
    bias: float = 0.0
    threshold: float = 0.0
    gain: float = 0.0
    # Points négatifs.
    min0: bool = False
    nomin: bool = True
    # Remise à l'échelle.
    noscale: bool = True
    scale: bool = False
    max: float = 0.0
    questions: list[Question] = field(default_factory=list)
    index: int = 0

    def get_mark_range(self) -> tuple[float, float]:
        """Calcule l'intervalle de notes pour cet exercice (min, max).
        
        Basé sur la logique du code original (index.html lignes ~5140-5180).
        Pour cet exercice :
        - max = somme des gains des questions QUI ONT des choix corrects (si sum=True)
          ou exercise.max (si sum=False)
        - min = -somme des pénalités des questions QUI ONT des choix pénalisants
        - Applique sum_bias, puis scale, puis min0 (dans cet ordre)
        """
        exercise_min = 0.0
        exercise_max = 0.0
        
        # Calcul du max
        for question in self.questions:
            # Seules les questions avec au moins un choix correct contribuent
            if any(c.correct for c in question.choices):
                exercise_max += question.gain
        
        # Calcul du min : soustraire les pénalités des questions avec choix pénalisants
        for question in self.questions:
            if any(c.penalty for c in question.choices):
                exercise_min -= question.penalty
        
        # Appliquer sum_bias
        if self.sum_bias:
            exercise_max -= self.bias
            exercise_min -= self.bias
        
        # Appliquer scale
        if self.scale and self.max > 0 and exercise_max > 0:
            exercise_min = exercise_min * self.max / exercise_max
            exercise_max = self.max
        
        # Appliquer min0 (dernière étape, comme dans le code original)
        if self.min0:
            exercise_min = 0.0
        
        return (exercise_min, exercise_max)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "header": self.header,
            "sum": self.sum,
            "sum_bias": self.sum_bias,
            "validation": self.validation,
            "bias": self.bias,
            "threshold": self.threshold,
            "gain": self.gain,
            "min0": self.min0,
            "nomin": self.nomin,
            "noscale": self.noscale,
            "scale": self.scale,
            "max": self.max,
            "questions": [q.to_dict() for q in self.questions],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Exercise":
        return cls(
            index=int(d.get("index", 0)),
            name=str(d.get("name", "")),
            header=str(d.get("header", "")),
            sum=bool(d.get("sum", True)),
            sum_bias=bool(d.get("sum_bias", False)),
            validation=bool(d.get("validation", False)),
            bias=float(d.get("bias", 0.0)),
            threshold=float(d.get("threshold", 0.0)),
            gain=float(d.get("gain", 0.0)),
            min0=bool(d.get("min0", False)),
            nomin=bool(d.get("nomin", True)),
            noscale=bool(d.get("noscale", True)),
            scale=bool(d.get("scale", False)),
            max=float(d.get("max", 0.0)),
            questions=[Question.from_dict(q) for q in d.get("questions", [])],
        )


# ---------------------------------------------------------------------------
# Variante et layout
# ---------------------------------------------------------------------------

@dataclass
class Layout:
    """Propriétés de mise en page portrait ('p') ou paysage ('l')."""

    orientation: str = "p"
    paper_format: str = "a4"
    page_width: float = 210.0
    page_height: float = 297.0
    margin_left: float = 10.0
    margin_top: float = 10.0
    margin_right: float = 10.0
    margin_bottom: float = 10.0
    page_center: float = 100.0
    header_height: float = 0.0
    header_left: str = ""
    header_middle: str = ""
    header_right: str = ""
    footer_height: float = 0.0
    footer_left: str = ""
    footer_middle: str = ""
    footer_right: str = ""
    # Repères d'alignement (5 cercles noirs).
    shapes_x: list[float] = field(default_factory=lambda: [0.0] * 5)
    shapes_y: list[float] = field(default_factory=lambda: [0.0] * 5)
    shapes_r: list[float] = field(default_factory=lambda: [2.0] * 5)
    # Code-barres.
    barcode_height: float = 10.0
    barcode_resolution: float = 0.5
    barcode_top: float = 0.0
    barcode_prefix: str = ""
    barcode_length: int = 0

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Layout":
        # On accepte un dict incomplet (layouts stockés dans variants).
        kwargs = {k: copy.deepcopy(v) for k, v in d.items()}
        # On ne garde que les champs connus.
        known = {f.name for f in cls.__dataclass_fields__.values()}
        kwargs = {k: v for k, v in kwargs.items() if k in known}
        return cls(**kwargs)


@dataclass
class Variant:
    """Une variante générée (un sujet imprimé)."""

    layout: str = "p"  # 'p' ou 'l'
    id: int = 0
    barcode_text: str = ""
    barcode_width: float = 0.0
    barcode_left: float = 0.0
    # Textes, rectangles, cercles, marks (coordonnées en mm, relatif page).
    texts: list[dict] = field(default_factory=list)
    rects: list[dict] = field(default_factory=list)
    circles: list[dict] = field(default_factory=list)
    marks: list[dict] = field(default_factory=list)
    # Boîte d'identification étudiant.
    id_x: float = 0.0
    id_y: float = 0.0
    id_width: float = 0.0
    id_height: float = 0.0
    id_columns: list[float] = field(default_factory=list)
    id_lines: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Variant":
        kwargs = {k: copy.deepcopy(v) for k, v in d.items()}
        known = {f.name for f in cls.__dataclass_fields__.values()}
        kwargs = {k: v for k, v in kwargs.items() if k in known}
        return cls(**kwargs)


class VariantStore(dict):
    """Conteneur des variantes indexé par id (str), avec layouts 'p'/'l'.

    Reproduit la variable globale ``variants`` du code original : un dict dont
    les clés sont les ids de variantes (en str) et 'p'/'l' pour les layouts.
    """

    def layout(self, orientation: str) -> Layout | None:
        v = self.get(orientation)
        if v is None:
            return None
        if isinstance(v, Layout):
            return v
        return Layout.from_dict(v)

    def variant(self, variant_id: int | str) -> Variant | None:
        v = self.get(str(variant_id))
        if v is None:
            return None
        if isinstance(v, Variant):
            return v
        return Variant.from_dict(v)

    def to_plain_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in self.items():
            if isinstance(value, (Layout, Variant)):
                out[key] = value.to_dict()
            else:
                out[key] = copy.deepcopy(value)
        return out

    @classmethod
    def from_plain_dict(cls, d: dict[str, Any]) -> "VariantStore":
        store = cls()
        for key, value in d.items():
            if key in ("p", "l"):
                store[key] = Layout.from_dict(value)
            elif key == "orientation":
                store[key] = value
            else:
                store[key] = Variant.from_dict(value)
        return store


# ---------------------------------------------------------------------------
# Paramètres du projet (settings)
# ---------------------------------------------------------------------------

# Formats de papier disponibles (largeur, hauteur) en mm, portrait.
PAPER_FORMATS: dict[str, tuple[float, float]] = {
    "a3": (297.0, 420.0),
    "a4": (210.0, 297.0),
    "a5": (148.5, 210.0),
}


@dataclass
class ProjectSettings:
    """Paramètres du QCM sauvegardés dans le projet JSON.

    Reprend les champs de l'interface (éléments d'id ``.setting``) utilisés par
    la génération. Les booléens correspondent aux boutons ``button_checked``.
    """

    # Informations du QCM.
    establishment: str = ""
    institute: str = ""
    formation: str = ""
    year: str = ""
    semester: str = ""
    teaching_unit: str = ""
    module_full: str = ""
    module_short: str = ""
    evaluation_full: str = ""
    evaluation_short: str = ""
    teachers: str = ""
    date: str = ""
    duration: str = ""

    # Format de page.
    paper_a3: bool = False
    paper_a4: bool = True
    paper_a5: bool = False
    paper_portrait: bool = True
    paper_landscape: bool = False
    paper_both: bool = False
    margin_left: float = 10.0
    margin_top: float = 10.0
    margin_right: float = 10.0
    margin_bottom: float = 10.0

    # En-tête / pied de page.
    header_left: str = ""
    header_middle: str = ""
    header_right: str = ""
    footer_left: str = ""
    footer_middle: str = ""
    footer_right: str = ""

    # Sens de lecture (True = gauche puis bas, False = haut puis droite).
    identification_dir_left: bool = True
    identification_dir_top: bool = False
    identification_dir_both: bool = False
    exercise_dir_left: bool = False
    exercise_dir_top: bool = False
    exercise_dir_both: bool = True
    question_dir_left: bool = False
    question_dir_top: bool = False
    question_dir_both: bool = True
    choice_dir_left: bool = False
    choice_dir_top: bool = False
    choice_dir_both: bool = True

    # Ajouts « fantômes » et « seconde chance ».
    choice_joker_always: bool = True
    choice_joker_never: bool = False
    exercise_new_never: bool = False
    exercise_new_always: bool = True
    exercise_new_sometimes: bool = False
    exercise_new_exercises: int = 1
    exercise_new_questions: int = 1
    exercise_new_choices: int = 4
    exercise_new_exercises_name: str = "Exercice"
    exercise_new_questions_name: str = "Question"
    exercise_new_choices_name: str = "X"
    question_new_never: bool = True
    question_new_always: bool = False
    question_new_sometimes: bool = False
    question_new_questions: int = 1
    question_new_choices: int = 4
    question_new_questions_name: str = "Question"
    question_new_choices_name: str = "X"
    choice_new_never: bool = True
    choice_new_always: bool = False
    choice_new_sometimes: bool = False
    choice_new_choices_name: str = "X"
    choice_new_choices: int = 1
    choice_checked_never: bool = False
    choice_checked_always: bool = True
    choice_checked_sometimes: bool = False

    # Ordre aléatoire.
    exercise_order_never: bool = True
    exercise_order_always: bool = False
    exercise_order_sometimes: bool = False
    question_order_never: bool = True
    question_order_always: bool = False
    question_order_sometimes: bool = False
    choice_order_never: bool = True
    choice_order_always: bool = False
    choice_order_sometimes: bool = False

    # Génération des variantes.
    generate_students: int = 1
    generate_count: int = 1
    generate_variants: str = ""
    generate_retry: bool = True
    generate_stop: bool = False
    generate_per_variant: bool = True
    generate_per_student: bool = False

    modified: bool = False

    # Propriétés calculées à partir d'autres champs (helpers).
    @property
    def name_short(self) -> str:
        return self.evaluation_short

    @property
    def course_short(self) -> str:
        return self.module_short

    @property
    def paper_format(self) -> str:
        if self.paper_a3:
            return "a3"
        if self.paper_a5:
            return "a5"
        return "a4"

    @property
    def paper_dimensions(self) -> tuple[float, float]:
        """Retourne (largeur, hauteur) portrait en mm."""
        return PAPER_FORMATS[self.paper_format]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ProjectSettings":
        s = cls()
        known = s.__dict__

        # Mapping des champs info_* vers les champs du modèle
        info_mapping = {
            'info_university': 'establishment',
            'info_college': 'institute',
            'info_departement': 'formation',
            'info_year': 'year',
            'info_semester': 'semester',
            'info_course_unit': 'teaching_unit',
            'info_course_long': 'module_full',
            'info_course_short': 'module_short',
            'info_name_long': 'evaluation_full',
            'info_name_short': 'evaluation_short',
            'info_authors_short': 'teachers',
            'info_date': 'date',
            'info_duration': 'duration',
        }

        # Champs à convertir en int (même s'ils sont stockés en string dans le JSON)
        int_fields = {
            'generate_students', 'generate_count', 'generate_retry', 'generate_stop',
            'generate_per_variant', 'generate_per_student', 'exercise_new_exercises',
            'exercise_new_questions', 'exercise_new_choices', 'question_new_questions',
            'question_new_choices', 'choice_new_choices', 'choice_checked_never',
            'choice_checked_always', 'choice_checked_sometimes', 'choice_joker_always',
            'choice_joker_never', 'exercise_new_never', 'exercise_new_always',
            'exercise_new_sometimes', 'question_new_never', 'question_new_always',
            'question_new_sometimes', 'choice_new_never', 'choice_new_always',
            'choice_new_sometimes', 'exercise_order_never', 'exercise_order_always',
            'exercise_order_sometimes', 'question_order_never', 'question_order_always',
            'question_order_sometimes', 'choice_order_never', 'choice_order_always',
            'choice_order_sometimes'
        }

        for key, value in d.items():
            if key in known:
                # Conversion automatique pour les champs entiers
                if key in int_fields and isinstance(value, str):
                    setattr(s, key, int(value))
                else:
                    setattr(s, key, copy.deepcopy(value))
            elif key in info_mapping:
                target_key = info_mapping[key]
                if target_key in known:
                    if target_key in int_fields and isinstance(value, str):
                        setattr(s, target_key, int(value))
                    else:
                        setattr(s, target_key, copy.deepcopy(value))
        return s

# ---------------------------------------------------------------------------
# Étudiant (table Scodoc)
# ---------------------------------------------------------------------------

@dataclass
class Student:
    """Un étudiant de la table Scodoc (levée d'anonymat)."""

    id: str = ""       # 'p' + 7 chiffres (sans le 'p' initial de Scodoc)
    eid: str = ""      # etudid
    nip: str = ""      # code_nip (commence par 'p' dans Scodoc)
    name: str = ""
    firstname: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "eid": self.eid,
            "nip": self.nip,
            "name": self.name,
            "firstname": self.firstname,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Student":
        return cls(
            id=str(d.get("id", "")),
            eid=str(d.get("eid", "")),
            nip=str(d.get("nip", "")),
            name=str(d.get("name", "")),
            firstname=str(d.get("firstname", "")),
        )


# ---------------------------------------------------------------------------
# Projet complet
# ---------------------------------------------------------------------------

@dataclass
class Project:
    """Un projet QCM complet : paramètres + structure + variantes + étudiants."""

    settings: ProjectSettings = field(default_factory=ProjectSettings)
    structure: list[Exercise] = field(default_factory=list)
    variants: VariantStore = field(default_factory=VariantStore)
    students: dict[str, Student] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "settings": self.settings.to_dict(),
            "variants": self.variants.to_plain_dict(),
            "structure": [e.to_dict() for e in self.structure],
            "students": {k: s.to_dict() for k, s in self.students.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Project":
        # Gérer les anciens JSON où les champs sont à la racine
        settings_dict = d.get("settings", {})

        # Si pas de "settings" mais des champs info_* à la racine → ancien format
        if not settings_dict and any(k.startswith("info_") for k in d.keys()):
            # Extraire tous les champs connus + info_* pour le mapping
            known_fields = {f.name for f in ProjectSettings.__dataclass_fields__.values()}
            settings_dict = {k: v for k, v in d.items()
                        if k.startswith("info_") or k in known_fields}

        settings = ProjectSettings.from_dict(settings_dict)
        variants = VariantStore.from_plain_dict(d.get("variants", {}))
        structure = [Exercise.from_dict(e) for e in d.get("structure", [])]
        students = {
            k: Student.from_dict(v) for k, v in d.get("students", {}).items()
        }
        return cls(settings=settings, variants=variants,
                structure=structure, students=students)

    def get_mark_range(self) -> tuple[float, float]:
        """Calcule l'intervalle de notes du QCM (min, max).
        
        Basé sur la logique du code original (index.html lignes ~5140-5180).
        Pour chaque exercice :
        - max = somme des gains des questions QUI ONT des choix corrects (si sum=True)
          ou exercise.max (si sum=False)
        - min = -somme des pénalités des questions QUI ONT des choix pénalisants
        - Applique sum_bias, puis scale, puis min0 (dans cet ordre)
        """
        global_min = 0.0
        global_max = 0.0
        
        for exercise in self.structure:
            exercise_min = 0.0
            exercise_max = 0.0
            
            # Calcul du max : TOUJOURS la somme des gains des questions avec choix corrects
            # (Le champ exercise.max n'est utilisé que pour la mise à l'échelle si scale=True)
            for question in exercise.questions:
                if any(c.correct for c in question.choices):
                    exercise_max += question.gain
            
            # Calcul du min : soustraire les pénalités des questions avec choix pénalisants
            for question in exercise.questions:
                if any(c.penalty for c in question.choices):
                    exercise_min -= question.penalty
            
            # Appliquer sum_bias
            if exercise.sum_bias:
                exercise_max -= exercise.bias
                exercise_min -= exercise.bias
            
            # Appliquer scale
            if exercise.scale and exercise.max > 0 and exercise_max > 0:
                exercise_min = exercise_min * exercise.max / exercise_max
                exercise_max = exercise.max
            
            # Appliquer min0 (dernière étape, comme dans le code original)
            if exercise.min0:
                exercise_min = 0.0
            
            global_min += exercise_min
            global_max += exercise_max

        
        return (global_min, global_max)
