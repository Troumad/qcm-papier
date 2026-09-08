# Fonction `_place_choices` - Explication complète

## 📌 Ce que tu cherches : **LA LETTRE DANS LA CASE**

**⚠️ LA LETTRE N'EST PAS DANS `_place_choices` !**

Dans `_place_choices`, on crée **uniquement les cercles** (cases à cocher) avec leurs propriétés :
- `x, y` : position
- `r` : rayon (positif = vide, **négatif = pré-coché**)
- `index` : index du choix (**négatif = fantôme**)
- `dash` : True pour les jokers (pointillés)

**La lettre (A, B, C...) ou le symbole fantôme est ajoutée dans `pdf_writer.py` !**

---

## 📊 Structure complète de la fonction

### Signature
```python
def _place_choices(variant, variant_id,
                   exercise, question,
                   exercise_index: int, question_iter: int,
                   question_name_width_max: float,
                   settings: ProjectSettings) -> tuple[list, list, list, list, float, float]
```

**Retourne :** `(texts, rects, circles, marks, width, height)`

| Élément | Type | Description |
|---------|------|-------------|
| `texts` | list[dict] | Textes à afficher (nom de question, nom de choix) |
| `rects` | list[dict] | Rectangles (zones de réponse manuelle) |
| **`circles`** | **list[dict]** | **CASES À COCHER** - **C'EST ICI** |
| `marks` | list[dict] | Marques de correction (e, q, c pour correction auto) |
| `width` | float | Largeur totale de la question |
| `height` | float | Hauteur totale de la question |

---

## 🔍 Où sont créés les cercles (cases à cocher)

### Dans la **BOUCLE PRINCIPALE** (lignes ~381-432) :

```python
while choice_list:
    # 1. Sélection du choix
    if choice_random:
        choice_index = rg.random_index(variant_id, len(choice_list))
    else:
        choice_index = 0
    choice = choice_list[choice_index]
    choice_list.pop(choice_index)
    
    # 2. Position x, y
    x = choice_x + 2
    y = choice_y + 3
    if choice_dir:
        choice_y += 5  # Vers le bas
    else:
        choice_x += 6  # Vers la droite
    
    # 3. Ajout du texte du choix
    texts.append({"x": x, "y": y, "t": choice.get("name", ""), "center": True})
    
    # ⭐⭐⭐ 4. CRÉATION DU CERCLE (LA CASE) ⭐⭐⭐
    exercice_fantome = exercise.get("index", -1) < 0
    question_fantome = question.get("index", -1) < 0
    choix_fantome = choice.get("index", -1) < 0
    niveau_fantome = sum([exercice_fantome, question_fantome, choix_fantome])
    
    if choice.get("index", -1) >= 0:
        # ✅ CHOIX NORMAL (index >= 0)
        # -> JAMAIS pré-coché aléatoirement
        if niveau_fantome == 0 and choice_checked:
            circles.append({"x": x, "y": y, "r": -2.3, "index": choice.get("index", -1)})
        else:
            circles.append({"x": x, "y": y, "r": 2.3, "index": choice.get("index", -1)})
    else:
        # 👻 CHOIX FANTÔME (index < 0)
        # -> Pré-coché aléatoirement selon le niveau
        if random.randint(1, 2 * niveau_fantome) < (2 if choix_fantome else 1):
            circles.append({"x": x, "y": y, "r": -2.3, "index": choice.get("index", -1)})
        else:
            circles.append({"x": x, "y": y, "r": 2.3, "index": choice.get("index", -1)})
    
    # 5. Ajout des marques de correction (SEULEMENT pour les choix valides)
    if (exercise.get("index", -1) >= 0 and question.get("index", -1) >= 0
            and choice.get("index", -1) >= 0):
        marks.append({"x": x, "y": y, "r": 2.3,
                      "e": exercise.get("index", -1), 
                      "q": question.get("index", -1),
                      "c": choice.get("index", 0)})
```

---

## 🎯 Ce que fait chaque partie

### Les CERCLES (cases à cocher)

**Structure d'un cercle :**
```python
{
    "x": position_x,      # Position horizontale (mm)
    "y": position_y,      # Position verticale (mm)
    "r": rayon,           # Rayon du cercle
    "index": index_choix, # Index du choix (-1 = fantôme)
    "dash": True/False    # True = pointillés (joker)
}
```

**Signification de `r` :**
- `r > 0` (ex: `2.3`) → **Cercle vide** (case **non cochée**)
- `r < 0` (ex: `-2.3`) → **Cercle rempli** (case **pré-cochée**)

### Les TEXTES

Les textes des choix sont ajoutés séparément dans `texts` :
```python
texts.append({"x": x, "y": y, "t": choice.get("name", ""), "center": True})
```

**La lettre (A, B, C...) n'est PAS ici !** Elle est probablement gérée dans `pdf_writer.py`.

### Les MARQUES (marks)

Les marques sont utilisées pour la **correction automatique** :
```python
marks.append({
    "x": x, "y": y, "r": 2.3,
    "e": exercise_index,  # Index de l'exercice
    "q": question_index, # Index de la question
    "c": choice_index    # Index du choix
})
```

**SEULEMENT** pour les choix valides (index >= 0 à tous les niveaux).

---

## 🔥 PROBLÈME ACTUEL : "Ça ne passe pas"

### Ce qui a été modifié récemment :

1. **Seules les cases FANTÔMES (index < 0) sont pré-cochées aléatoirement**
2. **Les cases NORMALES (index >= 0) ne sont JAMAIS pré-cochées aléatoirement**

### Vérifie si :

✅ **Les cases fantômes ont bien `index < 0`**
- Dans `_choice_to_dict()`, vérifie que les choix fantômes ont `index = -1` ou moins
- Dans `rg.insert_choices()`, vérifie que les nouveaux choix fantômes ont des index négatifs

✅ **Le pré-cochage utilise bien `random.randint`**
- Pour les fantômes : `random.randint(1, 2 * niveau_fantome) < (2 if choix_fantome else 1)`
- Pour le joker : probabilités basées sur le type de choix

✅ **Dans `pdf_writer.py`, vérifie que :**
- `r < 0` → cercle **rempli** (pré-coché)
- `r > 0` → cercle **vide** (non coché)

---

## 📝 Comment intervenir dans ce fichier

### Pour modifier le comportement des cases fantômes :

**Ligne ~415-425 dans `_place_choices` :**
```python
else:
    # Choix FANTÔME : probabilité basée sur le niveau
    if niveau_fantome > 0:
        if random.randint(1, 2 * niveau_fantome) < (2 if choix_fantome else 1):
            circles.append({"x": x, "y": y, "r": -2.3, "index": choice.get("index", -1)})
        else:
            circles.append({"x": x, "y": y, "r": 2.3, "index": choice.get("index", -1)})
```

### Pour ajouter un symbole dans les cases fantômes :

**Ce n'est PAS ici !** Il faut modifier `pdf_writer.py` :

Cherche dans `pdf_writer.py` la boucle qui dessine les cercles :
```python
for circle in variant.circles:
    r = circle.get("r", 2.3)
    x = circle.get("x", 0) * mm
    y = to_pdf_y(circle.get("y", 0))
    # ... dessin du cercle ...
```

**Ajoute après le dessin du cercle :**
```python
# Si c'est un fantôme (index < 0), ajouter un symbole
if circle.get("index", -1) < 0:
    c.setFont("Helvetica", 5)
    c.drawCentredString(x, y - 1 * mm, "F")  # ou "*" ou tout autre symbole
    c.setFont("Helvetica", 12)
```

---

## 🎯 Résumé : Où chercher quoi

| Élément | Où le trouver | Variable clé |
|---------|---------------|--------------|
| **Création des cases** | `_place_choices()` dans `generator.py` | `circles` |
| **Pré-cochage** | `_place_choices()` | `r` (négatif = pré-coché) |
| **Dessin des cases** | `_draw_variant()` dans `pdf_writer.py` | boucle `for circle in variant.circles` |
| **Lettre du choix (A,B,C)** | `_draw_variant()` dans `pdf_writer.py` | boucle `for text in variant.texts` |
| **Symbole fantôme** | `_draw_variant()` dans `pdf_writer.py` | à ajouter manuellement |
| **Correction auto** | `_place_choices()` | `marks` |

---

## 💡 Conseils pour déboguer

### 1. Vérifie les index des choix

Ajoute un print dans `_place_choices` :
```python
print(f"Choix: {choice.get('name')}, index: {choice.get('index')}, "
      f"niveau_fantome: {niveau_fantome}, r: {r}")
```

### 2. Vérifie ce qui est dessiné

Dans `pdf_writer.py`, avant de dessiner les cercles :
```python
for circle in variant.circles:
    print(f"Circle: x={circle.get('x')}, y={circle.get('y')}, "
          f"r={circle.get('r')}, index={circle.get('index')}, "
          f"dash={circle.get('dash')}")
```

### 3. Vérifie les fantômes

Vérifie que les choix fantômes ont bien `index < 0` :
- Dans `model.py`, vérifie `_choice_to_dict()`
- Dans `random_gen.py`, vérifie `insert_choices()`

---

## 📞 Besoin d'aide ?

Si tu veux que j'intervienne directement dans le fichier, dis-moi **exactement** ce que tu veux modifier :

- **Quelle ligne** ?
- **Quel comportement** tu veux ?
- **Quelle probabilité** pour les fantômes ?

Exemple :
> "Je veux que TOUTES les cases fantômes soient pré-cochées à 50%, pas seulement selon le niveau"

Ou :
> "Je veux ajouter la lettre 'F' dans les cases fantômes pré-cochées"
