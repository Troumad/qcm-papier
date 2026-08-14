# qcm-papier — Générateur/Correcteur de QCM papier (Python + GTK 4)

Portage en Python du générateur/correcteur de QCM papier originellement écrit en
HTML5 + JavaScript (Université Lyon 1, auteur original : Florent Ouchet).

## Fonctionnalités

- **Édition de la structure du QCM** : exercices, questions, choix, barèmes
  (somme, biais négatif, seuil de validation, gain progressif, choix multiples).
- **Génération des variantes** : placement aléatoire reproductible des
  exercices/questions/choix, ajout d'éléments « fantômes » et de « seconde chance »,
  repères d'alignement, code-barres Code 39, numéro identifiant étudiant.
- **Génération PDF du sujet** (ReportLab).
- **Correction automatique** des copies scannées (PDF/images) :
  alignement par repères, lecture du code-barres, lecture du numéro étudiant,
  détection des cases cochées, calcul des notes.
- **Correction manuelle** des questions à réponse libre.
- **Export Scodoc** des notes (fichier `.xls`), levée d'anonymat via la table
  des étudiants.
- **Sauvegarde/chargement du projet** au format JSON (compatible avec le format
  du code original).

## Architecture

```
qcm_papier/
├── model.py          # Structure du QCM (exercices/questions/choix), paramètres
├── random_gen.py     # Génération pseudo-aléatoire reproductible + insertions
├── code39.py         # Table Code 39
├── pdf_writer.py     # Génération du PDF sujet (ReportLab)
├── scanner.py        # Lecture des copies : alignement, code-barres, cases
├── marking.py        # Calcul des notes / barèmes
├── scodoc.py         # Import table étudiants + export notes Scodoc
├── project.py        # Persistance JSON du projet
├── cli.py            # Interface en ligne de commande
└── ui/
    ├── __init__.py
    ├── app.py        # Fenêtre principale GTK 4
    ├── editor.py     # Éditeur de structure
    ├── generate.py   # Onglet génération
    └── marking_ui.py # Onglet correction
```

## Dépendances

- Python ≥ 3.10
- ReportLab (génération PDF)
- openpyxl (fichiers Excel Scodoc)
- Pillow (images scannées)
- PyMuPDF (lecture des PDF scannés)
- PyGObject + GTK 4 (interface graphique, paquets système
  `gir1.2-gtk-4.0` + `python3-gi`)

## Installation

```bash
# Paquets système (Debian/Ubuntu) pour GTK 4
sudo apt-get install python3-gi gir1.2-gtk-4.0

# Dépendances Python
pip install -e .
```

## Utilisation

### Interface graphique GTK

```bash
python3 -m qcm_papier
```

### Ligne de commande

```bash
# Générer le sujet PDF à partir d'un projet
qcm-papier generate --project qcm.json --output sujet.pdf

# Corriger un lot de copies
qcm-papier correct --project qcm.json --copies scans/ --output notes.xls
```

## Tests

```bash
pytest -q
```

## Origine

Code original : https://troumad.org/OOo/QCM/index.html — auteur Florent Ouchet.
Ce portage Python préserve la logique métier (notamment l'algorithme
pseudo-aléatoire reproductible et le format de projet JSON) afin de rester
compatible avec les projets existants.
