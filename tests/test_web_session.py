"""Session de l'interface web : correction, reprise, visionneuse."""

import os
import time

import pytest

from qcm_papier.web.session import Session

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = os.path.join(REPO, "math", "2026", "correction3.pdf")
PROJECT = os.path.join(REPO, "math", "2026", "OML1_bis.json")


def _wait(session: Session, timeout: float = 120.0) -> None:
    start = time.monotonic()
    while session.job.running:
        assert time.monotonic() - start < timeout, "tâche trop longue"
        time.sleep(0.05)
    assert session.job.error == ""


@pytest.fixture
def corrected(tmp_path):
    if not (os.path.exists(PDF) and os.path.exists(PROJECT)):
        pytest.skip("fichiers absents")
    session = Session(work_dir=str(tmp_path))
    session.load_project(PROJECT)
    with open(PDF, "rb") as f:
        session.add_copy("correction3.pdf", f.read())
    session.start_correction()
    _wait(session)
    return session


def test_correction_en_arriere_plan(corrected):
    results = corrected.results()
    assert [r["variant"] for r in results] == [497, 3152, 1240, 1680, 1752, 2672]
    assert [r["note"] for r in results] == [1.5, 1.5, 1.0, 1.5, 1.0, 3.0]
    # Page 4 : note calculée mais n° étudiant illisible, signalé dans le statut.
    assert results[3]["status"] == "N° étudiant non trouvé"
    copy = corrected.copies[0]
    assert (copy.n_ok, copy.n_err, copy.n_pages, copy.checked) == (6, 0, 6, False)
    assert corrected.notes


def test_sauvegarde_puis_reprise_identique(corrected, tmp_path):
    before = corrected.results()
    archive = corrected.save_state_zip()
    other = Session(work_dir=str(tmp_path / "autre"))
    os.makedirs(other.work_dir)
    other.start_load_state_zip(archive)
    _wait(other)
    assert other.variant_ids() == corrected.variant_ids()
    after = other.results()
    keys = ("variant", "student_id", "note", "status")
    assert [{k: r[k] for k in keys} for r in after] == [{k: r[k] for k in keys} for r in before]


def test_numero_etudiant_manuel_et_images(corrected):
    corrected.set_student_id(0, "p1234567")
    assert corrected.page_info(0)["student_id"] == "p1234567"
    assert corrected.page_image(0).startswith(b"\x89PNG")
    assert corrected.page_image(0, raw=True).startswith(b"\x89PNG")


def test_zip_refuse_un_chemin_hors_dossier(tmp_path):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(ValueError):
        Session(work_dir=str(tmp_path)).start_load_state_zip(buf.getvalue())
