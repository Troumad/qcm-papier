"""Rendu des pages d'un PDF en images, pour l'aperçu intégré."""

import pytest

from qcm_papier import editing, generator, pdf_preview, pdf_writer
from qcm_papier.model import Project

pytest.importorskip("pymupdf")


@pytest.fixture(scope="module")
def pdf_bytes():
    project = Project()
    editing.add_exercise(project)
    editing.apply_info_defaults(project.settings)
    project.settings.generate_count = 2
    generator.generate_all(project, retry=True)
    return pdf_writer.generate_pdf(project)


def test_page_sizes_en_points(pdf_bytes):
    sizes = pdf_preview.page_sizes(pdf_bytes)
    assert len(sizes) >= 1
    width, height = sizes[0]
    assert width > 0 and height > 0


def test_render_page_renvoie_un_png(pdf_bytes):
    image = pdf_preview.render_page(pdf_bytes, 0, dpi=72)
    assert image.startswith(b"\x89PNG\r\n\x1a\n")


def test_un_dpi_plus_grand_donne_une_image_plus_grande(pdf_bytes):
    assert len(pdf_preview.render_page(pdf_bytes, 0, dpi=150)) > len(pdf_preview.render_page(pdf_bytes, 0, dpi=48))


def test_dpi_hors_bornes_refuse(pdf_bytes):
    for dpi in (0, 12, 1200):
        with pytest.raises(ValueError):
            pdf_preview.render_page(pdf_bytes, 0, dpi=dpi)


def test_page_inexistante_refuse(pdf_bytes):
    for index in (-1, len(pdf_preview.page_sizes(pdf_bytes))):
        with pytest.raises(IndexError):
            pdf_preview.render_page(pdf_bytes, index, dpi=72)


def test_document_illisible_refuse():
    with pytest.raises(ValueError):
        pdf_preview.page_sizes(b"ceci n'est pas un PDF")
