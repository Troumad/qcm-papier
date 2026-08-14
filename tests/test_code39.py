"""Tests du code-barres Code 39."""

from qcm_papier import code39


def test_code39_table_complete():
    """Tous les caractères usuels sont présents (lettre, chiffre, ponctuation)."""
    for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -$.%/+*":
        assert c in code39.CODE39, f"Caractère {c!r} manquant"
    # Chaque motif fait 9 caractères '0'/'1'.
    for char, pattern in code39.CODE39.items():
        assert len(pattern) == 9
        assert all(c in "01" for c in pattern)


def test_code39_width():
    """Largeur = 16 * résolution * longueur du texte."""
    text = "*TEST*"
    res = 0.5
    w = code39.code39_width(text, res)
    assert w == 16 * res * len(text)
    assert w == 16 * 0.5 * 6  # = 48.0


def test_code39_pattern_barres():
    """Le motif '*' (010010100) produit des barres pleines/fines alternées."""
    bars = code39.code39_pattern("*", resolution=0.5)
    # '*' = 010010100 → 9 barres + 1 séparateur = 10 entrées.
    assert len(bars) == 10
    # Les barres pleines sont aux indices pairs (j % 2 == 0) avec la bonne largeur.
    # Vérifier que les barres pleines existent.
    filled = [b for b in bars if b[1]]
    assert len(filled) > 0
    # Largeur d'une barre pleine = 3 * résolution.
    for width, is_bar in bars[:9]:
        if is_bar:
            # largeur pleine ou fine selon le bit
            assert width in (0.5, 1.5)  # 1*res ou 3*res


def test_code39_asterisk_pattern():
    """Le caractère '*' a le motif officiel Code 39."""
    assert code39.CODE39["*"] == "010010100"
    assert code39.CODE39["A"] == "100001001"
    assert code39.CODE39["0"] == "000110100"
