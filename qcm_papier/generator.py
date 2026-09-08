"""Génération des variantes d'un QCM.

Reproduit la fonction ``FileGenerate`` du code JavaScript original
(index.html lignes ~6188-6838) : pour chaque id de variante, on construit le
layout (portrait/paysage), on place les repères d'alignement, le code-barres,
la boîte d'identification étudiant, puis on dispose les exercices, questions et
choix selon les sens de lecture et les ajouts fantômes paramétrés.

Le résultat est stocké dans un ``VariantStore`` (dict indexé par id de variante
+ layouts 'p'/'l'), identique en structure à la variable globale ``variants``
du code original.
"""

from __future__ import annotations

import random

import math
from typing import Any

from . import random_gen as rg
from .code39 import code39_width
from .model import (
    Exercise,
    Layout,
    Project,
    ProjectSettings,
    Question,
    Variant,
    VariantStore,
)

def _exercise_to_dict(e) -> dict:
    """Convertit un Exercise (ou dict) en dict brut (format JS)."""
    if isinstance(e, dict):
        return dict(e)
    return {
        "index": e.index, "name": e.name, "header": e.header,
        "sum": e.sum, "sum_bias": e.sum_bias, "validation": e.validation,
        "bias": e.bias, "threshold": e.threshold, "gain": e.gain,
        "min0": e.min0, "nomin": e.nomin, "noscale": e.noscale,
        "scale": e.scale, "max": e.max,
        "questions": [_question_to_dict(q) for q in e.questions],
    }

def _question_to_dict(q) -> dict:
    if isinstance(q, dict):
        return dict(q)
    return {
        "index": q.index, "name": q.name, "gain": q.gain,
        "penalty": q.penalty, "manual": q.manual, "width": q.width,
        "height": q.height, "dessin": q.dessin, "dessin_nom": q.dessin_nom,
        "check": q.check, "single": q.single,
        "multiple_exact": q.multiple_exact,
        "multiple_progressive": q.multiple_progressive,
        "choices": [_choice_to_dict(c) for c in q.choices],
    }

def _choice_to_dict(c) -> dict:
    if isinstance(c, dict):
        return dict(c)
    return {
        "index": c.index, "name": c.name, "correct": c.correct,
        "neutral": c.neutral, "penalty": c.penalty,
    }

# Hauteur de ligne en mm (12 pt → mm). Reprend ``line_height = 12 / 2.835``.
LINE_HEIGHT = 12 / 2.835

# Bits utilisés par ``pseudoRandom`` (index.html ~6270-6290).
BIT_IDENT_DIR = 1
BIT_EXERCISE_DIR = 2
BIT_QUESTION_DIR = 3
BIT_CHOICE_DIR = 4
BIT_EXERCISE_NEW = 4
BIT_QUESTION_NEW = 6
BIT_CHOICE_NEW = 7
BIT_CHOICE_CHECKED = 8
BIT_EXERCISE_ORDER = 8
BIT_QUESTION_ORDER = 10
BIT_CHOICE_ORDER = 11

# ---------------------------------------------------------------------------
# Helpers de boutons à 3 états (depuis les ProjectSettings)
# ---------------------------------------------------------------------------
def _tri(settings: ProjectSettings, base: str, alt: str, rand: str) -> rg.TriChoice:
    """Retourne TriChoice.BASE (NEVER), TriChoice.ALT (ALWAYS) ou TriChoice.RANDOM (SOMETIMES).
    base, alt et rand sont les noms des 3 champs booléens d'un même groupe.
    Exemple: base="question_order_never", alt="question_order_always", rand="question_order_sometimes".
    Retourne TriChoice selon lequel des 3 est True dans settings.
    Priorité : SOMETIMES > ALWAYS > NEVER (pour gérer les conflits).
    """
    # Détecter le type de groupe
    is_dir_group = base.endswith("_left") or base.endswith("_top") or base.endswith("_both")
    is_order_group = "order" in base

    # Récupérer les valeurs (avec inversion si nécessaire)
    if is_dir_group:
        base_val, alt_val, rand_val = (
            getattr(settings, base, False),
            getattr(settings, alt, False),
            getattr(settings, rand, False),
        )
    elif is_order_group:
        base_val, alt_val, rand_val = (
            getattr(settings, base, True),
            getattr(settings, alt, False),
            getattr(settings, rand, False),
        )
    else:  # new/checked
        base_val, alt_val, rand_val = (
            getattr(settings, base, True),
            getattr(settings, alt, False),
            getattr(settings, rand, False),
        )
    
    # Priorité : SOMETIMES ou (ALWAYS et NEVER) > ALWAYS > NEVER
    if rand_val or (alt_val and base_val):  # ← Gestion des conflits, ce serait un bug dans les données
        return rg.TriChoice.RANDOM
    elif alt_val:
        return rg.TriChoice.ALT
    else:  # si base_val ou aucun
        return rg.TriChoice.BASE    
    
def _settings_tri_groups() -> dict[str, tuple[str, str, str]]:
    """Mappe chaque groupe aux 3 champs booléens.
    Ordre : (Jamais, Toujours, De temps en temps)"""
    return {
        "paper_orientation": ("paper_portrait", "paper_landscape", "paper_both"),
        "identification_dir": ("identification_dir_left", "identification_dir_top", "identification_dir_both"),
        "exercise_dir": ("exercise_dir_left", "exercise_dir_top", "exercise_dir_both"),
        "question_dir": ("question_dir_left", "question_dir_top", "question_dir_both"),
        "choice_dir": ("choice_dir_left", "choice_dir_top", "choice_dir_both"),
        "exercise_new": ("exercise_new_never", "exercise_new_always", "exercise_new_sometimes"),
        "question_new": ("question_new_never", "question_new_always", "question_new_sometimes"),  # ✅ ICI : "never" en premier
        "choice_new": ("choice_new_never", "choice_new_always", "choice_new_sometimes"),
        "choice_checked": ("choice_checked_never", "choice_checked_always", "choice_checked_sometimes"),
        "exercise_order": ("exercise_order_never", "exercise_order_always", "exercise_order_sometimes"),
        "question_order": ("question_order_never", "question_order_always", "question_order_sometimes"),
        "choice_order": ("choice_order_never", "choice_order_always", "choice_order_sometimes"),
    }


# ---------------------------------------------------------------------------
# Construction du layout (portrait/paysage)
# ---------------------------------------------------------------------------

def _header_footer_height(settings: ProjectSettings) -> tuple[float, float]:
    """Calcule les hauteurs d'en-tête et de pied de page (en mm).

    Reprend ``layout.header_height = max(nb_lignes(gauche,milieu,droite)) *
    line_height * 1.15`` du code original.
    """
    def nb_lines(text: str) -> int:
        return len(text.split("\n")) if text else 0

    header_h = max(nb_lines(settings.header_left),
                   nb_lines(settings.header_middle),
                   nb_lines(settings.header_right), 0)
    footer_h = max(nb_lines(settings.footer_left),
                   nb_lines(settings.footer_middle),
                   nb_lines(settings.footer_right), 0)
    return header_h * LINE_HEIGHT * 1.15, footer_h * LINE_HEIGHT * 1.15

def build_layout(settings: ProjectSettings, orientation: str) -> Layout:
    """Construit un layout portrait ('p') ou paysage ('l').

    Reprend la construction de ``layout`` dans ``FileGenerate``
    (index.html ~6235-6330) — repères, marges, en-tête/pied, code-barres.
    """
    paper_w, paper_h = settings.paper_dimensions
    layout = Layout(orientation=orientation, paper_format=settings.paper_format)
    if orientation == "p":
        layout.page_width = paper_w
        layout.page_height = paper_h
    else:  # 'l'
        layout.page_width = paper_h
        layout.page_height = paper_w

    layout.margin_left = settings.margin_left
    layout.margin_top = settings.margin_top
    layout.margin_right = settings.margin_right
    layout.margin_bottom = settings.margin_bottom
    layout.page_center = (layout.margin_left + layout.page_width
                          - layout.margin_right) / 2

    header_h, footer_h = _header_footer_height(settings)
    layout.header_height = header_h
    layout.footer_height = footer_h
    layout.header_left = settings.header_left
    layout.header_middle = settings.header_middle
    layout.header_right = settings.header_right
    layout.footer_left = settings.footer_left
    layout.footer_middle = settings.footer_middle
    layout.footer_right = settings.footer_right

    # Repères d'alignement (5 cercles noirs).
    layout.shapes_x = [
        layout.margin_left + 2,
        layout.margin_left + 2,
        layout.margin_left + 2,
        layout.page_width - layout.margin_right - 2,
        layout.page_width - layout.margin_right - 2,
    ]
    layout.shapes_y = [
        layout.margin_top + layout.header_height + 12,
        layout.margin_top + layout.header_height + 37,
        layout.page_height - layout.margin_bottom - layout.footer_height - 8,
        layout.page_height - layout.margin_bottom - layout.footer_height - 3,
        layout.margin_top + layout.header_height + 7,
    ]
    layout.shapes_r = [2, 2, 2, 2, 2]

    # Code-barres.
    layout.barcode_height = 10.0
    layout.barcode_resolution = 0.5
    layout.barcode_top = (layout.page_height - layout.margin_bottom
                          - layout.footer_height - layout.barcode_height)
    layout.barcode_prefix = (settings.module_short + settings.evaluation_short
                              + settings.year + "-")
    # Longueur = préfixe + 6 ('*' + 4 chiffres + '*').
    layout.barcode_length = len(layout.barcode_prefix) + 6
    return layout

# ---------------------------------------------------------------------------
# Texte du code-barres d'une variante
# ---------------------------------------------------------------------------

def barcode_text(prefix: str, variant_id: int) -> str:
    """Construit le texte Code 39 d'une variante (avec '*' de début/fin).

    Reprend la logique de padding sur 4 chiffres (index.html ~6332-6340).
    """
    if variant_id < 10:
        digits = "000" + str(variant_id)
    elif variant_id < 100:
        digits = "00" + str(variant_id)
    elif variant_id < 1000:
        digits = "0" + str(variant_id)
    else:
        digits = str(variant_id)
    return "*" + prefix + digits + "*"

# ---------------------------------------------------------------------------
# Fusion de listes (mergeArrays du code original)
# ---------------------------------------------------------------------------

def _merge_arrays(target: list, source: list, delta_x: float, delta_y: float) -> None:
    for item in source:
        item = dict(item)  # copie pour ne pas muter la source
        item["x"] = item.get("x", 0) + delta_x
        item["y"] = item.get("y", 0) + delta_y
        target.append(item)

# ---------------------------------------------------------------------------
# Boîte d'identification étudiant
# ---------------------------------------------------------------------------

def _build_identification(variant: Variant, layout: Layout,
                          settings: ProjectSettings, variant_id: int) -> None:
    """Construit la boîte d'identification (textes + cases pour le n° étudiant).

    Reprend la construction de la ``identification box`` (index.html ~6345-6390).
    """
    alt = rg.pseudo_random(variant_id, 0, BIT_IDENT_DIR,
                           _tri(settings, "identification_dir_left", "identification_dir_top", "identification_dir_both"))
    variant.id_x = layout.margin_left + 10
    variant.id_y = layout.margin_top + layout.header_height + 5
    id_texts = [
        {"x": 2, "y": 7, "t": "Numéro identifiant de l'étudiant : p"},
        {"x": 2, "y": 17, "t": "Nom :"},
        {"x": 2, "y": 27, "t": "Prénom :"},
        {"x": 2, "y": 37, "t": "Groupe :"},
        {"x": 2, "y": 43, "t": "Variante du test : " + str(variant_id)},
    ]
    _merge_arrays(variant.texts, id_texts, variant.id_x, variant.id_y)
    if alt:
        # de haut en bas puis de gauche à droite.
        variant.id_width = 130
        variant.id_height = 45
        variant.id_columns = [c + variant.id_x for c in
                              [65, 71, 77, 83, 89, 95, 101, 107, 113, 119, 125]]
        variant.id_lines = [l + variant.id_y for l in
                            [10, 15, 20, 25, 30, 35, 40]]
    else:
        # de gauche à droite puis de haut en bas.
        variant.id_width = 110
        variant.id_height = 60
        variant.id_columns = [c + variant.id_x for c in
                              [70, 76, 82, 88, 94, 100, 106]]
        variant.id_lines = [l + variant.id_y for l in
                            [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]]
    variant.rects.append({
        "x": variant.id_x, "y": variant.id_y,
        "w": variant.id_width, "h": variant.id_height,
    })

# ---------------------------------------------------------------------------
# Largeur/hauteur d'un texte (approximation reportlab-like)
# ---------------------------------------------------------------------------

def _text_width(text: str, font_size: float = 12) -> float:
    """Largeur approximative d'un texte en mm (Helvetica 12 pt).

    ReportLab mesure en points : on convertit en mm (1 pt = 25.4/72 mm). On
    utilise la métrique de ReportLab quand elle est disponible, sinon une
    approximation moyenne (0.5 pt par caractère).
    """
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth
        # stringWidth renvoie la largeur en points ; conversion en mm.
        return stringWidth(text or "", "Helvetica", font_size) * 25.4 / 72
    except Exception:
        return len(text or "") * font_size * 0.5 * 25.4 / 72

# ---------------------------------------------------------------------------
# Placement des choix d'une question
# ---------------------------------------------------------------------------

def _place_choices(variant, variant_id,
                   exercise, question,
                   exercise_index: int, question_iter: int,
                   question_name_width_max: float,
                   settings: ProjectSettings) -> tuple[list, list, list, list, float, float]:
    """Place les choix d'une question.

    Renvoie ``(texts, rects, circles, marks, width, height)`` (relatifs à la
    question). Reprend la boucle ``while(choice_list.length > 0)``
    (index.html ~6540-6680).
    """
    texts: list[dict] = []
    rects: list[dict] = []
    circles: list[dict] = []
    marks: list[dict] = []
    
    texts.append({"x": 2, "y": 5, "t": question.get("name", "")})
    question_name_width = _text_width(question.get("name", ""))  # Largeur du nom de cette question

    if question.get("manual", False):
        width = float(question.get("width", 0))
        height = float(question.get("height", 0))
        rects.append({"x": 2, "y": 6, "w": width, "h": height})
        if exercise.get("index", -1) >= 0 and question.get("index", -1) >= 0:
            marks.append({"x": 2, "y": 6, "w": width, "h": height,
                          "e": exercise.get("index", -1), "q": question.get("index", -1)})
        q_width = max(question_name_width, width) + 4
        q_height = height + 8
        return texts, rects, circles, marks, q_width, q_height

    if not question.get("check", True):
        # Question sans cases à cocher : juste le nom.
        return texts, rects, circles, marks, question_name_width + 4, 7

    # Choix de direction / ajout fantôme / pré-coche / ordre.
    question_dir = rg.pseudo_random(variant_id, variant_id, BIT_QUESTION_DIR,
                                     _tri(settings, "question_dir_left", "question_dir_top", "question_dir_both"))
    choice_dir = rg.pseudo_random(variant_id, variant_id, BIT_CHOICE_DIR,
                                   _tri(settings, "choice_dir_left", "choice_dir_top", "choice_dir_both"))
    choice_new = rg.pseudo_random(variant_id, question_iter, BIT_CHOICE_NEW,
                                  _tri(settings, "choice_new_never", "choice_new_always", "choice_new_sometimes"))
    choice_checked = rg.pseudo_random(variant_id, question_iter, BIT_CHOICE_CHECKED,
                                      _tri(settings, "choice_checked_never", "choice_checked_always", "choice_checked_sometimes"))
    choice_random = rg.pseudo_random(variant_id, question_iter, BIT_CHOICE_ORDER,
                                     _tri(settings, "choice_order_never", "choice_order_always", "choice_order_sometimes"))

    choice_list = [_choice_to_dict(ch) for ch in question.get("choices", [])]
    if choice_new:
        additional = 0
        if question_dir != choice_dir:
            # On ajuste au nombre max de choix des autres questions.
            additional = _max_choice_count(exercise) - len(choice_list)
            if additional < 0:
                additional = 0
        if exercise.get("index", -1) >= 0 and question.get("index", -1) >= 0:
            rg.insert_choices(variant_id + question_iter, choice_list, additional,
                              new_choices_name=settings.question_new_choices_name,
                              new_choices_count=settings.question_new_choices
                              if exercise.get("index", -1) >= 0 else 1)

    choice_x = 0.0
    choice_y = 0.0
    if choice_dir:
        # de haut en bas.
        choice_x = question_name_width / 2
        if settings.choice_joker_always:
            choice_x -= 3
            if choice_x < 2:
                choice_x = 2
        choice_y = 5
    else:
        # de gauche à droite.
        choice_x = question_name_width + 4

    choice_iter = 0
    while choice_list:
        if choice_random:
            choice_index = rg.random_index(variant_id, len(choice_list))
        else:
            choice_index = 0
        choice = choice_list[choice_index]
        choice_list.pop(choice_index)

        x = choice_x + 2
        y = choice_y + 3
        if choice_dir:
            choice_y += 5
        else:
            choice_x += 6

        texts.append({"x": x, "y": y, "t": choice.get("name", ""),
                      "center": True})
        
        # Déterminer le niveau de fantôme
        exercice_fantome = exercise.get("index", -1) < 0
        question_fantome = question.get("index", -1) < 0
        choix_fantome = choice.get("index", -1) < 0
        niveau_fantome = sum([exercice_fantome, question_fantome, choix_fantome])
        
        # Placer le cercle (pré-coché ou non)
        # les vraies cases à cocher et la première ligne des exercices fantomes
        if choice.get("index", -1) >= 0:
            # Choix NORMAL : jamais pré-coché aléatoirement
            # (choice_checked est utilisé pour les choix normaux dans les questions normales)
            # NE PAS précoche tout pour l'exercice !
            if niveau_fantome == 0 and choice_checked:
                circles.append({"x": x, "y": y, "r": -2.3, "index": choice.get("index", -1)})
            else:
                circles.append({"x": x, "y": y, "r": 2.3, "index": choice.get("index", -1)})
        else:
            # Choix FANTÔME : probabilité basée sur le niveau
            # cas pas de joker, case à cocher
            if niveau_fantome > 0:
                # Premier choix fantôme : 1/(2*niveau)
                # Second choix fantôme : 2/(2*niveau) = 1/niveau
                if random.randint(1, 2 * niveau_fantome) < (2 if choix_fantome else 1):
                    circles.append({"x": x, "y": y, "r": -2.3, "index": choice.get("index", -1)})
                else:
                    circles.append({"x": x, "y": y, "r": 2.3, "index": choice.get("index", -1)})
        
        # je ne sais pas quand on peut passer ici !
        if (exercise.get("index", -1) >= 0 and question.get("index", -1) >= 0
                and choice.get("index", -1) >= 0):
            marks.append({"x": x, "y": y, "r": 2.3*0.2,
                          "e": exercise.get("index", -1), "q": question.get("index", -1),
                          "c": choice.get("index", 0)})
        choice_iter += 1

    # Ajout « seconde chance » (joker) : duplication des choix en pointillés.
    # Il faut distinguer 3 cas :
    # 1. Pas de ligne seconde chance (settings.choice_joker_always = False) -> rien
    # 2. Première ligne (originale) : probabilités selon présence de fantômes
    # 3. Seconde ligne (joker) : probabilités fixes
    if settings.choice_joker_always:
        delta_x = 0.0
        delta_y = 0.0
        if choice_dir:
            delta_x = 6
        else:
            delta_y = 6
        dup_texts = [dict(t) for t in texts[1:]]  # sans le nom de question
        dup_circles = []
        
        # Vérifier si la question a des choix fantômes (index < 0)
        a_des_choix_fantomes = any(c.get("index", -1) < 0 for c in circles)
        
        # Pour la PREMIÈRE LIGNE (circles existants) :
        # On modifie directement les circles originaux selon les règles
        for i, c in enumerate(circles):
            choice_index = c.get("index", -1)
            
            if choice_index >= 0:
                # Cas 2: Première ligne, choix original (index >= 0)
                # les Item qui ne sont pas à cocher de la première ligne de chaque question
                # -> TOUJOURS cercle vide (pas de pré-cochage aléatoire)
                c["r"] = 2.3
            else:
                # Cas 2: Première ligne, choix fantôme (index < 0)
                # les items fantomes de la première ligne de chaque question
                # 33% de chance de pré-cocher
                if random.randint(1, 3) == 1:  # 1/3 ≈ 33%
                    c["r"] = -2.3  # précoché
                else:
                    c["r"] = 2.3  # non précoché
        
        # Pour la SECONDE LIGNE (joker) : duplication avec pointillés
        # Il manque à cocher la seconde ligne des exercices fantômes
        for i, c in enumerate(circles):
            cc = dict(c)
            cc["dash"] = True  # Trait pointillé pour le joker
            
            # Cas 3: Seconde ligne (joker) - probabilités INDEPENDANTES
            choice_index = c.get("index", -1)
            if choice_index >= 0:
                # Choix original sur la ligne joker : 50%
                if random.randint(1, 2) == 1:
                    cc["r"] = -2.3  # précoché
                else:
                    cc["r"] = 2.3  # non précoché
            else:
                # Choix fantôme sur la ligne joker : 33%
                if random.randint(1, 3) == 1:
                    cc["r"] = -2.3  # précoché
                else:
                    cc["r"] = 2.3  # non précoché
            
            dup_circles.append(cc)
        dup_marks = []
        for m in marks:
            mm = dict(m)
            mm["joker"] = True
            dup_marks.append(mm)
        _merge_arrays(texts, dup_texts, delta_x, delta_y)
        _merge_arrays(circles, dup_circles, delta_x, delta_y)
        _merge_arrays(marks, dup_marks, delta_x, delta_y)

    # Dimensions de la question.
    if choice_dir:
        # de haut en bas : la hauteur a augmenté à chaque choix.
        question_height = choice_y + 2  # approximation (5 + 5*nb + 7)
        question_width = question_name_width + 4
    else:
        question_width = choice_x + 4
        question_height = 13 if settings.choice_joker_always else 7

    # On recalcule proprement la hauteur/largeur cumulées (comme le JS).
    # Le JS accumule ``question_height += 5`` par choix puis ``+ 7`` à la fin
    # (cas choice_dir) ; pour choice_x += 6 par choix puis ``+ question_name_width_max + 4``.
    return texts, rects, circles, marks, question_width, question_height

def _max_choice_count(exercise) -> int:
    """Nombre maximum de choix parmi les questions réelles (index >= 0)."""
    m = 0
    for q in exercise.get("questions", []):
        if q.get("index", -1) >= 0 and q.get("check", True) and len(q.get("choices", [])) > m:
            m = len(q.get("choices", []))
    return m

# ---------------------------------------------------------------------------
# Génération d'une variante
# ---------------------------------------------------------------------------

class GenerateError(Exception):
    """Levée quand une variante ne tient pas dans le format de papier."""

def generate_variant(project: Project, variant_id: int) -> Variant:
    """Génère une variante pour l'id donné."""
    settings = project.settings
    variant = Variant(layout="p", id=variant_id)
    print(f"entrée generate_variant avec {variant_id}")

    # Orientation portrait/paysage.
    if rg.pseudo_random(variant_id, 0, 0, _tri(settings, "paper_portrait", "paper_landscape", "paper_both")):
        variant.layout = "l"

    # Récupère ou crée le layout.
    layout = project.variants.layout(variant.layout)
    if layout is None:
        layout = build_layout(settings, variant.layout)
        project.variants[variant.layout] = layout

    # Code-barres.
    variant.barcode_text = barcode_text(layout.barcode_prefix, variant_id)
    variant.barcode_width = code39_width(variant.barcode_text,
                                         layout.barcode_resolution)
    variant.barcode_left = layout.page_center - variant.barcode_width / 2

    # Boîte d'identification.
    _build_identification(variant, layout, settings, variant_id)

    # Paramètres de disposition des exercices.
    exercise_dir = rg.pseudo_random(variant_id, 0, BIT_EXERCISE_DIR,
                                     _tri(settings, "exercise_dir_left", "exercise_dir_top", "exercise_dir_both"))
    exercise_new = rg.pseudo_random(variant_id, 0, BIT_EXERCISE_NEW,
                                     _tri(settings, "exercise_new_never", "exercise_new_always", "exercise_new_sometimes"))
    exercise_random = rg.pseudo_random(variant_id, 0, BIT_EXERCISE_ORDER,
                                       _tri(settings, "exercise_order_never", "exercise_order_always", "exercise_order_sometimes"))

    # On travaille sur des dicts (comme le JS) pour pouvoir mélanger avec les
    # exercices/questions/choix « fantômes » insérés par insert_*.
    exercise_list = [_exercise_to_dict(e) for e in project.structure]
    if exercise_new:
        rg.insert_exercises(
            variant_id, exercise_list,
            new_exercises=settings.exercise_new_exercises,
            new_questions=settings.exercise_new_questions,
            new_choices=settings.exercise_new_choices,
            new_exercises_name=settings.exercise_new_exercises_name,
            new_questions_name=settings.exercise_new_questions_name,
            new_choices_name=settings.exercise_new_choices_name,
        )

    # --- NOUVELLE LOGIQUE DE PLACEMENT DES EXERCICES ---
    # Détermine si on va vers la droite ou vers le bas
    go_right = ((exercise_dir and variant.layout == "p") or (not exercise_dir and variant.layout == "l"))
    # Limites de la page
    max_width = layout.page_width - layout.margin_right
    max_height = layout.barcode_top

    # Initialisation des variables pour les deux modes
    x_max = layout.margin_left
    y_max = variant.id_y + variant.id_height
    x_line_start = variant.id_x
    y_column_start = variant.id_y

    # Initialisation des positions selon le mode
    if go_right :
        # Mode "vers la droite" : première ligne commence après la boîte d'identification
        exercise_x = variant.id_x + variant.id_width
        exercise_y = variant.id_y
        y_max = variant.id_y + variant.id_height  # Point bas maximal initial (boîte d'identification)
        #x_line_start = variant.id_x + variant.id_width  # Début de ligne (après la boîte)
    else:
        # Mode "vers le bas" : première colonne commence sous la boîte d'identification
        exercise_x = layout.margin_left
        exercise_y = variant.id_y + variant.id_height
        x_max = variant.id_x + variant.id_width  # Point droit maximal initial (marge gauche)
        #y_column_start = variant.id_y + variant.id_height  # Début de colonne (sous la boîte)

    has_error = False
    exercise_iter = 0

    while exercise_list:
        if exercise_random:
            exercise_index = rg.random_index(variant_id, len(exercise_list))
        else:
            exercise_index = 0
        exercise = exercise_list[exercise_index]
        exercise_list.pop(exercise_index)
        
        questions_texts: list[dict] = []
        questions_rects: list[dict] = []
        questions_circles: list[dict] = []
        questions_marks: list[dict] = []

        # Nom de l'exercice.
        questions_texts.append({"x": 2, "y": 5, "t": exercise.get("name", "")})
        # Introduction (header) en italique après le nom
        header = exercise.get("header", "")
        if header:
            questions_texts.append({"x": 2 + _text_width(exercise.get("name", "")) + 2, "y": 5, "t": header, "i": True})
        exercise_name_width = _text_width(exercise.get("name", "")) + (2 + _text_width(header)) if header else _text_width(exercise.get("name", ""))

        question_dir = rg.pseudo_random(variant_id, variant_id, BIT_QUESTION_DIR,
                                         _tri(settings, "question_dir_left", "question_dir_top", "question_dir_both"))
        question_new = rg.pseudo_random(variant_id, exercise_iter, BIT_QUESTION_NEW,
                                         _tri(settings, "question_new_never", "question_new_always", "question_new_sometimes"))
        question_random = rg.pseudo_random(variant_id, exercise_iter,
                                            BIT_QUESTION_ORDER,
                                            _tri(settings, "question_order_never", "question_order_always", "question_order_sometimes"))
        question_list = [_question_to_dict(q) for q in exercise.get("questions", [])]
        if question_new and exercise.get("index", -1) >= 0:
            rg.insert_questions(
                variant_id + exercise_iter, question_list,
                new_questions=settings.question_new_questions,
                new_choices=settings.question_new_choices,
                new_questions_name=settings.question_new_questions_name,
                new_choices_name=settings.question_new_choices_name,
            )

        # Dimensions max des noms de questions (pour l'alignement).
        question_name_width_max = 0.0
        for q in question_list:
            qw = _text_width(q.get("name", ""))
            if question_name_width_max < qw:
                question_name_width_max = qw

        question_x = 0.0
        question_y = 6.0 # if (exercise.get("header", "") == "") else 12.0
        question_y_first = question_y
        exercise_width = exercise_name_width + 4
        exercise_height = 6.0

        question_iter = 0
        while question_list:
            if question_random:
                question_index = rg.random_index(variant_id, len(question_list))
            else:
                question_index = 0
            question = question_list[question_index]
            question_list.pop(question_index)
            
            qt, qr, qc, qm, qw, qh = _place_choices(
                variant, variant_id, exercise, question,
                exercise.get("index", -1), question_iter,
                question_name_width_max, settings,
            )

            # Gestion du retour à la ligne/colonne selon la direction.
            if question_dir:
                if question_y + qh > layout.barcode_top - exercise_y:
                    question_x = exercise_width
                    question_y = question_y_first
            else:
                if question_x + qw > max_width - exercise_x:
                    question_x = 0
                    question_y = exercise_height

            _merge_arrays(questions_texts, qt, question_x, question_y)
            _merge_arrays(questions_rects, qr, question_x, question_y)
            _merge_arrays(questions_circles, qc, question_x, question_y)
            _merge_arrays(questions_marks, qm, question_x, question_y)

            if question_dir:
                question_y += qh
                if exercise_height < question_y:
                    exercise_height = question_y
                if exercise_width < question_x + qw:
                    exercise_width = question_x + qw
            else:
                question_x += qw
                if exercise_width < question_x:
                    exercise_width = question_x
                if exercise_height < question_y + qh:
                    exercise_height = question_y + qh
            question_iter += 1

        # Cadre de l'exercice.
        questions_rects.append({"x": 0, "y": 0, "w": exercise_width, "h": exercise_height})

        # --- PLACEMENT DE L'EXERCICE SELON LE MODE (CORRIGÉ) ---
        placed = False
        place_x, place_y = exercise_x, exercise_y  # Position par défaut

        if go_right :
            # Mode "vers la droite"
            # 1. Essayer de placer à la position actuelle
            if (place_x + exercise_width <= max_width) and (place_y + exercise_height <= max_height):
                placed = True
            else:
                # 2. Si ça ne marche pas, essayer en début de nouvelle ligne
                place_x = x_line_start
                place_y = y_max
                if (place_x + exercise_width <= max_width) and (place_y + exercise_height <= max_height):
                    placed = True
                else:
                    has_error = True
                    print(f"[ERREUR] Exercice '{exercise.get('name', 'SANS NOM')}' ne tient pas (x+largeur={place_x + exercise_width:.1f}mm > {max_width}mm OU y+hauteur={place_y + exercise_height:.1f}mm > {max_height}mm) - mode droite")
                    break

            # Mettre à jour y_max si nécessaire
            if place_y + exercise_height > y_max:
                y_max = place_y + exercise_height

            # Mettre à jour exercise_x pour l'exercice SUIVANT (APRÈS placement)
            exercise_x = place_x + exercise_width
            exercise_y = place_y

        else:
            # Mode "vers le bas"
            # 1. Essayer de placer à la position actuelle
            if (place_x + exercise_width <= max_width) and (place_y + exercise_height <= max_height):
                placed = True
            else:
                # 2. Si ça ne marche pas, essayer en haut de nouvelle colonne
                place_x = x_max
                place_y = y_column_start
                if (place_x + exercise_width <= max_width) and (place_y + exercise_height <= max_height):
                    placed = True
                else:
                    has_error = True
                    print(f"[ERREUR] Exercice '{exercise.get('name', 'SANS NOM')}' ne tient pas (x+largeur={place_x + exercise_width:.1f}mm > {max_width}mm OU y+hauteur={place_y + exercise_height:.1f}mm > {max_height}mm) - mode bas")
                    break

            # Mettre à jour x_max si nécessaire
            if place_x + exercise_width > x_max:
                x_max = place_x + exercise_width

                # Mettre à jour exercise_y pour l'exercice SUIVANT (APRÈS placement)
            exercise_x = place_x
            exercise_y = place_y + exercise_height

        # --- Fusion des éléments à la position déterminée ---
        if placed:
            _merge_arrays(variant.texts, questions_texts, place_x, place_y)
            _merge_arrays(variant.rects, questions_rects, place_x, place_y)
            _merge_arrays(variant.circles, questions_circles, place_x, place_y)
            _merge_arrays(variant.marks, questions_marks, place_x, place_y)

        exercise_iter += 1

    if has_error:
        raise GenerateError(
            f"La variante {variant_id} ne tient pas dans le format "
            f"{layout.paper_format} ({layout.orientation})."
        )
    return variant

# ---------------------------------------------------------------------------
# Génération de toutes les variantes d'un projet
# ---------------------------------------------------------------------------

def generate_all(project: Project,
                retry: bool = True,
                max_errors: int = 10) -> tuple[list[int], list[int]]:
    """Génère toutes les variantes demandées par les paramètres."""
    import random

    # Vider les anciennes variantes (sauf layouts 'p' et 'l') avant nouvelle génération
    for k in list(project.variants.keys()):
        if k not in ("p", "l"):
            del project.variants[k]

    if not project.settings.generate_variants:
        count = project.settings.generate_count
        ids = [random.randint(0, 4095) for _ in range(count)]
        project.settings.generate_variants = ";".join(str(i) for i in ids)

    variant_ids = [int(x) for x in project.settings.generate_variants.split(";") if x]
    error_count = 0
    failed: list[int] = []
    success: list[int] = []  # Liste des IDs qui ont réellement réussi
    page = 0
    page_index = 0

    while page_index < len(variant_ids):
        variant_id = variant_ids[page_index]
        print(f"essai avec {variant_id}")
        page += 1
        try:
            variant = generate_variant(project, variant_id)
            project.variants[str(variant_id)] = variant
            success.append(variant_id)
            page_index += 1
            print(f"réussite : {variant_id}")
        except GenerateError:
            error_count += 1
            failed.append(variant_id)
            if error_count >= max_errors:
                break
            if retry:
                variant_ids[page_index] = random.randint(0, 4095)
            else:
                page_index += 1

    # Stocker TOUS les IDs (succès + remplacements) pour la prochaine génération
    project.settings.generate_variants = ";".join(str(i) for i in variant_ids)
    return success, failed
