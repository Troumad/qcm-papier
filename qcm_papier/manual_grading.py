"""Notation des questions à réponse libre, commune aux interfaces web et GTK.

Le scanner repère le cadre de réponse de chaque question « manuelle » (mark
avec largeur ``w`` et hauteur ``h``) ; le correcteur y saisit les points, qui
sont stockés dans ``mark["value"]`` puis pris en compte par ``score_page``.
"""

from __future__ import annotations

from typing import Any

from .marking import score_page
from .model import Exercise, Project, Question
from .scanner import ScannedPage


def open_questions(project: Project) -> list[tuple[int, int, Exercise, Question]]:
    """Questions à réponse libre du projet : (indice exercice, indice question, exercice, question)."""
    return [
        (e, q, exercise, question)
        for e, exercise in enumerate(project.structure)
        for q, question in enumerate(exercise.questions)
        if question.manual
    ]


def manual_question(project: Project, e: int, q: int) -> Question:
    question = project.structure[e].questions[q]
    if not question.manual:
        raise ValueError("Cette question n'est pas à réponse libre.")
    return question


def answer_mark(page: ScannedPage, e: int, q: int) -> dict | None:
    """Mark du cadre de réponse de la question sur la page, si la page est alignée."""
    if page.matrix_inv is None:
        return None
    for mark in page.marks:
        if mark.get("e") == e and mark.get("q") == q and mark.get("w") is not None:
            return mark
    return None


def crop_answer(page: ScannedPage, e: int, q: int, margin_mm: float = 3.0):
    """Image Pillow du cadre de réponse découpé dans le scan (avec une petite marge)."""
    mark = answer_mark(page, e, q)
    m = page.matrix_inv
    if mark is None or m is None or page.img is None:
        raise ValueError("Cadre de réponse introuvable sur cette page.")
    x0, y0 = mark["x"] - margin_mm, mark["y"] - margin_mm
    x1, y1 = mark["x"] + mark["w"] + margin_mm, mark["y"] + mark["h"] + margin_mm
    corners = [m.apply(x, y) for x in (x0, x1) for y in (y0, y1)]
    img = page.img.img
    box = (
        max(0, int(min(cx for cx, _ in corners))),
        max(0, int(min(cy for _, cy in corners))),
        min(img.width, int(max(cx for cx, _ in corners)) + 1),
        min(img.height, int(max(cy for _, cy in corners)) + 1),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("Cadre de réponse hors de la page.")
    return img.crop(box)


def parse_points(text: str) -> float | None:
    """Points tapés au clavier (virgule ou point décimal) ; texte vide → None (non noté)."""
    text = text.strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise ValueError("Points invalides.") from None


def set_answer_value(project: Project, page: ScannedPage, e: int, q: int, value: Any) -> None:
    """Points d'une réponse libre (None efface la saisie), bornés par le gain ; recalcule la note."""
    question = manual_question(project, e, q)
    if value is not None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError("Points invalides.") from None
        if not 0 <= value <= float(question.gain):
            raise ValueError(f"Les points doivent être compris entre 0 et {question.gain:g}.")
    mark = answer_mark(page, e, q)
    if mark is None:
        raise ValueError("Cadre de réponse introuvable sur cette page.")
    mark["value"] = value
    score = score_page(project, page.marks, variant_id=page.variant_id, student_id=page.student_id)
    page.value, page.total, page.complete = score.value, score.total, score.complete
