# Application de bureau QCM-Papier (Tauri)

Tauri lance le serveur Python sur un port libre de la boucle locale, attend
son démarrage et affiche l'interface web dans une fenêtre. La correction,
la génération des PDF et les projets restent gérés par Python.

**État actuel : lanceur de développement.** Python et le paquet `qcm-papier`
avec l'option `web` doivent être installés sur la machine, y compris pour
utiliser une application construite avec `cargo tauri build`.
La distribution autonome et les essais Windows/Linux restent à réaliser.

## Prérequis

- Python 3.10 ou plus récent.
- Rust et Cargo ; CLI Tauri 2 : `cargo install tauri-cli --version "^2" --locked`.
- Les [dépendances système Tauri](https://v2.tauri.app/start/prerequisites/)
  correspondant à votre système (outils Xcode sur macOS, WebView2 et outils
  de compilation C++ sur Windows, WebKitGTK et bibliothèques de développement
  sur Linux).

Aucun outil de compilation JavaScript n'est nécessaire : les fichiers HTML,
CSS et JavaScript sont servis directement par FastAPI.

## Lancer en développement

Depuis la racine du dépôt, sur macOS ou Linux :

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[web]"
export QCM_PAPIER_PYTHON="$PWD/.venv/bin/python"
cd src-tauri
cargo tauri dev
```

Sous Windows PowerShell, depuis la racine du dépôt :

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[web]"
$env:QCM_PAPIER_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
cd src-tauri
cargo tauri dev
```

Utiliser un chemin absolu évite de dépendre du répertoire de lancement.
Sans cette variable, le lanceur utilise `python3` (`python` sous Windows).
Sauvegardez ou téléchargez votre travail avant de fermer l'application :
la fermeture arrête le serveur local.

## Ouverture, sauvegarde et fermeture

Les commandes **Ouvrir**, **Enregistrer** et **Enregistrer sous** utilisent les
boîtes de dialogue natives (`rfd`). Enregistrer réutilise le chemin du JSON ouvert
ou précédemment enregistré ; Enregistrer sous permet de choisir un autre fichier.
Les raccourcis sont **Ctrl/Cmd + S** et **Ctrl/Cmd + Maj + S**.

Les exports PDF, ZIP et notes proposent également une destination native.
L'écriture passe par un fichier temporaire dans le dossier de destination, puis
son remplacement. Une annulation ou un échec d'écriture conserve l'indication
« non enregistré ». Avant de fermer, l'application propose de sauvegarder le
projet ou l'archive de correction ; une correction en cours bloque la fermeture.

Les commandes natives sont autorisées uniquement depuis la fenêtre principale
et l'origine locale exacte du serveur lancé par Tauri (port compris).

La compilation et Clippy sont vérifiés sur macOS. Les dialogues et le parcours
visuel complet restent à valider manuellement, ainsi que Windows et Linux.

## Connexion à ScoDoc

L'onglet **Réglages** enregistre le compte ScoDoc avec le même mécanisme que
l'interface web : le mot de passe est conservé dans le trousseau du système
via Python et `keyring`, inclus dans `.[web]`. Un trousseau disponible et
déverrouillé est nécessaire pour enregistrer le compte. Voir le
[guide ScoDoc](../README.md#levée-danonymat-scodoc) pour le parcours complet.

## Vérifier et construire

```bash
# Depuis la racine du dépôt :
cargo check --locked --manifest-path src-tauri/Cargo.toml

# Depuis src-tauri/, avec le même interpréteur Python configuré :
cargo tauri build
```

Les exécutables et paquets sont produits dans `src-tauri/target/release/`.
Ils exigent encore l'interpréteur Python et ses dépendances. La signature,
la notarisation macOS et les installateurs autonomes ne sont pas configurés.

Pour une distribution autonome, il faudra embarquer le serveur Python,
par exemple comme [exécutable compagnon Tauri](https://v2.tauri.app/develop/sidecar/).
Le lanceur accepte déjà `QCM_PAPIER_SERVER`, chemin absolu d'un exécutable
recevant les arguments `serve --no-browser --exit-with-parent --port PORT`.
Aucun exécutable compagnon n'est fourni dans cette PR.

## Dépannage

Vérifiez d'abord le serveur depuis le terminal avec le même Python :

```bash
"$QCM_PAPIER_PYTHON" -m qcm_papier serve --no-browser
```

Puis ouvrez `http://127.0.0.1:8060`. Si ce lancement échoue, vérifiez
l'installation de `.[web]` dans cet environnement.

Retour au [guide principal](../README.md).
