# Rapport de bug : conversions docx → ODT générant des documents non conformes aux attentes LibreOffice

*Rapport destiné à Mistral AI, rédigé suite à la correction des styles de
`mes-notes-git.odt` (PR #32, commit `bbf9ce2`).*

## Composant concerné

Génération/correction de documents ODT issus d'une conversion depuis docx
(exemple : `mes-notes-git.odt`, dépôt `Troumad/qcm-papier`).

## Résumé

Lors de la production ou modification d'un document ODT issu d'une conversion
depuis docx, les styles de titre sont créés sous des noms `Heading1`–`Heading4`
comme styles de paragraphe *ordinaires*. Ils perdent la sémantique de titre ODF :

- absence de `style:class="chapter"` ;
- absence de `style:default-outline-level="N"` (le niveau de plan, élément clé) ;
- absence d'héritage du style `Heading` ;
- noms externes (`Heading1`) au lieu des noms internes des styles intégrés
  (`Heading_20_1`, `_20_` codant l'espace).

## Conséquences pour l'utilisateur final (LibreOffice Writer)

- les titres n'apparaissent pas dans le navigateur (F5) ;
- l'index (table des matières) ne se génère pas correctement ;
- les styles s'affichent sous des noms anglais non standard au lieu de
  « Titre 1 »–« Titre 4 » ;
- la hiérarchisation/numérotation automatique ne fonctionne pas.

## Comportement attendu

Pour un document ODF destiné à LibreOffice, les styles de titre doivent être
soit les styles intégrés `Heading_20_1`…`Heading_20_10` (noms internes ODF,
affichés « Titre 1 »–« Titre 10 » en interface française), soit des styles
personnalisés portant au minimum :

```xml
<style:style style:name="MonTitre" style:family="paragraph"
              style:parent-style-name="Heading" style:class="chapter"
              style:default-outline-level="N">
  <style:paragraph-properties fo:keep-with-next="always"/>
</style:style>
```

## Recommandations

1. Lors d'une conversion docx → ODT (ou d'une génération ODT), mapper les
   styles `Heading N` vers les styles intégrés `Heading_20_N` plutôt que de
   créer des styles plats du même nom.
2. Toujours préserver `style:default-outline-level` et `style:class="chapter"` :
   c'est la sémantique, pas le nom, qui fait un titre ODF.
3. Un paragraphe peut porter un style de titre sans être un élément titre :
   la conversion doit produire de vrais éléments `<text:h text:outline-level="N">`,
   pas seulement appliquer le style à un `<text:p>`. Symptôme observé : le style
   Titre est appliqué, la mise en forme est correcte à l'écran, mais les titres
   n'apparaissent ni dans le navigateur ni dans l'index (3 titres sur 22
   manquaient, dont le tout premier).
4. Rappel de structure d'archive ODF : `mimetype` en première entrée,
   stocké sans compression.
5. Les agents capables de lire/écrire le XML ODF disposent de tout le
   nécessaire pour appliquer ces règles sans passer par LibreOffice — autant
   les systématiser pour éviter de la dette de mise en forme chez les
   utilisateurs.

## Reproduction

Voir commits `bbf9ce2`, `a78a240` et `59084b5` du dépôt `Troumad/qcm-papier` :

- le fichier original contenait 12 paragraphes `Heading2`, 5 `Heading1`,
  4 `Heading3`, 2 `Heading4`, tous sans niveau de plan ;
- après correction des styles, 3 titres restaient invisibles dans le
  navigateur et l'index car codés comme des `<text:p>` avec style de titre
  au lieu de `<text:h>` (voir recommandation 3).
