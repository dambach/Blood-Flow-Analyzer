# ✨ CEUS Analyzer v0.2.0 - Améliorations UI

## 🎯 Résumé des Améliorations

L'interface a été mise à jour pour une **visualisation fidèle au notebook** avec un panneau dual view (B-mode + CEUS) et des colormaps adaptées.

---

## 🖼️ Panneau Dual View

### Avant
- Une seule vue (CEUS uniquement)
- B-mode ignoré

### Maintenant ✨
```
┌─────────────────────────────────────────┐
│  B-mode (gauche)  │  CEUS (droite)     │
│     Vert           │    Orange           │
│   Colormap gray    │  Colormap gray/magma│
└─────────────────────────────────────────┘
│  ▶  Frame: ══════════════ 0 / 640 (0.00s)│
```

**Fonctionnalités:**
- ✅ **B-mode + CEUS côte à côte** : Visualisation simultanée
- ✅ **Synchronisation parfaite** : Même frame dans les deux vues
- ✅ **Lecture vidéo** : Bouton ▶/⏸ pour play/pause
- ✅ **Labels intelligents** :
  - `B-mode` (vert) si disponible, grisé sinon
  - `CEUS (raw)` (orange) pour données brutes
  - `CEUS (preprocessed)` (orange clair) après traitement

---

## 🎨 Colormaps du Notebook

L'UI utilise maintenant **exactement les mêmes colormaps** que le notebook :

| Type | Colormap | Quand |
|------|----------|-------|
| **B-mode** | `gray` | Toujours |
| **CEUS raw** | `gray` | Après chargement DICOM |
| **CEUS preprocessed** | `magma` | Après Preprocessing |

### Exemple Workflow

```
1. Load DICOM
   ├─ B-mode: gray ✓
   └─ CEUS: gray ✓

2. Detect Flash
   ├─ B-mode: gray ✓
   └─ CEUS: gray ✓

3. Preprocess
   ├─ B-mode: gray ✓
   └─ CEUS: magma ✓✨  (change!)

4. Motion Correction
   ├─ B-mode: gray ✓
   └─ CEUS: magma ✓
```

---

## 🔧 Orientation Corrigée

Les images sont maintenant affichées dans la **bonne orientation** (comme dans le notebook).

**Problème résolu:**
- PyQtGraph et matplotlib ont des conventions différentes
- Solution: transposition automatique `(T, H, W)` → `(T, W, H)`

---

## 📁 Path par Défaut

Le dialogue "Load DICOM" s'ouvre maintenant **directement dans `data/`** :

```python
# Avant: s'ouvrait dans le home directory
file_path = QFileDialog.getOpenFileName(self, "Select DICOM", str(Path.home()))

# Maintenant: s'ouvre dans data/
default_path = Path(__file__).parent.parent.parent.parent / "data"
file_path = QFileDialog.getOpenFileName(self, "Select DICOM", str(default_path))
```

**Avantages:**
- ✅ Accès direct aux fichiers de test
- ✅ Moins de clics pour charger un DICOM
- ✅ Fallback intelligent si `data/` n'existe pas

---

## 🚀 Comment Tester

### 1. Lancer l'application
```bash
cd /Users/damienbachasson/GitHub_repos/Blood-Flow-Analyzer
source .venv/bin/activate
python ceus_app_pyqt/launch.py
```

### 2. Charger un DICOM
```
Fichier → Load DICOM (ou Ctrl+O)
→ Le dialogue s'ouvre dans data/
→ Sélectionner a_aixplorerdcm ou b_00010230
```

### 3. Vérifier la visualisation
```
✓ B-mode visible à gauche (gray)
✓ CEUS visible à droite (gray)
✓ Les deux vues sont synchronisées
✓ Slider fonctionne
✓ Bouton ▶ lance la lecture
```

### 4. Preprocessing
```
Analyse → Detect Flash
Analyse → Preprocess
→ Vérifier que CEUS passe en colormap magma ✨
→ Label devient "CEUS (preprocessed)"
```

---

## 📊 Comparaison Visuelle

### Notebook (cellule 8)
```python
# Raw frame
ax.imshow(img_raw, cmap='gray')

# Preprocessed frame
ax.imshow(img_pre, cmap='magma', vmin=vmin, vmax=vmax)
```

### UI PyQt6 (maintenant)
```python
# Raw CEUS → gray
image_view.setColorMap(pg.colormap.get('gray'))

# Preprocessed CEUS → magma
image_view.setColorMap(pg.colormap.get('magma'))
```

**Résultat: Rendu identique ! 🎨**

---

## 🎯 Raccourcis Clavier

| Touche | Action |
|--------|--------|
| `Ctrl+O` | Load DICOM |
| `Ctrl+D` | Detect Flash |
| `Ctrl+P` | Preprocess |
| `Ctrl+M` | Motion Correction |
| `Space` | Play/Pause (si focus sur slider) |
| `←` / `→` | Frame précédente/suivante |

---

## 🐛 Bugs Corrigés

1. ✅ **Orientation images**: Correction transposition PyQtGraph
2. ✅ **B-mode ignoré**: Maintenant affiché dans panneau gauche
3. ✅ **Colormap fixe**: Dynamique selon preprocessing state
4. ✅ **Path DICOM**: S'ouvre dans `data/` par défaut

---

## 📝 Notes Techniques

### Architecture ImageViewerWidget

```python
class ImageViewerWidget:
    def __init__(self):
        self.bmode_view = pg.ImageView()  # Vue gauche
        self.ceus_view = pg.ImageView()   # Vue droite
        self.play_btn = QPushButton("▶")  # Lecture
        self.frame_slider = QSlider()     # Navigation
    
    def set_stacks(self, bmode, ceus, fps, ceus_is_preprocessed):
        # Configure colormaps selon état
        if ceus_is_preprocessed:
            self.ceus_view.setColorMap(pg.colormap.get('magma'))
        else:
            self.ceus_view.setColorMap(pg.colormap.get('gray'))
        
        self.bmode_view.setColorMap(pg.colormap.get('gray'))
```

### Synchronisation Bidirectionnelle

```
Slider change
    ↓
Update both views
    ↓
Emit frame_changed signal

ImageView timeline change
    ↓
Update slider
    ↓
Emit frame_changed signal
```

---

## ✅ Checklist Validation

- [x] B-mode visible si présent dans DICOM
- [x] CEUS visible toujours
- [x] Synchronisation B-mode ↔ CEUS
- [x] Colormap gray pour données brutes
- [x] Colormap magma après preprocessing
- [x] Lecture vidéo synchronisée
- [x] Path par défaut vers data/
- [x] Labels dynamiques selon état
- [x] Orientation correcte des images

---

**L'interface est maintenant fidèle au notebook ! 🎉**

Pour toute question, voir `CHANGELOG.md` pour les détails techniques.
