# qcm-papier — Générateur/Correcteur de QCM papier (Python + GTK 3)

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
    ├── app.py        # Fenêtre principale GTK 3
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
- PyGObject + GTK 3 (interface graphique, paquets système
  `gir1.2-gtk-3.0` + `python3-gi`)

## Installation

### Prérequis

Python ≥ 3.10 doit être installé.

### Debian / Ubuntu (apt)

```bash
# Paquets système pour GTK 3
sudo apt install python3-gi gir1.2-gtk-3.0

# Dépendances Python (depuis les dépôts ou PyPI)
sudo apt install python3-reportlab python3-openpyxl python3-pil python3-pymupdf python3-pytest
# ou, pour une version à jour :
pip install -e .
```

### Mageia (urpmi)

```bash
# Paquets système : GTK 3 + bindings Python + dépendances
sudo urpmi python3-gobject3 lib64gtk-gir3.0 \
            python3-reportlab python3-openpyxl python3-pillow python3-pymupdf \
            python3-pytest
```

> Si un paquet manque (Mageia Cauldron), on peut le chercher avec `urpmq` :
> `urpmq -y pymupdf` ou `urpmf -i pymupdf`.
>
> En alternative, les dépendances Python peuvent être installées via `pip` :
> `pip install --user reportlab openpyxl Pillow PyMuPDF pytest`.

### Autres distributions

Adaptez les noms de paquets ; les bibliothèques Python nécessaires sont :
`reportlab`, `openpyxl`, `Pillow`, `PyMuPDF` (+ `PyGObject`/GTK 3 pour l'interface
graphique, fourni par le paquet système `gir1.2-gtk-3.0` sous Debian/Ubuntu ou
`python3-gobject3` + `lib64gtk-gir3.0` sous Mageia).

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
