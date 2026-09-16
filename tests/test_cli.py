"""Parcours CLI avec vrais fichiers de projet et PDF temporaires."""

import pymupdf
import pytest

from qcm_papier import cli, project


@pytest.mark.parametrize("command", ["open", "check"])
def test_resume_projet(command, project_path, capsys):
    assert cli.main([command, "-p", project_path]) == 0
    assert "Questions : 1" in capsys.readouterr().out


def test_generation_pdf_et_sauvegarde(project_path, tmp_path):
    output = tmp_path / "sujet"
    saved = tmp_path / "avec_variantes.json"
    assert cli.main(["generate", "-p", project_path, "-o", str(output), "--save-project", str(saved)]) == 0
    with pymupdf.open(str(output) + ".pdf") as doc:
        assert len(doc) == 1
        assert "Question" in doc[0].get_text()
    assert project.load_project(str(saved)).variants.variant(42) is not None
    assert project.load_project(project_path).variants.variant(42) is None


def test_variantes_puis_pdf(project_path, tmp_path):
    assert cli.main(["variants", "-p", project_path]) == 0
    output = tmp_path / "sujet.pdf"
    assert cli.main(["pdf", "-p", project_path, "-o", str(output)]) == 0
    with pymupdf.open(output) as doc:
        assert len(doc) == 1


def test_pdf_sans_variantes_refuse(project_path, tmp_path):
    output = tmp_path / "absent.pdf"
    with pytest.raises(SystemExit, match="variantes"):
        cli.main(["pdf", "-p", project_path, "-o", str(output)])
    assert not output.exists()


def test_projet_absent(tmp_path):
    with pytest.raises(SystemExit, match="Projet introuvable"):
        cli.main(["check", "-p", str(tmp_path / "absent.json")])


def test_correction_sans_copies(project_path, tmp_path):
    cli.main(["variants", "-p", project_path])
    empty = tmp_path / "copies"
    empty.mkdir()
    with pytest.raises(SystemExit, match="Aucune copie"):
        cli.main(["correct", "-p", project_path, "-c", str(empty)])


def test_point_entree_module(project_path, capsys):
    from qcm_papier.__main__ import main

    assert main(["check", "-p", project_path]) == 0
    assert "Questions : 1" in capsys.readouterr().out
