# CEUS Analyzer - Workflow Temporel Optimisé

## 📋 Vue d'ensemble

L'application CEUS Analyzer a été optimisée pour suivre un workflow clinique standard avec **temporal crop** avant motion correction.

## 🔄 Nouveau Workflow Optimisé

### 1️⃣ **Load DICOM** 📂
- Sélectionner le fichier DICOM directement
- Choisir le preset de crop spatial : **LOGIC**, Aixplorer, ou No Crop
- **LOGIC** (recommandé) : Moitié droite, -10% haut/bas (calcul dynamique)

### 2️⃣ **Set Flash Frame** ⚡
- Naviguer dans les frames avec le slider
- **Appuyer sur 'f'** pour marquer la frame du flash (injection de contraste)
- Ou utiliser le widget "Set Flash Frame"

### 3️⃣ **Temporal Crop (Flash + 30s)** ✂️
**NOUVEAU : Étape clé du workflow !**
- Cliquer sur **"✂️ Temporal Crop (Flash+30s)"**
- Par défaut : Flash frame + 30 secondes
- Durée ajustable : 5-120 secondes
- Inclut quelques frames **avant** le flash (baseline)
- **🔀 Motion correction appliquée AUTOMATIQUEMENT** après le crop

**Pourquoi c'est important ?**
- ✅ **Calcul plus rapide** : 30s au lieu de 2+ minutes
- ✅ **Meilleur alignement** : Moins de variations anatomiques
- ✅ **Focus clinique** : Phases wash-in, peak, wash-out
- ✅ **Baseline préservée** : Permet la normalisation

### 4️⃣ **Draw ROIs** ✏️
- Sélectionner le label du ROI : **liver**, **dia**, **cw**
- L'outil rectangle est **AUTO-SÉLECTIONNÉ**
- Dessiner jusqu'à 3 ROIs (un par label)
- Tous les ROIs restent visibles

### 5️⃣ **Compute TIC** 📊
- Calcule les courbes TIC pour tous les ROIs visibles
- Affiche un graphique unique : **mean ± std** pour chaque ROI
- Affiche les propriétés des ROIs (area, dimensions, intensités)

### 6️⃣ **Export TIC** 💾
- Données temporelles : mean, min, max, std par frame
- Propriétés des ROIs : area, perimeter, bbox, intensités
- Logs de motion correction : shifts par frame

## 🎯 Avantages du Nouveau Workflow

### Avant (❌ Problématique)
```
Load DICOM → Crop spatial → Motion correction (2+ min) → Flash frame → ROIs → TIC
```
**Problèmes :**
- Motion correction sur tout le clip (lent)
- Perte de contexte anatomique
- Artefacts de bord importants
- Faux alignements (variations de contraste)

### Après (✅ Optimisé)
```
Load DICOM → Crop spatial → Flash frame → Temporal Crop (30s) → Motion correction automatique → ROIs → TIC
```
**Avantages :**
- Motion correction sur fenêtre réduite (rapide)
- Alignement plus précis (moins de variations)
- Focus sur phase cliniquement pertinente
- Baseline préservée pour normalisation

## 🔬 Détails Techniques

### Temporal Crop
```python
# Calcul automatique de la fenêtre temporelle
baseline_frames = min(5, flash_frame * 0.1)  # 5 frames ou 10% du flash
start_frame = flash_frame - baseline_frames
end_frame = flash_frame + (duration_seconds * fps)

# Exemple avec flash_frame=10, duration=30s, fps=13
# → baseline_frames = 1
# → start_frame = 9
# → end_frame = 10 + 390 = 400
# → Total: ~391 frames (30.1s)
```

### Motion Correction
- **Algorithme** : Phase cross-correlation (scikit-image)
- **Précision** : Sub-pixel (upsample_factor=10)
- **Interpolation** : Cubique (order=3)
- **Conversion** : Float64 → uint8 (préserve les couleurs RGB)
- **Export** : 
  - CSV des shifts (frame, shift_y, shift_x)
  - Vidéos MP4 (before/after) pour comparaison

### Correction des Couleurs
Le problème de teinte verdâtre a été résolu :
```python
# scipy_shift retourne float64
aligned_frames = scipy_shift(frame, shift=(dy, dx), order=3)

# IMPORTANT : Convertir en uint8 pour préserver les couleurs RGB
self.frames_cropped = np.clip(aligned_frames, 0, 255).astype(np.uint8)
```

## 🎹 Raccourcis Clavier

| Touche | Action |
|--------|--------|
| **f** | Marquer la frame actuelle comme flash frame |
| **Space** | Play/Pause de la vidéo |
| **Ctrl/Cmd+Z** | Annuler le dernier ROI dessiné |

## 📁 Fichiers Exportés

### TIC Time-Series
```
TIC_TimeSeries_YYYYMMDD_HHMMSS.csv
```
Colonnes : Frame, Time_s, liver_mean, liver_min, liver_max, liver_std, dia_mean, ...

### ROI Properties
```
ROI_Properties_YYYYMMDD_HHMMSS.csv
```
Colonnes : ROI_Label, ROI_Color, Area_pixels, Width, Height, Perimeter, BBox, Mean_Intensity, ...

### Motion Correction
```
Motion_Shifts_YYYYMMDD_HHMMSS.csv
Video_BEFORE_MotionCorrection_YYYYMMDD_HHMMSS.mp4
Video_AFTER_MotionCorrection_YYYYMMDD_HHMMSS.mp4
```

## 🧪 Tests

### Test Automatique
```bash
source .venv/bin/activate
python test_temporal_workflow.py
```

### Test Manuel
1. Lancer l'application : `python napari_ceus_app.py`
2. Load DICOM : Sélectionner `data/00010230` avec preset LOGIC
3. Naviguer jusqu'à la frame d'injection et appuyer sur **'f'**
4. Cliquer sur **"✂️ Temporal Crop (Flash+30s)"**
5. Attendre la motion correction automatique
6. Dessiner 3 ROIs (liver, dia, cw)
7. Compute TIC
8. Export CSV

## 📊 Résultats Attendus

### Temporal Crop
- **Input** : 120 frames (9.2s @ 13 FPS)
- **Output** : ~391 frames (30.1s @ 13 FPS) après flash frame
- **Baseline** : 1-5 frames avant le flash

### Motion Correction
- **Shifts typiques** : 0-5 pixels (respiration, mouvement du patient)
- **Temps de calcul** : 10-30s pour 400 frames (vs 2+ min pour tout le clip)
- **Qualité** : Sub-pixel precision (±0.1 pixel)

## 🐛 Dépannage

### Problème : "Set flash frame first"
**Solution** : Naviguer dans les frames et appuyer sur **'f'** ou utiliser le widget

### Problème : Couleurs verdâtres après motion correction
**Solution** : Déjà corrigé ! Conversion uint8 appliquée automatiquement

### Problème : ROIs disparaissent
**Solution** : Déjà corrigé ! Mécanisme save/restore implémenté

### Problème : Temporal crop trop court
**Solution** : Ajuster le paramètre "Duration (s)" dans le widget (5-120s)

## 📚 Références

- **Phase Cross-Correlation** : scikit-image.registration.phase_cross_correlation
- **YCbCr → RGB** : ITU-R BT.601 standard
- **CEUS Guidelines** : EFSUMB Guidelines 2020
- **Motion Correction** : Optical Flow / Phase Correlation methods

## 🎯 Prochaines Étapes

1. ✅ Workflow temporel optimisé
2. ✅ Motion correction automatique
3. ✅ Correction des couleurs
4. 🔜 Pharmacokinetic parameters (PE, TTP, AUC, WiR, WoR)
5. 🔜 Flash frame normalization (baseline subtraction)
6. 🔜 Perfusion ratios entre ROIs

---

**Version** : 2.0 (Temporal Workflow Optimized)
**Date** : Novembre 2025
**Author** : CEUS Analyzer Team
