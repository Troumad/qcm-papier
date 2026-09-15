# Application de bureau QCM-Papier (Tauri)

Tauri sert uniquement d'enveloppe : au démarrage, il lance le serveur Python
(`qcm-papier serve`) sur un port libre de la machine, attend qu'il réponde,
puis ouvre une fenêtre sur l'interface web. Toute la logique reste en Python ;
ce dossier ne contient qu'une centaine de lignes de Rust.

## Prérequis (pour compiler)

- Rust (`rustup`) et la CLI Tauri : `cargo install tauri-cli --version "^2"`
- Les dépendances système de Tauri : <https://v2.tauri.app/start/prerequisites/>
- Le paquet Python avec l'interface web : `pip install -e ".[web]"`

Les utilisateurs de l'application empaquetée n'ont besoin d'aucun de ces outils.

## Lancer en développement

```bash
cd src-tauri
cargo tauri dev
```

Le serveur est lancé avec `python3 -m qcm_papier serve` (`python` sous
Windows). Pour utiliser un autre interpréteur, par exemple celui d'un
environnement virtuel :

```bash
QCM_PAPIER_PYTHON=../.venv/bin/python cargo tauri dev
```

## Empaqueter

```bash
cd src-tauri
cargo tauri build
```

L'application produite lance encore Python installé sur la machine. Pour une
application totalement autonome, il reste à construire le serveur en un seul
exécutable (par exemple avec PyInstaller) et à le désigner avec la variable
`QCM_PAPIER_SERVER`, ou à l'intégrer comme *sidecar* Tauri (`bundle.externalBin`).
C'est l'étape suivante, à valider sur chaque système (Linux, macOS, Windows).

## Icônes

Générées depuis une image 1024×1024 avec `cargo tauri icon image.png -o icons`.
