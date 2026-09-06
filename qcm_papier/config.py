"""Configuration centrale pour le mapping des champs avec préfixes.

Ce module centralise la gestion des champs qui utilisent des préfixes dans le JSON
(ex: pos_tolerance, pos_mapping) mais pas dans le modèle Python interne.

Utilisation :
    - to_internal_key(json_key): Convertit une clé JSON en clé interne (ex: 'pos_tolerance' -> 'tolerance')
    - to_json_key(internal_key): Convertit une clé interne en clé JSON (ex: 'tolerance' -> 'pos_tolerance')
"""

from typing import Dict

# Mapping bidirectionnel entre les noms INTERNES (sans préfixe) et les noms JSON (avec préfixe pos_)
# Format: {clé_interne: clé_json}
POS_FIELD_MAPPING: Dict[str, str] = {
    # Champs de direction
    "identification_dir_left": "pos_identification_dir_left",
    "identification_dir_top": "pos_identification_dir_top",
    "identification_dir_both": "pos_identification_dir_both",
    "exercise_dir_left": "pos_exercise_dir_left",
    "exercise_dir_top": "pos_exercise_dir_top",
    "exercise_dir_both": "pos_exercise_dir_both",
    "question_dir_left": "pos_question_dir_left",
    "question_dir_top": "pos_question_dir_top",
    "question_dir_both": "pos_question_dir_both",
    "choice_dir_left": "pos_choice_dir_left",
    "choice_dir_top": "pos_choice_dir_top",
    "choice_dir_both": "pos_choice_dir_both",
    
    # Champs "new" (ajouts fantômes / seconde chance)
    "choice_joker_always": "pos_choice_joker_always",
    "choice_joker_never": "pos_choice_joker_never",
    "exercise_new_never": "pos_exercise_new_never",
    "exercise_new_always": "pos_exercise_new_always",
    "exercise_new_sometimes": "pos_exercise_new_sometimes",
    "question_new_never": "pos_question_new_never",
    "question_new_always": "pos_question_new_always",
    "question_new_sometimes": "pos_question_new_sometimes",
    "choice_new_never": "pos_choice_new_never",
    "choice_new_always": "pos_choice_new_always",
    "choice_new_sometimes": "pos_choice_new_sometimes",
    
    # Champs "checked"
    "choice_checked_never": "pos_choice_checked_never",
    "choice_checked_always": "pos_choice_checked_always",
    "choice_checked_sometimes": "pos_choice_checked_sometimes",
    
    # Champs "order" (ordre aléatoire)
    "exercise_order_never": "pos_exercise_order_never",
    "exercise_order_always": "pos_exercise_order_always",
    "exercise_order_sometimes": "pos_exercise_order_sometimes",
    "question_order_never": "pos_question_order_never",
    "question_order_always": "pos_question_order_always",
    "question_order_sometimes": "pos_question_order_sometimes",
    "choice_order_never": "pos_choice_order_never",
    "choice_order_always": "pos_choice_order_always",
    "choice_order_sometimes": "pos_choice_order_sometimes",
}

# Mapping inverse pour une recherche rapide (clé JSON -> clé interne)
_JSON_TO_INTERNAL_MAPPING: Dict[str, str] = {
    json_key: internal_key for internal_key, json_key in POS_FIELD_MAPPING.items()
}

def to_internal_key(json_key: str) -> str:
    """Convertit une clé JSON (ex: 'pos_tolerance') en clé interne (ex: 'tolerance')."""
    return _JSON_TO_INTERNAL_MAPPING.get(json_key, json_key)

def to_json_key(internal_key: str) -> str:
    """Convertit une clé interne (ex: 'tolerance') en clé JSON (ex: 'pos_tolerance')."""
    return POS_FIELD_MAPPING.get(internal_key, internal_key)

def get_all_json_keys() -> list[str]:
    """Retourne la liste de toutes les clés JSON avec préfixe."""
    return list(POS_FIELD_MAPPING.values())

def get_all_internal_keys() -> list[str]:
    """Retourne la liste de toutes les clés internes sans préfixe."""
    return list(POS_FIELD_MAPPING.keys())
