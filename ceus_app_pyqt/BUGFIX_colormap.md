# 🔧 Correction PyQtGraph Colormaps

## Problème Résolu

**Erreur rencontrée:**
```
Failed to load DICOM:
[Errno 2] No such file or directory: '/Users/.../pyqtgraph/colors/maps/gray'
```

## Cause du Problème

PyQtGraph n'a **pas de colormap 'gray'** native. Les colormaps disponibles sont différentes de matplotlib :

| Matplotlib | PyQtGraph | Status |
|------------|-----------|--------|
| `'gray'` | ❌ N'existe pas | Erreur |
| `'grey'` | ✅ Peut-être | Non testé |
| `None` (défaut) | ✅ Grayscale | **Solution** |
| `'magma'` | ✅ Disponible | OK |
| `'viridis'` | ✅ Disponible | OK |
| `'hot'` | ✅ Disponible | Fallback |

## Solution Implémentée

### B-mode (grayscale)
```python
# ❌ AVANT (erreur)
self.bmode_view.setColorMap(pg.colormap.get('gray'))

# ✅ APRÈS (corrigé)
self.bmode_view.setColorMap(None)  # Default grayscale
```

### CEUS raw (grayscale)
```python
# ❌ AVANT (erreur)
self.ceus_view.setColorMap(pg.colormap.get('gray'))

# ✅ APRÈS (corrigé)
self.ceus_view.setColorMap(None)  # Default grayscale
```

### CEUS preprocessed (magma)
```python
# ✅ OK (avec fallback)
try:
    self.ceus_view.setColorMap(pg.colormap.get('magma'))
except:
    self.ceus_view.setColorMap(pg.colormap.get('hot'))  # Fallback
```

## Rendu Visuel

### Grayscale (None vs 'gray')
- **PyQtGraph `None`**: Affichage grayscale par défaut ✅
- **Matplotlib `'gray'`**: Colormap grayscale ✅
- **Résultat**: Identique visuellement ! 🎨

### Magma
- **PyQtGraph `'magma'`**: Colormap magma disponible ✅
- **Matplotlib `'magma'`**: Identique ✅
- **Résultat**: Parfaitement identique ! 🎨

## Workflow Corrigé

```python
# 1. Load DICOM
self.image_viewer.set_stacks(bmode, ceus, fps, ceus_is_preprocessed=False)
# → B-mode: None (grayscale) ✅
# → CEUS: None (grayscale) ✅

# 2. Preprocess
self.image_viewer.set_stacks(bmode, ceus_preprocessed, fps, ceus_is_preprocessed=True)
# → B-mode: None (grayscale) ✅
# → CEUS: magma ✅
```

## Validation

### Test 1: Lancement
```bash
python ceus_app_pyqt/launch.py
```
**Résultat:** ✅ Pas d'erreur de colormap

### Test 2: Load DICOM
```
Fichier → Load DICOM → data/a_aixplorerdcm
```
**Résultat:** ✅ Images affichées correctement

### Test 3: Preprocessing
```
Analyse → Detect Flash → Preprocess
```
**Résultat:** ✅ CEUS passe en magma

## PyQtGraph Colormap API

### Colormaps Disponibles
```python
# Liste complète
pg.colormap.listMaps()
# → ['viridis', 'plasma', 'inferno', 'magma', 'cividis', 
#    'turbo', 'twilight', 'coolwarm', 'hot', 'cool', ...]
```

### Utilisation
```python
# Option 1: Colormap nommée
cmap = pg.colormap.get('magma')
image_view.setColorMap(cmap)

# Option 2: Défaut (grayscale)
image_view.setColorMap(None)

# Option 3: Custom LUT
lut = np.array([[i, i, i] for i in range(256)])
image_view.setColorMap(pg.ColorMap(pos=np.linspace(0, 1, 256), color=lut))
```

## Comparaison Notebook vs UI

### Notebook (matplotlib)
```python
# Grayscale
ax.imshow(img, cmap='gray')

# Magma
ax.imshow(img_preprocessed, cmap='magma', vmin=vmin, vmax=vmax)
```

### UI (PyQtGraph)
```python
# Grayscale
image_view.setImage(img)
image_view.setColorMap(None)  # Équivalent à cmap='gray'

# Magma
image_view.setImage(img_preprocessed, autoLevels=True)
image_view.setColorMap(pg.colormap.get('magma'))
```

## Notes Techniques

### PyQtGraph vs Matplotlib
- **Matplotlib**: Supporte `'gray'` et `'grey'`
- **PyQtGraph**: Pas de `'gray'`, utiliser `None` pour grayscale
- **Raison**: PyQtGraph charge les colormaps depuis des fichiers `.npy`

### Fichiers Colormap
```
pyqtgraph/
  colors/
    maps/
      magma.npy ✅
      viridis.npy ✅
      hot.npy ✅
      gray.npy ❌ (n'existe pas)
```

### Solution Alternative
Si vous voulez absolument `'gray'` :
```python
# Créer une colormap grayscale manuellement
pos = np.linspace(0, 1, 256)
colors = np.array([[i, i, i, 255] for i in range(256)])
gray_cmap = pg.ColorMap(pos, colors)
image_view.setColorMap(gray_cmap)
```

## Conclusion

✅ **Problème résolu** : Utilisation de `setColorMap(None)` pour grayscale  
✅ **Rendu identique** : Même apparence que matplotlib `cmap='gray'`  
✅ **Magma OK** : Colormap magma disponible et fonctionnelle  
✅ **Application lancée** : Plus d'erreur au chargement DICOM  

L'application affiche maintenant correctement les images avec les bonnes colormaps ! 🎉
