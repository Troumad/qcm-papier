"""Projets synthétiques sans données étudiantes réelles."""

import random

import pytest

from qcm_papier import model, project


@pytest.fixture
def project_path(tmp_path):
    value = model.Project()
    value.settings.generate_variants = "42"
    value.settings.generate_count = 1
    value.structure = [
        model.Exercise(
            name="Exercice",
            index=0,
            questions=[
                model.Question(
                    name="Question",
                    index=0,
                    choices=[
                        model.Choice(name="Oui", index=0, correct=True, neutral=False),
                        model.Choice(name="Non", index=1, penalty=True, neutral=False),
                    ],
                )
            ],
        )
    ]
    path = tmp_path / "projet.json"
    project.save_project(value, str(path))
    return str(path)


@pytest.fixture(autouse=True)
def reproducible_random():
    """Reproduire les tirages des sujets, sans modifier l'état du test suivant."""
    state = random.getstate()
    random.seed(0)
    yield
    random.setstate(state)
