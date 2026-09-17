# qcm-papier — Repères techniques (Python, GTK 4 et interface web)

Le guide principal d'installation et d'utilisation est dans [README.md](README.md).

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
  des étudiants (Excel ou API ScoDoc dans l'interface web).
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
├── scodoc_api.py     # Client HTTP ScoDoc et conversion des étudiants
├── scodoc_config.py  # Compte enregistré et mot de passe dans le trousseau
├── project.py        # Persistance JSON du projet
├── cli.py            # Interface en ligne de commande
├── editing.py        # Règles d'édition utilisées par l'interface web
├── web/
│   ├── server.py     # API FastAPI locale et fichiers statiques
│   ├── session.py    # Projet, correction en arrière-plan et sauvegardes ZIP
│   └── static/       # HTML, CSS et JavaScript, sans compilation
└── ui/
    ├── __init__.py
    ├── app.py        # Fenêtre principale GTK 4
    └── editor.py     # Éditeur de structure
```

## Dépendances

- Python ≥ 3.10
- ReportLab (génération PDF)
- openpyxl (fichiers Excel Scodoc)
- Pillow (images scannées)
- PyMuPDF (lecture des PDF scannés)
- numpy (calculs sur les images scannées : repères, cases, recherche globale)
- FastAPI, Uvicorn, python-multipart et keyring (option `.[web]`)
- PyGObject + GTK 4 (interface graphique, paquets système
  `gir1.2-gtk-4.0` + `python3-gi`)

## Installation

```bash
# Paquets système (Debian/Ubuntu) pour GTK 4
sudo apt-get install python3-gi gir1.2-gtk-4.0

# Dépendances Python (uv crée .venv et installe les versions de uv.lock)
uv sync
```

Sans [uv](https://docs.astral.sh/uv/) : `python3 -m venv .venv`, activation de
l'environnement, puis `pip install -e .`.

## Utilisation

### Interface web locale

```bash
uv sync --extra web
uv run qcm-papier serve
```

Le serveur sert les fichiers de `web/static/` et écoute sur la boucle locale.
Une instance correspond à une session de travail ; plusieurs onglets du même
serveur partagent le projet et la correction. Les téléchargements et archives
permettent de conserver le travail après l'arrêt du serveur.

Le suivi des modifications distingue l'empreinte du projet et la révision de la
correction. Une sauvegarde confirme uniquement l'instantané effectivement exporté.
`web/static/persistence.js` gère les sauvegardes et confirmations, et `review.js`
les filtres et le bilan des copies. Les archives de reprise incluent les copies
en attente et les réglages de détection, avec lecture des anciennes archives.

Le lanceur Rust est décrit dans [src-tauri/README.md](src-tauri/README.md).

### Interface graphique GTK

```bash
uv run python -m qcm_papier
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
uv sync --extra dev
uv run pytest -q
node --test tests/js/*.cjs
```

Les tests Python couvrent l'édition, l'API, la correction et la sauvegarde.
Les tests JavaScript utilisent Node.js 24 uniquement pour le développement ;
Node.js n'est pas nécessaire pour utiliser l'application.

Pour vérifier le lanceur Tauri sans créer d'installateur :

```bash
cargo check --locked --manifest-path src-tauri/Cargo.toml
```

## Origine

Code original : https://troumad.org/OOo/QCM/index.html — auteur Florent Ouchet.
Ce portage Python préserve la logique métier (notamment l'algorithme
pseudo-aléatoire reproductible et le format de projet JSON) afin de rester
compatible avec les projets existants.
