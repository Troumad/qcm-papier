"""Conversion Markdown → balisage Pango (aide GTK), sans dépendre de GTK."""

import pathlib
import xml.etree.ElementTree as ET

from qcm_papier.markdown_pango import render


def well_formed(markup: str) -> ET.Element:
    """Pango refuse un balisage mal formé : on le vérifie comme du XML."""
    return ET.fromstring(f"<markup>{markup}</markup>")


def test_emphase_code_et_liens():
    markup = render("Un **gras**, une *italique*, du `code` et [un lien](https://example.org).")
    assert "<b>gras</b>" in markup
    assert "<i>italique</i>" in markup
    assert "<tt>code</tt>" in markup
    assert "un lien" in markup and "https://example.org" in markup
    well_formed(markup)


def test_texte_echappe():
    markup = render("a < b & c > d **x < y**")
    assert "a &lt; b &amp; c &gt; d" in markup
    assert "<b>x &lt; y</b>" in markup
    well_formed(markup)


def test_listes_titres_et_paragraphes():
    markup = render("# Titre\n\nUne phrase\nsur deux lignes.\n\n- 1 pt : dérivée\n- *0,5 pt* sinon\n\n1. un\n2. deux")
    lines = markup.split("\n")
    assert "Titre" in lines[0] and "<b>" in lines[0]
    assert "Une phrase sur deux lignes." in markup
    assert "• 1 pt : dérivée" in markup
    assert "• <i>0,5 pt</i> sinon" in markup
    assert "1. un" in markup and "2. deux" in markup
    well_formed(markup)


def test_bloc_de_code_non_interprete():
    markup = render("```\nx = a * b * c\n**pas gras**\n```")
    assert "<tt>" in markup
    assert "x = a * b * c" in markup
    assert "**pas gras**" in markup
    well_formed(markup)


def test_citation_et_ligne_horizontale():
    markup = render("> attention\n\n---\n\nfin")
    assert "attention" in markup and "<i>" in markup
    assert "───" in markup
    well_formed(markup)


def test_le_readme_entier_reste_bien_forme():
    readme = pathlib.Path(__file__).resolve().parent.parent / "README.md"
    well_formed(render(readme.read_text(encoding="utf-8")))
