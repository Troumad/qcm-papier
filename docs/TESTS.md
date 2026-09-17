# Bilan des tests et de la couverture

Mesure du 17 septembre 2026, Python 3.12, sur une copie ne contenant que les
fichiers versionnés et les nouveaux tests. Aucun PDF étudiant privé n'est requis.

## Résultats

- 175 tests Python réussis, 5 ignorés car ils nécessitent le PDF local de correction.
- Les mêmes tests passent sous Python 3.10.
- 17 tests JavaScript (Markdown, sauvegardes et filtres de correction) réussis ; pas de mesure de couverture JavaScript.
- Ruff étendu, formatage et Bandit passent.
- Gitleaks passe sur l'historique : deux faux positifs jsPDF (alphabet hexadécimal)
  sont exclus par empreinte précise dans `.gitleaksignore`.

## Couverture

La mesure combine lignes exécutables et branches conditionnelles :

- **51,6 % sur tout le paquet Python**, GTK inclus.
- **82,6 % hors `qcm_papier/ui/`**, CLI et point d'entrée inclus.
- Sur ce dernier périmètre : **86,1 % des lignes** (3408/3957) et
  **72,3 % des branches conditionnelles** (1001/1384).
- Le seuil CI de **80 %** porte sur la mesure combinée hors GTK. Ce seuil protège
  contre les régressions globales ; il ne garantit pas chaque module individuellement.

| Module | Couverture combinée |
|---|---:|
| `qcm_papier/__main__.py` | 50.0 % |
| `qcm_papier/cli.py` | 76.0 % |
| `qcm_papier/code39.py` | 90.9 % |
| `qcm_papier/config.py` | 80.0 % |
| `qcm_papier/editing.py` | 93.5 % |
| `qcm_papier/generator.py` | 83.7 % |
| `qcm_papier/marking.py` | 79.1 % |
| `qcm_papier/model.py` | 89.2 % |
| `qcm_papier/pdf_preview.py` | 100.0 % |
| `qcm_papier/pdf_writer.py` | 88.3 % |
| `qcm_papier/project.py` | 90.4 % |
| `qcm_papier/random_gen.py` | 100.0 % |
| `qcm_papier/scanner.py` | 74.8 % |
| `qcm_papier/scodoc.py` | 90.4 % |
| `qcm_papier/scodoc_api.py` | 94.2 % |
| `qcm_papier/scodoc_config.py` | 78.7 % |
| `qcm_papier/ui/app.py` | 0.0 % |
| `qcm_papier/ui/editor.py` | 0.0 % |
| `qcm_papier/web/server.py` | 82.5 % |
| `qcm_papier/web/session.py` | 86.0 % |

## Ce qui a été renforcé

19 cas supplémentaires vérifient les commandes CLI, la génération effective de PDF,
la sauvegarde des variantes, les erreurs de fichiers, la correction et reprise CLI,
les réponses joker selon trois barèmes, ainsi que le parcours API de correction,
identification manuelle, images PNG, sauvegarde ZIP, suppression et reprise.
Les tirages de tests sont fixés pour rendre les résultats reproductibles.

Depuis la fusion de la PR #20, dix cas Python supplémentaires protègent les
instantanés de sauvegarde, le blocage pendant une correction, l'export PDF + JSON,
le remplacement du projet et les archives contenant des copies en attente.
Quatorze cas JavaScript supplémentaires couvrent les filtres, les doublons,
l'annulation, l'échec d'écriture, les modifications concurrentes à une sauvegarde,
le téléchargement effectif du JSON et son rappel après l'export PDF. Un test Python
vérifie qu'un sujet modifié ne réexporte pas les anciennes variantes, y compris
après sauvegarde et réouverture.
Avec le PDF privé présent localement, les **180 tests Python** passent.

Le lanceur Tauri compile sur macOS ; `cargo fmt --check` et
`cargo clippy --locked -- -D warnings` passent. Cela ne valide pas les dialogues natifs.

Après intégration de `nouvelle_main` (jusqu'à `b90dac2`), les sept tests de
positionnement PDF passent : en-tête, cadres, paysage, pied de page multiligne
et code-barres. Une page synthétique a aussi été contrôlée visuellement : pas
de chevauchement entre l'en-tête et le cadre, ni entre le pied et le code-barres.
Le binaire Tauri démarre sur macOS avec un JSON de test et son serveur répond.

## Limites et prochains tests prioritaires

1. Scanner (74,8 %) : copies dégradées, rotations, numéros illisibles et échecs
   d'alignement. Le PDF synthétique valide un parcours idéal, pas toutes les qualités de scan.
2. Calcul des notes (79,1 %) : combinaisons de barèmes, notes manuelles et cas limites.
3. API web (82,5 %) et CLI (76 %) : erreurs d'import, export des notes, annulation
   et échecs de tâches en arrière-plan.
4. GTK : code non exercé ici ; il faut des tests dans un environnement GTK adapté.
5. ScoDoc : serveur simulé et trousseau en mémoire. Un serveur réel et les trousseaux
   natifs doivent encore être essayés.
6. Navigateur et Tauri : pas de tests du parcours visuel, de couverture Rust ou de
   validation Windows/Linux dans cette suite. Les tests JavaScript isolés ne couvrent pas toute l'interface. Les parcours E2E,
   les scans dégradés et les essais multiplateformes restent dans un chantier suivant.

## Reproduire

Le lanceur `lancer-tauri.sh` dispose de six tests inclus dans le total ci-dessus avec outils
simulés : chemin du JSON avec espaces, environnement Python séparé, absence de
projet, aide et arguments invalides. Ils n'installent aucun paquet et n'ouvrent
aucune fenêtre. La compilation et Clippy du lanceur passent sur macOS ; une
installation complète sur une machine Linux vierge reste à valider.

```bash
uv sync --extra dev
uv run coverage run -m pytest -q
uv run coverage report
uv run coverage report --omit="qcm_papier/ui/*" --fail-under=80
uv run coverage html
node --test tests/js/*.cjs
uv run pre-commit run --all-files
uv run pre-commit run gitleaks-history --all-files --hook-stage manual
```

Sans [uv](https://docs.astral.sh/uv/) : `python -m pip install -e ".[dev]"` dans un
environnement virtuel, puis les mêmes commandes sans le préfixe `uv run`.

La présence du PDF local peut augmenter le nombre de tests exécutés et la couverture.
Le rapport HTML contient les lignes et branches non exercées pour guider les prochains tests.
