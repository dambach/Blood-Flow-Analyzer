# CEUS Analyzer - Napari Edition

## Version Full Napari

Cette version utilise Napari comme moteur de visualisation principal avec PyQt5 pour les contrôles.

### Lancement

```bash
# Depuis le dossier ceus_app_pyqt
cd ceus_app_pyqt

# Lancer la version Napari pure
python napari_main.py

# Ou via module
python -m napari_main
```

### Architecture

**Visualisation:**
- Deux viewers Napari séparés (B-mode et CEUS)
- Shapes layer Napari pour dessiner des ROI polygonaux interactifs
- Synchronisation automatique des frames entre viewers

**Contrôles Qt5:**
- Boutons de contrôle pour chargement DICOM, détection flash, preprocessing, motion correction
- ROI Manager avec liste des ROI actifs
- TIC Plot (PyQtGraph) synchronisé avec les frames
- Fit Panel pour l'ajustement de modèles wash-in

**Modules Core (réutilisés):**
- `DICOMLoader`: Chargement DICOM (GE, SuperSonic)
- `detect_flash_ceus_refined`: Détection automatique du flash
- `preprocess_ceus`: Preprocessing (log-compression, filtres spatial/temporel)
- `motion_compensate`: Compensation de mouvement
- `ROIManager`: Gestion des ROI polygonaux

### Workflow

1. **Load DICOM**: Charger un fichier DICOM CEUS
2. **Detect Flash**: Détection automatique ou manuelle du frame de flash
3. **Preprocess**: Prétraitement (crop à washout+15s, log-compression, filtres)
4. **Motion Correction** (optionnel): Compensation de mouvement basée sur B-mode
5. **Draw ROI**: Dessiner des polygones ROI sur le viewer CEUS
   - Mode polygon: cliquer pour ajouter des points, fermer le polygone pour valider
6. **Compute TICs**: Calculer les courbes temps-intensité pour chaque ROI
7. **Fit Models** (à venir): Ajuster des modèles wash-in

### Fonctionnalités Napari

- **Shapes Layer**: Dessin interactif de polygones
- **Multi-viewer**: B-mode et CEUS côte à côte
- **Timeline synchronisée**: Les deux viewers suivent la même frame
- **Colormaps**: 'gray' pour raw CEUS, 'magma' pour preprocessed
- **Zoom/Pan**: Contrôles natifs Napari

### Différences avec la version PyQtGraph

| Feature | PyQtGraph Version | Napari Version |
|---------|------------------|----------------|
| Image display | `pg.ImageView` | `napari.Viewer` |
| ROI drawing | Custom `InteractiveImageLabel` | `shapes` layer natif |
| Playback | Custom timer + slider | Napari dims + Qt timer |
| Zoom/Pan | PyQtGraph controls | Napari native |
| Colormaps | PyQtGraph colormaps | Napari colormaps |

### Dépendances

```
PyQt5>=5.15
napari>=0.5.6
pyqtgraph>=0.13.3  # Pour TICPlotWidget
numpy>=1.24.0
scipy>=1.11.0
scikit-image>=0.22.0
pydicom>=2.4.0
matplotlib>=3.8.0
pandas>=2.1.0
```

### Notes Techniques

- **QT_API**: Forcé à 'pyqt5' avant l'import de Napari
- **get_qapp()**: Utilisation de l'app Qt partagée avec Napari (évite les conflits)
- **_qt_viewer**: Embedding du widget Qt interne de Napari (stable sur macOS)
- **Polygon to mask**: Conversion des polygones Napari en masques numpy pour extraction TIC

### TODO

- [ ] Implémenter le fitting de modèles wash-in
- [ ] Export des TIC en CSV
- [ ] Export des résultats de fit
- [ ] Sauvegarde/chargement de sessions (ROIs + paramètres)
- [ ] Documentation utilisateur complète
