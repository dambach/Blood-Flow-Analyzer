# CEUS Analyzer - Changelog

## [Version 0.2.0] - 4 novembre 2025

### 🎨 Améliorations Visualisation

#### Panneau Dual View (B-mode + CEUS)
- ✅ **Affichage côte à côte** : Visualisation simultanée B-mode et CEUS
- ✅ **Synchronisation parfaite** : Les deux vues sont synchronisées sur le même frame
- ✅ **Lecture vidéo** : Bouton play/pause pour lecture synchronisée
- ✅ **Labels dynamiques** : 
  - "B-mode" (vert) quand disponible, grisé sinon
  - "CEUS (raw)" (orange) pour données brutes
  - "CEUS (preprocessed)" (orange clair) après prétraitement

#### Colormaps du Notebook
- ✅ **'gray' pour données brutes** : B-mode et CEUS raw utilisent grayscale (comme notebook)
- ✅ **'magma' pour CEUS prétraité** : CEUS preprocessed utilise colormap magma (comme notebook)
- ✅ **Cohérence visuelle** : Même rendu que dans les notebooks Jupyter

#### Orientation Corrigée
- ✅ **Transposition spatiale** : Correction de l'orientation PyQtGraph vs matplotlib
- ✅ **Convention (T, H, W) → (T, W, H)** : Images affichées dans la bonne orientation
- ✅ **Compatible RGB et grayscale** : Conversion automatique si nécessaire

#### Path par Défaut
- ✅ **Ouverture automatique dans `data/`** : Le dialogue DICOM s'ouvre dans le dossier data
- ✅ **Fallback intelligent** : Si data/ n'existe pas, utilise le home directory

---

## Comparaison avec Notebook

### Affichage Images (cellule 8 - preprocessing before/after)

**Notebook:**
```python
# Raw frames
ax.imshow(img_raw, cmap='gray')

# Preprocessed frames  
ax.imshow(img_pre, cmap='magma', vmin=vmin, vmax=vmax)
```

**UI PyQt6:**
```python
# Raw CEUS
self.ceus_view.setColorMap(pg.colormap.get('gray'))
self.ceus_label.setText("CEUS (raw)")

# Preprocessed CEUS
self.ceus_view.setColorMap(pg.colormap.get('magma'))
self.ceus_label.setText("CEUS (preprocessed)")
```

### Workflow Identique

1. **Load DICOM** → B-mode + CEUS affichés (gray)
2. **Detect Flash** → Flash et washout détectés
3. **Preprocess** → CEUS passe en magma colormap
4. **Motion Correction** → CEUS corrigé reste en magma

---

## Architecture Widget ImageViewer

### Avant (v0.1.0)
```python
class ImageViewerWidget:
    - Single ImageView
    - set_stack(stack, fps)
    - Pas de B-mode
    - Colormap fixe
```

### Après (v0.2.0)
```python
class ImageViewerWidget:
    - Dual ImageView (bmode_view + ceus_view)
    - set_stacks(bmode, ceus, fps, is_preprocessed)
    - B-mode optionnel
    - Colormap dynamique (gray/magma)
    - Synchronisation bidirectionnelle
    - Bouton play/pause
```

---

## Détails Techniques

### Transposition PyQtGraph
```python
# Matplotlib/numpy convention: (T, H, W)
# PyQtGraph convention: (T, W, H) for correct display

# Conversion
bmode_display = np.transpose(bmode_gray, (0, 2, 1))
ceus_display = np.transpose(ceus_gray, (0, 2, 1))
```

### Colormaps PyQtGraph
```python
# PyQtGraph colormap API
pg.colormap.get('gray')   # Grayscale
pg.colormap.get('magma')  # Matplotlib magma
```

### Path Management
```python
# Default to data/ directory
default_path = Path(__file__).parent.parent.parent.parent / "data"
if not default_path.exists():
    default_path = Path.home()
```

---

## Tests de Validation

### Test 1: Chargement DICOM
```bash
python ceus_app_pyqt/launch.py
# → Load DICOM: data/a_aixplorerdcm
# ✅ B-mode visible (gauche, gray)
# ✅ CEUS visible (droite, gray)
# ✅ Slider synchronisé
```

### Test 2: Preprocessing
```bash
# → Detect Flash → Preprocess
# ✅ CEUS passe en magma colormap
# ✅ Label devient "CEUS (preprocessed)"
# ✅ B-mode reste en gray
```

### Test 3: Lecture Vidéo
```bash
# → Clic sur ▶
# ✅ Les deux vues jouent simultanément
# ✅ Slider suit la lecture
# ✅ Frame label mis à jour
```

---

## Fichiers Modifiés

### src/ui/widgets/image_viewer.py
- Ajout dual view (bmode_view + ceus_view)
- Ajout paramètre `ceus_is_preprocessed`
- Implémentation colormaps dynamiques
- Synchronisation des deux vues
- Bouton play/pause

### src/ui/main_window.py
- Path par défaut vers `data/`
- Appels à `set_stacks()` avec flag `ceus_is_preprocessed`
- Gestion B-mode dans toutes les étapes du workflow

---

## Prochaines Étapes (v0.3.0)

### Priorité 1 - ROI Interactif
- [ ] Dessin ROI avec PyQtGraph ROI items
- [ ] Liste ROIs avec couleurs
- [ ] Affichage ROI sur B-mode ET CEUS

### Priorité 2 - TIC Integration
- [ ] Calcul automatique TIC quand ROI ajouté
- [ ] Affichage courbe dans TIC plot
- [ ] Sync TIC click → frame jump

### Priorité 3 - Features
- [ ] Exclusion de frames (touche X)
- [ ] Export CSV
- [ ] Batch processing

---

## Notes Développeur

### Colormap Mapping
| Type | Notebook | PyQtGraph | Usage |
|------|----------|-----------|-------|
| B-mode | `'gray'` | `pg.colormap.get('gray')` | Toujours |
| CEUS raw | `'gray'` | `pg.colormap.get('gray')` | Avant preprocessing |
| CEUS preprocessed | `'magma'` | `pg.colormap.get('magma')` | Après preprocessing |

### PyQtGraph ImageView API
```python
# Set image
image_view.setImage(data, autoRange=True, autoLevels=True)

# Set colormap
image_view.setColorMap(pg.colormap.get('magma'))

# Control playback
image_view.play(fps)
image_view.pause()
image_view.setCurrentIndex(frame_idx)

# Get current state
current_frame = image_view.currentIndex
is_playing = image_view.isPlaying()
```

### Signals
```python
# Frame changed from slider
self.frame_slider.valueChanged.connect(callback)

# Frame changed from ImageView
self.image_view.timeLine.sigPositionChanged.connect(callback)

# Custom signal
self.frame_changed.emit(frame_idx)
```

---

**Version 0.2.0 apporte une visualisation complète et fidèle au notebook !** 🎨✨
