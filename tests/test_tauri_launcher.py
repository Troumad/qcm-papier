"""Parcours du lanceur sans téléchargement, installation système ni fenêtre."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="Le lanceur nécessite Bash")

MOCK_TOOLS = r"""
uname() { printf 'Linux\n'; }
pkg-config() { return 0; }
cc() { return 0; }
uv() { printf '%s\n' "$@" > "$LAUNCH_LOG/uv"; }
cargo() {
    if [[ "$1" == --version ]]; then printf 'cargo test\n'; return; fi
    printf '%s\n' "$@" > "$LAUNCH_LOG/cargo"
    printf '%s\n' "$QCM_PAPIER_PROJECT" > "$LAUNCH_LOG/project"
    printf '%s\n' "$QCM_PAPIER_PYTHON" > "$LAUNCH_LOG/python"
    printf '%s\n' "${QCM_PAPIER_SERVER-unset}" > "$LAUNCH_LOG/server"
    printf '%s\n' "$UV_PROJECT_ENVIRONMENT" > "$LAUNCH_LOG/venv"
}
# Intercepter aussi exec pour ne jamais démarrer le vrai binaire Cargo.
exec() { "$@"; }
export -f uname pkg-config cc uv cargo exec
bash "$@"
"""


def launch(tmp_path, *args):
    env = {
        **os.environ,
        "LAUNCH_LOG": str(tmp_path),
        "QCM_PAPIER_PROJECT": "/ancien/projet.json",
        "QCM_PAPIER_SERVER": "/ancien/serveur",
    }
    return subprocess.run(
        [BASH, "-c", MOCK_TOOLS, "test", str(ROOT / "lancer-tauri.sh"), *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_lanceur_transmet_le_projet_et_isole_python(tmp_path):
    project = tmp_path / "Mon sujet corrigé.json"
    project.write_text("{}")
    result = launch(tmp_path, "-p", project.name)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "project").read_text().strip() == str(project.resolve())
    assert (tmp_path / "uv").read_text().splitlines() == ["sync", "--locked", "--extra", "web"]
    assert (tmp_path / "venv").read_text().strip() == str(ROOT / ".venv-tauri")
    assert (tmp_path / "python").read_text().strip() == str(ROOT / ".venv-tauri/bin/python")
    assert (tmp_path / "server").read_text().strip() == "unset"
    assert (tmp_path / "cargo").read_text().splitlines() == [
        "run",
        "--locked",
        "--manifest-path",
        str(ROOT / "src-tauri/Cargo.toml"),
    ]


def test_lanceur_sans_projet_oublie_ancien_environnement(tmp_path):
    result = launch(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "project").read_text().strip()


@pytest.mark.parametrize("args", [("--help",), ("-p",), ("-p", "absent.json"), ("--inconnu",)])
def test_lanceur_aide_et_erreurs_sans_installation(tmp_path, args):
    result = launch(tmp_path, *args)
    assert (result.returncode == 0) == (args == ("--help",))
    assert not (tmp_path / "uv").exists()
    assert not (tmp_path / "cargo").exists()
