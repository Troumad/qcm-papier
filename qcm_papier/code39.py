"""Table de codage Code 39 (issue du code original, wikipedia Code 39).

Chaque caractère est encodé sur 9 bits : alternance de barres fines (0) et
épaisses (1). Le bit de poids faible correspond à la première barre. Voir
``code39`` dans index.html (lignes ~2061-2101).
"""

from __future__ import annotations

# Caractère -> motif de 9 caractères '0'/'1' (barres).
CODE39: dict[str, str] = {
    "A": "100001001", "B": "001001001", "C": "101001000",
    "D": "000011001", "E": "100011000", "F": "001011000",
    "G": "000001101", "H": "100001100", "I": "001001100",
    "J": "000011100", "K": "100000011", "L": "001000011",
    "M": "101000010", "N": "000010011", "O": "100010010",
    "P": "001010010", "Q": "000000111", "R": "100000110",
    "S": "001000110", "T": "000010110", "U": "110000001",
    "V": "011000001", "W": "111000000", "X": "010010001",
    "Y": "110010000", "Z": "011010000", "0": "000110100",
    "1": "100100001", "2": "001100001", "3": "101100000",
    "4": "000110001", "5": "100110000", "6": "001110000",
    "7": "000100101", "8": "100100100", "9": "001100100",
    " ": "011000100", "-": "010000101", "$": "010101000",
    "%": "000101010", ".": "110000100", "/": "010100010",
    "+": "010001010", "*": "010010100",
}


def code39_pattern(text: str, resolution: float = 0.5) -> list[tuple[float, bool]]:
    """Renvoie la séquence de barres (largeur_mm, est_pleine) d'un texte Code 39.

    Le texte doit inclure les caractères de début/fin ``*``. Chaque caractère
    produit 9 barres ; une barre pleine ('1') est large ``3*resolution``, une
    barre fine ('0') vaut ``resolution``. Un espace de largeur ``resolution``
    sépare deux caractères (correspond à ``bar_left += barcode_resolution``
    dans le code original).
    """
    bars: list[tuple[float, bool]] = []
    for char in text:
        pattern = CODE39.get(char)
        if pattern is None:
            pattern = CODE39[" "]
        for i, bit in enumerate(pattern):
            width = resolution * (3 if bit == "1" else 1)
            # Les barres paires (i % 2 == 0) sont pleines (noires).
            is_bar = (i % 2 == 0)
            bars.append((width, is_bar))
        # Espace inter-caractère.
        bars.append((resolution, False))
    return bars


def code39_width(text: str, resolution: float = 0.5) -> float:
    """Largeur totale (mm) d'un code-barres Code 39 (texte + inter-espaces).

    Reproduit ``16 * barcode_resolution * barcode_text.length`` du code original
    (chaque caractère occupe 16 unités de résolution : 9 barres + 1 séparateur,
    avec une moyenne pondérée par les barres épaisses → 16 en pratique).
    """
    return 16 * resolution * len(text)
