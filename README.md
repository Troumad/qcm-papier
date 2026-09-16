# QCM-Papier — Guide d'installation et d'utilisation

QCM-Papier est un générateur et correcteur de QCM sur papier. Il s'agit d'un
portage en Python du code HTML+JS de l'Université Lyon 1, avec une interface
GTK 4 et une interface web locale (FastAPI, HTML, CSS et JavaScript).

Le principe : on crée un sujet (plusieurs variantes d'un même QCM), on l'imprime,
les étudiants le remplissent, on scanne les copies, puis le logiciel corrige
automatiquement et exporte les notes vers Scodoc.

### Choisir son interface

- **Navigateur** : Python et l'installation `.[web]` suffisent. Lancez
  `qcm-papier serve` depuis un terminal ; GTK et Rust ne sont pas nécessaires.
- **GTK 4** : installez les dépendances système ci-dessous puis `.[gui]`.
- **Fenêtre Tauri** : utilise l'interface web dans une fenêtre de bureau.
  Cette première version exige encore Python et `.[web]` sur la machine.
  Voir [le guide Tauri](src-tauri/README.md) pour la compilation.

---

## 1. Prérequis

### Python

- **Python 3.10** ou plus récent.

Vérifiez votre version :

```bash
python3 --version
```

### Dépendances système

Ces dépendances concernent l'interface GTK 4. Pour l'interface dans le
navigateur, passez directement à l'installation web ci-dessous.

#### Linux (Fedora / RHEL)

```bash
sudo dnf install gtk4 python3-gobject gtk3-devel
```

#### Linux (Debian / Ubuntu / Mint)

```bash
sudo apt install libgtk-4-dev python3-gi
```

#### macOS (avec Homebrew)

```bash
brew install pygobject3 gtk4
```

#### Windows

L'installation de GTK 4 sur Windows est plus délicate. La méthode recommandée
est d'utiliser [MSYS2](https://www.msys2.org/) :

1. Installez MSYS2 puis ouvrez un terminal **MSYS2 UCRT64**.
2. Installez GTK 4 et les bindings Python :

   ```bash
   pacman -S mingw-w64-ucrt-x86_64-python-gobject mingw-w64-ucrt-x86_64-gtk4
   ```

3. Installez ensuite le paquet `qcm-papier` (voir ci-dessous) depuis ce même
   terminal.

> Si l'interface graphique ne se lance pas, vous pouvez tout de même utiliser
> les commandes en ligne de commande (sans `--edit`).

---

## 2. Installation de qcm-papier

### Interface web locale

Depuis la racine d'une version contenant la commande `serve`, avec
[uv](https://docs.astral.sh/uv/) (installation : `curl -LsSf https://astral.sh/uv/install.sh | sh`,
ou `winget install astral-sh.uv` sous Windows) :

```bash
uv sync --extra web
uv run qcm-papier serve
```

`uv sync` crée l'environnement `.venv` du projet, y installe le bon Python et
les dépendances exactes du fichier `uv.lock` : rien à activer, rien à choisir.

Sans uv, l'environnement se prépare à la main :

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell : .venv\Scripts\Activate.ps1
python -m pip install ".[web]"
python -m qcm_papier serve
```
Le navigateur s'ouvre sur `http://127.0.0.1:8060`. Gardez le terminal ouvert ;
`Ctrl+C` arrête le serveur. Aucune compilation des fichiers HTML/JS n'est nécessaire.

### Installation simple (utilisation)

Récupérez la version publique (branche `main`) :

```bash
git clone https://github.com/Troumad/qcm-papier.git
cd qcm-papier
uv sync --extra gui        # sans uv : pip install ".[gui]"
```

Pour mettre à jour vers la dernière version publiée :

```bash
git pull origin main
uv sync --extra gui        # sans uv : pip install ".[gui]"
```

Les lanceurs (`qcm-papier.command`, `qcm-papier.bat`, `qcm-papier.sh`) utilisent
le `.venv` du projet s'il existe, sinon le `python3` du système.

### Pour développeurs (branche de développement)

La branche `nouvelle_main` contient l'historique de développement. En mode
editable, les mises à jour se font par un simple `git pull` sans
réinstaller le paquet :

```bash
git clone https://github.com/Troumad/qcm-papier.git
cd qcm-papier
git checkout nouvelle_main
uv sync --extra gui
```

`uv sync` installe le projet en mode editable : les mises à jour se font par un
simple `git pull origin nouvelle_main`, suivi de `uv sync --extra gui` si les
dépendances ont changé. Sans uv : `pip install -e ".[gui]"`.

#### Vérifications avant commit

Les outils de vérification (tests, couverture, Ruff, Bandit, pre-commit) s'installent avec :

```bash
uv sync --extra dev        # sans uv : pip install -e ".[dev]"
uv run pre-commit install
```

Chaque `git commit` lance alors les vérifications automatiquement. Pour les
lancer à la main :

```bash
uv run pre-commit run --all-files
uv run pre-commit run gitleaks-history --all-files --hook-stage manual
uv run coverage run -m pytest -q
uv run coverage report
uv run coverage report --omit="qcm_papier/ui/*" --fail-under=80
```

GTK n'est pas nécessaire pour ces vérifications. Pour utiliser aussi
l'interface graphique, installez `.[gui,dev]` avec les prérequis GTK ci-dessus.

Les mêmes vérifications tournent sur GitHub (onglet **Actions**) à chaque push
et à chaque pull request, avec les tests sur Python 3.10 et 3.12.
Les contrôles suivants sont bloquants :

- **Ruff** : erreurs Python, imports inutilisés et tri des imports, pièges courants,
  modernisation et simplifications (`E`, `W`, `F`, `I`, `B`, `UP`, `SIM`).
  `ruff check --fix qcm_papier tests` applique les corrections sûres, dont le tri.
- **ruff-format** : mise en forme ; appliquer `ruff format qcm_papier tests`.
- **Bandit** : analyse de sécurité du code Python de production. Les exceptions
  sont locales et commentées (tirages non cryptographiques, repli de widgets GTK).
- **Gitleaks** : secrets dans les changements indexés avant commit, puis historique
  complet en CI. Les rapports masquent les valeurs détectées. Le premier lancement
  du hook peut télécharger Go et compiler Gitleaks ; aucun binaire système n'est requis.
- **Coverage** : mesure des lignes et branches conditionnelles. Le rapport complet
  inclut GTK ; le seuil de 80 % porte explicitement sur le code hors `ui/`, y compris
  la CLI et le point d'entrée. La couverture Python ne mesure ni JavaScript ni Rust.

Les versions de Ruff, Bandit, Gitleaks et de l'action `setup-uv` sont fixées. Les seules exceptions Ruff
sont documentées dans `pyproject.toml` : longueur des lignes gérée par le formateur,
préférence pour certains blocs explicites, ordre d'initialisation GTK et marqueurs
FastAPI. Il n'est pas nécessaire d'installer Flake8, isort ou Black en plus.

Le [bilan détaillé des tests](docs/TESTS.md) précise les taux par module et les limites.

Les parcours synthétiques de génération, correction, export et reprise ZIP tournent
sans données privées. Les tests utilisant les copies réelles restent complémentaires.
Le test utilisant `math/2026/correction3.pdf` est signalé comme ignoré si
les données locales sont absentes, et exécuté normalement lorsqu'elles sont présentes.

---

## 3. Lancer le programme depuis l'explorateur de fichiers

Pour ouvrir l'interface graphique sans passer par le terminal, des lanceurs
sont fournis à la racine du projet. Un double-clic ouvre l'application vide ;
le projet se charge ensuite depuis le menu **Fichier → Ouvrir**.

### Linux

**Double-clic sur `qcm-papier.desktop`** : selon votre gestionnaire de
fichiers, il peut demander confirmation la première fois (c'est normal, le
fichier n'est pas encore « approuvé »).

Pour l'installer durablement dans le menu des applications :

```bash
cp qcm-papier.desktop ~/.local/share/applications/
chmod +x ~/.local/share/applications/qcm-papier.desktop
```

Il apparaîtra dans le menu des applications sous le nom **QCM-Papier**.

### Windows

Double-cliquez sur **`qcm-papier.bat`** (placé à la racine du projet).
Il utilise `pythonw` pour ne pas ouvrir de fenêtre de terminal.

> Si `pythonw` n'est pas trouvé, remplacez `pythonw` par `python` dans le
> fichier `.bat`.

### macOS

Double-cliquez sur **`qcm-papier.command`** (placé à la racine du projet).
La première fois, le Finder peut bloquer le lancement : faites
**clic droit → Ouvrir** pour autoriser, puis confirmez.

> Les lanceurs partent du principe que Python est accessible sous le nom
> `python3` (Linux/macOS) ou `pythonw` (Windows) et que le paquet
> `qcm-papier` est installé (`pip install -e ".[gui]"`).

---

## 4. Les images d'aide Scodoc

Les captures d'écran affichées dans les dialogues de levée d'anonymat et
d'export des notes se trouvent dans :

```
qcm_papier/data/scodoc/
```

- `Scodoc_student_list.png` — téléchargement de la table des étudiants.
- `Scodoc_eval_get1.png` et `Scodoc_eval_get2.png` — récupération de la feuille
  de notes.
- `Scodoc_eval_send.png` — renvoi des notes dans Scodoc.

Scodoc est régulièrement mis à jour : il suffit de remplacer ces PNG (en
conservant les mêmes noms) puis de relancer l'application.

---

## 5. Utilisation

### En ligne de commande

Le programme s'appelle `qcm-papier` (ou `python3 -m qcm_papier`).

#### Ouvrir un projet dans l'interface graphique

```bash
qcm-papier open -p math/2026/OML1_bis.json --edit
```

`--edit` ouvre la fenêtre graphique. Sans `--edit`, le projet est seulement
validé et un résumé s'affiche.

#### Générer les variantes

Les variantes sont les versions différentes du sujet (ordre des questions/choix
modifié selon l'id de la variante).

```bash
qcm-papier variants -p math/2026/OML1_bis.json
```

Les variantes sont sauvegardées dans le JSON du projet.

#### Générer le PDF du sujet

```bash
qcm-papier pdf -p math/2026/OML1_bis.json -o sujet.pdf
```

Ou tout en un (variantes + PDF) :

```bash
qcm-papier generate -p math/2026/OML1_bis.json -o sujet.pdf
```

Avec `--per-student`, une copie par étudiant est générée (au lieu d'une par
variante).

#### Corriger des copies

```bash
qcm-papier correct -p math/2026/OML1_bis.json --copies math/2026/correction3.pdf --edit
```

Options utiles :

- `--students table.xlsx` — table des étudiants Scodoc (pour la levée d'anonymat).
- `--save etat.json` — sauvegarde l'état de correction (pour recharger plus tard
  sans refaire l'alignement).
- `--load etat.json` — recharge un état de correction sauvegardé.
- `--clair 140` — seuil de détection des cases cochées (augmentez pour des scans
  plus sombres, ex. `--clair 160`).
- `--render dossier/` — produit des images PNG des copies corrigées (overlay
  vert/rouge).
- `--scodoc-input feuille.xlsx` — remplit une feuille Scodoc avec les notes.

### Interface graphique

L'interface est organisée en onglets :

1. **Fichier** — ouvrir, créer, enregistrer un projet.
2. **Informations** — résumé du projet (exercices, questions, choix, variantes).
3. **Structure** — éditeur des exercices, questions et choix. Chaque ligne de
   l'arborescence porte trois boutons : ▲ et ▼ déplacent l'élément d'un cran,
   ✕ le supprime après confirmation. Un projet garde toujours au moins un
   exercice, et un exercice au moins une question.
4. **Génération** — générer les variantes et le PDF sujet.
5. **Correction** — charger les copies, lancer la correction, voir les pages
   corrigées, lever l'anonymat (Scodoc) et exporter les notes.
6. **Aide** — ce guide.

### Interface web (sans GTK)

Une interface complémentaire existe dans le navigateur : édition, génération,
correction et sauvegarde. Elle utilise Python avec `.[web]`, sans GTK.
L'éditeur de structure applique les mêmes règles que l'interface GTK, y compris
la suppression et le déplacement des exercices et des questions. Le choix du
dossier d'enregistrement reste propre à GTK : le navigateur télécharge les
fichiers dans son dossier habituel.

```bash
uv sync --extra web
uv run qcm-papier serve                              # ouvre le navigateur
uv run qcm-papier serve -p math/2026/OML1_bis.json   # avec un projet ouvert
```

- Le serveur écoute uniquement sur `127.0.0.1` (port 8060 par défaut,
  `--port` pour le changer) : les copies et les notes restent sur la machine.
- Les fichiers (projet, copies, tables Scodoc) sont choisis dans la page et
  les résultats (projet, PDF, notes, sauvegarde) sont téléchargés.
- La sauvegarde de correction est une archive `.zip` qui contient l'état, les
  copies corrigées en images, **le projet et les fichiers de copies** : on peut la
  recharger plus tard, même sur une autre machine.
- Dans le tableau des résultats, un clic affiche la page, un double-clic
  l'ouvre en grand (zoom, n° étudiant, alignement manuel).

### Application de bureau (Tauri)

Le dossier `src-tauri/` fait de l'interface web une application à
double-cliquer : elle lance le serveur Python et ouvre une fenêtre dessus.
Python avec `.[web]` doit encore être installé sur la machine.
Voir [le guide Tauri](src-tauri/README.md).

#### Levée d'anonymat (Scodoc)

Après la correction, les copies sont identifiées par un numéro « p******* ».
Pour associer les noms et prénoms :

1. Téléchargez la table des étudiants depuis Scodoc (menu en haut de la page
   principale du semestre).
2. Onglet **Correction** → bouton **Levée d'anonymat Scodoc…**
3. Chargez le fichier Excel obtenu.

**Dans l'interface web**, la même boîte de dialogue permet aussi de charger
les étudiants directement depuis le serveur ScoDoc, sans fichier Excel.

1. Une seule fois, dans l'onglet **Réglages** : adresse du serveur (en
   `https://`), identifiant et mot de passe du **compte ScoDoc dédié** disposant des droits de lecture
   des étudiants et semestres concernés, puis **Tester la connexion**.
2. Dans **Table étudiants (Scodoc)…** : **Se connecter à ScoDoc**, choisir le
   département et le semestre en cours, puis **Charger les étudiants du
   semestre**.

Le mot de passe est rangé dans le trousseau sécurisé du système (Trousseau
macOS, Gestionnaire d'identifiants Windows, Secret Service sous Linux) ; il
n'est jamais écrit dans un fichier ni réaffiché. Sans trousseau disponible,
l'enregistrement est refusé. Selon votre établissement, l'accès au serveur
peut nécessiter le réseau interne ou le VPN. Installez les dépendances avec
`uv sync --extra web`.

Si la connexion échoue avec `[SSL: CERTIFICATE_VERIFY_FAILED] ... unable to get
local issuer certificate`, l'interpréteur utilisé n'a pas de magasin de
certificats : c'est le cas d'un Python installé depuis python.org sous macOS
tant que `/Applications/Python 3.x/Install Certificates.command` n'a pas été
lancé. Passer par `uv sync` puis `uv run` évite le problème.

L'adresse et l'identifiant sont conservés dans `scodoc.json`, dans le dossier
de configuration de l'application ; seul le mot de passe va dans le trousseau.
Un mot de passe laissé vide conserve celui du compte enregistré uniquement si
l'adresse et l'identifiant restent identiques. Un changement de serveur ou de
compte exige de le ressaisir. Après modification des réglages ou expiration du
jeton, reconnectez-vous depuis la fenêtre de sélection des étudiants.

Utilisez l'adresse HTTPS finale du serveur : les redirections sont refusées.
L'intégration lit les départements, semestres en cours et étudiants ; elle
n'envoie aucune note à l'API. L'export des notes reste réalisé par fichier Excel.

En ligne de commande, avec le compte enregistré :

```bash
qcm-papier scodoc status                          # compte enregistré (sans le mot de passe)
qcm-papier scodoc test                            # tester la connexion
qcm-papier scodoc dump -o ~/scodoc_dump -d GEII   # réponses brutes de l'API en JSON
```

Les fichiers de `dump` contiennent des données personnelles : à garder hors
du dépôt Git et à supprimer après usage.

L'identifiant lu sur la copie est `p` + le NIP Scodoc sans son premier chiffre
(ex. NIP `12504873` → `p2504873`).

#### Export des notes Scodoc

Onglet **Correction** → bouton **Exporter les notes Scodoc…**

- Choisissez le fichier tableur Scodoc (entrée) et le fichier de sortie.
- Option « Monter les notes négatives à 0 » : les notes négatives sont
  ramenées à 0.

#### Alignement manuel des repères

Si une copie est mal scannée et que les 5 repères d'orientation ne sont pas
trouvés automatiquement, le logiciel demande de les placer à la main :

1. Cliquez sur les 5 repères dans l'ordre : à gauche de haut en bas, puis à
   droite de bas en haut.
2. Les repères déjà détectés sont marqués en bleu clair sur toutes les copies.
3. Une fois les 5 points placés, la correction se fait par transformation
   affine de la page.

> Pour un alignement manuel fiable, évitez de zoomer : restez à 100 % et
> utilisez la fenêtre à sa taille initiale. Le défilement (scroll) n'affecte
> pas le placement.

---

## 6. Dépannage

### « Interface graphique indisponible »

GTK 4 n'est pas installé. Revenez à la section *Dépendances système*.
En attendant, les commandes en ligne de commande fonctionnent sans `--edit`.

### Les captures d'écran Scodoc ne s'affichent pas

Vérifiez que les fichiers sont bien présents dans `qcm_papier/data/scodoc/`.
En cas d'erreur, un message s'affiche dans le terminal :
`[scodoc-image] image absente : …` ou `[scodoc-image] échec chargement …`.

### Une copie mal scannée n'est pas corrigée

Utilisez l'alignement manuel (clic sur les 5 repères). Si le problème persiste,
augmentez le seuil `--clair` (ex. `--clair 160`).

---

## 7. Licence

GPL-3.0-or-later. Portage Python/GTK 4 du code HTML+JS de l'Université Lyon 1.
