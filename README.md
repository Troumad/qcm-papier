# QCM-Papier — Guide d'installation et d'utilisation

QCM-Papier est un générateur et correcteur de QCM sur papier. Il s'agit d'un
portage en Python/GTK 4 du code HTML+JS de l'Université Lyon 1.

Le principe : on crée un sujet (plusieurs variantes d'un même QCM), on l'imprime,
les étudiants le remplissent, on scanne les copies, puis le logiciel corrige
automatiquement et exporte les notes vers Scodoc.

---

## 1. Prérequis

### Python

- **Python 3.10** ou plus récent.

Vérifiez votre version :

```bash
python3 --version
```

### Dépendances système

Le logiciel utilise GTK 4 pour l'interface graphique. Cette bibliothèque doit
être installée séparément (Python seul ne suffit pas).

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

### Installation simple (utilisation)

Récupérez la version publique (branche `main`) :

```bash
git clone https://github.com/Troumad/qcm-papier.git
cd qcm-papier
pip install ".[gui]"
```

Pour mettre à jour vers la dernière version publiée :

```bash
git pull origin main
pip install ".[gui]"
```

### Pour développeurs (branche de développement)

La branche `nouvelle_main` contient l'historique de développement. En mode
editable, les mises à jour se font par un simple `git pull` sans
réinstaller le paquet :

```bash
git clone https://github.com/Troumad/qcm-papier.git
cd qcm-papier
git checkout nouvelle_main
pip install -e ".[gui]"
```

Mises à jour :

```bash
git pull origin nouvelle_main
```

(Sans le mode `-e`, refaites `pip install -e ".[gui]"`.)

#### Vérifications avant commit

Les outils de vérification (tests, Ruff, pre-commit) s'installent avec :

```bash
pip install -e ".[dev]"
pre-commit install
```

Chaque `git commit` lance alors les vérifications automatiquement. Pour les
lancer à la main :

```bash
pre-commit run --all-files
pytest -q
```

GTK n'est pas nécessaire pour ces vérifications. Pour utiliser aussi
l'interface graphique, installez `.[gui,dev]` avec les prérequis GTK ci-dessus.

Les mêmes vérifications tournent sur GitHub (onglet **Actions**) à chaque push
et à chaque pull request, avec les tests sur Python 3.10 et 3.12.
Ruff bloque uniquement certaines erreurs de code (notamment les noms non
définis) ; les règles étendues et le formatage restent informatifs.
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
3. **Structure** — éditeur des exercices, questions et choix.
4. **Génération** — générer les variantes et le PDF sujet.
5. **Correction** — charger les copies, lancer la correction, voir les pages
   corrigées, lever l'anonymat (Scodoc) et exporter les notes.
6. **Aide** — ce guide.

### Interface web (sans GTK)

La même interface existe dans le navigateur. Elle ne demande pas GTK : Python
suffit, sur Linux, macOS et Windows.

```bash
pip install -e ".[web]"
qcm-papier serve                              # ouvre le navigateur
qcm-papier serve -p math/2026/OML1_bis.json   # avec un projet ouvert
```

- Le serveur écoute uniquement sur `127.0.0.1` (port 8060 par défaut,
  `--port` pour le changer) : les copies et les notes restent sur la machine.
- Les fichiers (projet, copies, tables Scodoc) sont choisis dans la page et
  les résultats (projet, PDF, notes, sauvegarde) sont téléchargés.
- La sauvegarde de correction est une archive `.zip` qui contient l'état, les
  copies corrigées en images **et les fichiers de copies** : on peut la
  recharger plus tard, même sur une autre machine.
- Dans le tableau des résultats, un clic affiche la page, un double-clic
  l'ouvre en grand (zoom, n° étudiant, alignement manuel).

### Application de bureau (Tauri)

Le dossier `src-tauri/` fait de l'interface web une application à
double-cliquer : elle lance le serveur Python et ouvre une fenêtre dessus.
Voir `src-tauri/LISEZMOI.md`.

#### Levée d'anonymat (Scodoc)

Après la correction, les copies sont identifiées par un numéro « p******* ».
Pour associer les noms et prénoms :

1. Téléchargez la table des étudiants depuis Scodoc (menu en haut de la page
   principale du semestre).
2. Onglet **Correction** → bouton **Levée d'anonymat Scodoc…**
3. Chargez le fichier Excel obtenu.

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
