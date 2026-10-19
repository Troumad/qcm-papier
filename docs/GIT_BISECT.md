# `git bisect` : retrouver le commit qui a cassé quelque chose

## Le principe

`git bisect` est une **recherche dichotomique** (binary search) dans l'historique
git. Quand un défaut apparaît — un bug d'affichage, un test qui échoue, une
régression — et qu'on ne sait pas quel commit l'a introduit, `git bisect`
élimine la moitié des candidats à chaque étape :

| Commits suspects | Étapes de bisect nécessaires |
|---:|---:|
| 4 | 2 |
| 100 | ~7 |
| 1 000 | ~10 |
| 1 000 000 | ~20 |

C'est l'équivalent du jeu « qui est-ce ? » appliqué à l'historique : à chaque
essai, git vous place sur un commit intermédiaire, vous testez, vous répondez
« bon » ou « mauvais », et git resserre l'intervalle.

## Le vocabulaire

- **`good`** : un commit où le défaut **n'existe pas** (le code y fonctionne).
- **`bad`** : un commit où le défaut **existe**.
- git cherche le **premier commit fautif** : le plus ancien commit `bad`,
  c'est-à-dire celui qui a fait basculer l'historique de bon à mauvais.

## La procédure de base

```bash
git bisect start
git bisect bad              # l'état actuel (HEAD) est cassé
git bisect good v2.3         # cette ancienne étiquette marchait
```

Git checkout automatiquement un commit au milieu de l'intervalle :

```
Bissection : 3 révisions à tester après ceci (environ 2 étapes)
[abc1234...] Correction du placement des images
```

Testez ce commit (lancez l'application, le test, la procédure qui reproduit le
défaut), puis répondez :

```bash
git bisect good    # le défaut n'est PAS présent ici
# ou
git bisect bad     # le défaut EST présent ici
```

Répétez jusqu'au verdict :

```
abc1234 is the first 'bad' commit
commit abc1234 (HEAD)
Author: ...
```

Enfin, revenez à votre branche de travail :

```bash
git bisect reset
```

## Exemple réel : le bug d'affichage de la visionneuse

Ce qui suit est une session vécue sur ce projet (octobre 2026). La fenêtre
« Page corrigée » n'affichait les copies qu'après un coup de zoom ; la
navigation laissait la page précédente affichée.

**1. Trouver les bornes.** Le défaut existait sur `nouvelle_main` (bad) mais
une version quelques commits plus tôt l'affichait correctement. Vérification
du point good — étape cruciale, un point good erroné fausse toute la recherche :

```bash
git checkout 9d06375
python -m qcm_papier        # test manuel : l'affichage y fonctionne ✔
git checkout nouvelle_main
```

**2. Lancer la bissection** (3 commits suspects seulement, grâce à un
squat préalable des commits d'essais) :

```bash
git bisect start
git bisect bad              # HEAD actuel : l'affichage est cassé
git bisect good 9d06375     # point bon confirmé à l'instant
```

Git propose le commit du milieu : `6064fcb` (bloc orientation). Test →
l'affichage reste cassé → `git bisect bad`. Git propose alors `df3f054`
(bloc joker/décompte). Test → toujours cassé → `git bisect bad`.

**3. Verdict :**

```
df3f054 is the first 'bad' commit
```

**4. Le verdict désigne le bloc, le diff désigne la ligne.** Un coup d'œil au
diff du commit fautif (`git show df3f054`) a suffit à voir la ligne coupable :
en ajoutant le décompte des points à la visionneuse, l'appel
`self._update_image()` avait été **remplacé** par
`self._update_page_breakdown(page)` au lieu d'être complété — l'image n'était
plus jamais rafraîchie au changement de page. Une ligne rétablie, bug réglé.

À retenir de cet exemple : trois correctifs successifs avaient échoué en
devinant la cause (couches de rendu GTK). Le bisect n'a pas deviné — il a
montré *où* regarder, et le diff a fait le reste.

## Astuces et pièges

### Le point `good` doit être vraiment bon
C'est la borne qui oriente toute la recherche. Si votre « good » est en
réalité bogué, le verdict sera faux. Prenez le temps de le vérifier en
l'exécutant ; en cas de doute, reculez encore (`git bisect good <plus_vieux>`).

### Un commit impossible à tester : `skip`
Un commit intermédiaire peut être inutilisable (plantage au démarrage, code
qui ne compile plus, migration en cours) :

```bash
git bisect skip
```

Git en choisit un autre pour continuer.

### Automatiser le test : `git bisect run`
Si le défaut se traduit par un test automatisé qui échoue, la bissection peut
être entièrement automatique :

```bash
git bisect start HEAD v2.3
git bisect run python -m pytest tests/test_scanner.py
git bisect reset
```

Git teste chaque commit par lui-même (code de retour 0 = good, non nul = bad)
et affiche le verdict. Pour un défaut purement visuel comme notre exemple,
le test manuel reste la règle.

### Voir où en est la recherche
```bash
git bisect log      # journal des décisions déjà prises
git bisect visualize # graphe des commits restants (git log --graph)
```

### Les fichiers de travail ne bougent pas
Checkout un ancien commit ne modifie que les fichiers **versionnés**. Vos
données hors dépôt (projets JSON, scans, sauvegardes de correction) restent
en place et peuvent servir à chaque étape — pratique pour recharger la même
correction sur chaque commit testé.

### Attention aux historiques réécrits
Un bisect se fait sur des ancêtres **linéaires**. Si les commits suspects ont
été condensés (squash/rebase), le verdict désigne le condensé ; il faut alors
refiner à l'intérieur (par exemple en re-poussant les commits d'origine
depuis une branche qui les a conservés).

### Sortir proprement
```bash
git bisect reset
```
Vous rend à la branche d'origine, dépôt propre. Pendant le bisect, git est en
état « HEAD détaché » — ne pas committer sans être sorti.

## En résumé

1. Reproduire le défaut et identifier un commit « good » certain.
2. `git bisect start`, `bad`, `good`.
3. À chaque commit proposé : tester, puis `good` / `bad` (`skip` si intestable).
4. Lire le verdict, ouvrir le diff du commit fautif, corriger.
5. `git bisect reset`.
