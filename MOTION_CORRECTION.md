# Motion Correction pour CEUS Analysis

## 🔀 Vue d'ensemble

La **motion correction** (correction du mouvement) est essentielle pour l'analyse CEUS car :
- Le diaphragme bouge pendant la respiration
- Les organes abdominaux se déplacent légèrement
- Les ROIs doivent suivre la structure anatomique pour une quantification précise

## 🎯 Algorithme Implémenté

### Phase Cross-Correlation
- **Méthode** : Phase cross-correlation avec précision sub-pixel
- **Bibliothèque** : `skimage.registration.phase_cross_correlation`
- **Précision** : Upsampling factor = 10 (précision de 0.1 pixel)
- **Interpolation** : Cubic (order=3) pour un résultat lisse

### Workflow
1. **Sélection de la frame de référence** : Frame flash ou frame 0
2. **Conversion en niveaux de gris** : Pour images RGB (calcul plus rapide)
3. **Calcul des décalages** : Pour chaque frame vs référence
4. **Application des shifts** : Interpolation cubique sur toutes les couleurs
5. **Export des logs** : CSV avec tous les décalages

## 📊 Utilisation

### Dans l'interface Napari
```
1. Load DICOM → Choisir data/00010230
2. Select Crop Preset → LOGIC
3. Set Flash Frame → Naviguer et marquer avec 'f'
4. Apply Motion Correction → Clic sur bouton 🔀
5. Attendre la progression (affichée dans status bar)
6. Résultat : Frames alignées + CSV des shifts
```

### Test automatisé
```bash
source .venv/bin/activate
python test_motion_correction.py
```

## 📈 Sorties

### Fichiers générés
- **`Motion_Shifts_YYYYMMDD_HHMMSS.csv`** : Log de tous les décalages
  - Colonnes : `Frame`, `Shift_Y`, `Shift_X`
  - Permet analyse statistique post-traitement

### Statistiques affichées
- **Max shift** : Déplacement maximal observé (Y et X)
- **Mean shift** : Déplacement moyen (indicateur de stabilité)
- **Frame de référence** : Frame utilisée comme ancre

## 🔬 Interprétation Clinique

### Décalages normaux
- **Respiration** : 5-15 pixels (typique)
- **Mouvement cardiaque** : 2-5 pixels
- **Péristaltisme** : 3-10 pixels

### Flags de qualité
- ⚠️ **Max shift > 30px** : Mouvement excessif → considérer ré-acquisition
- ✅ **Mean shift < 5px** : Qualité optimale
- ⚠️ **Shifts erratiques** : Patient non coopératif ou artefacts

## 🧪 Validation

### Test avec données réelles
```python
# Test sur data/00010230 (120 frames, 13 FPS)
# Résultats attendus:
# - Max shift Y: 2-10 px (respiration diaphragmatique)
# - Max shift X: 1-5 px (mouvement latéral minimal)
# - Correction visiblement plus stable en lecture vidéo
```

### Comparaison avant/après
```python
# ROI tracking plus stable après correction
# TIC curves moins bruitées
# Paramètres pharmacocinétiques plus reproductibles
```

## 🔧 Paramètres Ajustables

Dans `apply_motion_correction()` :

```python
# Précision (trade-off vitesse/qualité)
upsample_factor=10  # 1-20 (plus haut = plus précis, plus lent)

# Interpolation
order=3  # 0=nearest, 1=linear, 3=cubic, 5=quintic

# Mode de bordure
mode='nearest'  # 'constant', 'reflect', 'wrap'
```

## 📚 Références

1. **Phase Cross-Correlation** : Scikit-image Documentation
   - https://scikit-image.org/docs/stable/api/skimage.registration.html

2. **Motion Correction in Medical Imaging**
   - Rigid registration for ultrasound sequences
   - Sub-pixel alignment for time-series analysis

3. **CEUS Best Practices**
   - EFSUMB Guidelines: Motion correction recommended for quantitative analysis
   - Stabilization improves reproducibility of perfusion parameters

## 🚀 Améliorations Futures

### Non-rigid registration
```python
# Pour mouvements non-linéaires (déformation d'organes)
from skimage.registration import optical_flow_tvl1
# Permet correction plus sophistiquée mais plus lente
```

### ROI tracking automatique
```python
# Suivre automatiquement les ROIs frame-par-frame
# Ajuster position basée sur motion vectors
```

### Quality metrics
```python
# Calculer SSIM (Structural Similarity Index)
# Flaguer frames avec artefacts
# Auto-reject frames hors critères
```

## 💡 Tips

1. **Définir le flash frame AVANT motion correction**
   - Utilise cette frame comme référence stable

2. **Vérifier le CSV des shifts**
   - Patterns réguliers = respiration
   - Pics isolés = artefacts de mouvement

3. **Comparer TIC avant/après**
   - Courbes plus lisses après correction
   - Moins de variations liées au mouvement

4. **Pour recherche**
   - Toujours documenter si motion correction appliquée
   - Inclure stats de shift dans méthodes
