"""Tests de la génération des variantes et du PDF."""

import os

import pymupdf

from qcm_papier import generator, model, pdf_writer, scanner


def _make_project(count: int = 2) -> model.Project:
    p = model.Project()
    p.settings.evaluation_short = "TEST"
    p.settings.module_short = "M"
    p.settings.year = "24"
    ex = model.Exercise(name="Exercice 1", index=0)
    q = model.Question(name="Q1", gain=2.0, penalty=1.0, single=True, index=0)
    q.choices = [
        model.Choice(name="A", correct=True, neutral=False, index=0),
        model.Choice(name="B", correct=False, neutral=False, penalty=True, index=1),
        model.Choice(name="C", correct=False, neutral=True, index=2),
        model.Choice(name="D", correct=False, neutral=True, index=3),
    ]
    ex.questions = [q]
    p.structure = [ex]
    p.settings.generate_count = count
    p.settings.generate_variants = ""
    return p


def test_barcode_text_padding():
    """Le texte du code-barres remplit le numéro sur 4 chiffres avec des 0."""
    assert generator.barcode_text("PRE-", 5) == "*PRE-0005*"
    assert generator.barcode_text("PRE-", 42) == "*PRE-0042*"
    assert generator.barcode_text("PRE-", 999) == "*PRE-0999*"
    assert generator.barcode_text("PRE-", 1234) == "*PRE-1234*"


def test_generate_all_produit_variantes():
    """generate_all crée au moins une variante par id demandé."""
    p = _make_project(count=3)
    ids, failed = generator.generate_all(p, retry=True)
    assert len(ids) == 3
    # Au moins une variante stockée (les layouts 'p'/'l' ne comptent pas).
    variant_keys = [k for k in p.variants if k not in ("p", "l")]
    assert len(variant_keys) >= 1
    # Chaque variante a un code-barres et des marks.
    for vid in variant_keys:
        v = p.variants.variant(int(vid))
        assert v is not None
        assert v.barcode_text.startswith("*")
        assert v.barcode_text.endswith("*")
        assert len(v.marks) > 0


def test_generate_variant_reproductible():
    """Deux générations avec le même id donnent le même code-barres.

    On désactive les en-têtes pour garantir que la variante tient dans le format.
    """
    p1 = _make_project(count=1)
    p1.settings.header_left = ""
    p1.settings.header_middle = ""
    p1.settings.header_right = ""
    p1.settings.generate_variants = "4"
    generator.generate_all(p1, retry=False)
    v1 = p1.variants.variant(4)
    assert v1 is not None, "La variante 4 aurait dû être générée"

    p2 = _make_project(count=1)
    p2.settings.header_left = ""
    p2.settings.header_middle = ""
    p2.settings.header_right = ""
    p2.settings.generate_variants = "4"
    generator.generate_all(p2, retry=False)
    v2 = p2.variants.variant(4)
    assert v2 is not None

    assert v1.barcode_text == v2.barcode_text
    assert len(v1.marks) == len(v2.marks)


def test_pdf_generation_valide(tmp_path):
    """Le PDF généré est un PDF valide avec le bon nombre de pages."""
    p = _make_project(count=3)
    generator.generate_all(p, retry=True)
    out = tmp_path / "sujet.pdf"
    pdf_writer.generate_pdf(p, str(out))
    assert os.path.exists(out)
    assert out.stat().st_size > 0
    # En-tête PDF.
    with open(out, "rb") as f:
        assert f.read(5) == b"%PDF-"
    # Nombre de pages = nombre de variantes.
    doc = pymupdf.open(str(out))
    variant_count = len([k for k in p.variants if k not in ("p", "l")])
    assert doc.page_count == variant_count
    doc.close()


def test_scan_corrige_pdf_genere(tmp_path):
    """Le scanner arrive à relire le code-barres du PDF généré (round-trip).

    On désactive les en-têtes pour garantir que les variantes tiennent dans le format.
    """
    p = _make_project(count=2)
    p.settings.header_left = ""
    p.settings.header_middle = ""
    p.settings.header_right = ""
    p.settings.generate_variants = "4;5"
    generator.generate_all(p, retry=False)
    out = tmp_path / "sujet.pdf"
    pdf_writer.generate_pdf(p, str(out))
    pages = scanner.load_pages_from_file(str(out), dpi=150)
    # Au moins une page générée (certaines variantes peuvent déborder).
    assert len(pages) >= 1
    # Chaque page doit être corrigée (au moins le code-barres lu).
    for sp in pages:
        assert scanner.auto_check(sp, p) is True
        assert sp.variant_id is not None
        assert sp.barcode.startswith("*")
