# Chat Export — CEUS App (hybride Napari/Dash) 

> Transcript summary of our session focused on building a CEUS analysis pipeline (stabilization, flash selection, TIC fitting), plus links to all generated artifacts.

---

## Conversation Highlights

- **User:** “J’essaie de faire une app comme narnar pour l’analyse de mes données CEUS. Tu me conseilles quoi comme outil / language?”  
- **Assistant:** Reco initiale: **Streamlit** pour itérations rapides, ou **Napari** si imagerie-centrée; proposition d’architecture hybride (**core Python** + **Napari plugin** + **Dash web**).

- **User:** “Il faudrait aussi pouvoir lire le clip et déterminer la frame du flash puis couper le clip...”  
- **Assistant:** Première version **détection manuelle** + script CLI; ensuite app complète proposée.

- **User:** “Plutôt une détection manuelle.”  
- **Assistant:** Fourni `ceus_flash_manual.py` (mode non interactif + interactif minimal).

- **User:** “Génère le dossier complet.”  
- **Assistant:** Propose choix d’interface (Napari / Streamlit / Dash); utilisateur demande simplicité d’édition → **Streamlit** recommandé, mais discussion parallèle **Napari** pour imagerie.

- **User:** “Dans ce genre de pipeline il faut quoi comme processing en amont ?”  
- **Assistant:** Chaîne de prétraitement: **linearisation intensité → stabilisation → filtrage temporel → normalisation baseline → suppression flash → extraction/fit TIC → QC**.

- **User:** “Des solutions open-source existent ?”  
- **Assistant:** Inventaire: QURE, SimpleITK/ITK, napari, MONAI, etc. Conclusion: combiner briques open-source, pas d’outil CEUS complet.

- **User:** Choix entre **Napari**, **Streamlit**, **Dash** comparés (complexité, perfs, UX).

- **User:** “Architecture hybride — comment structurer ? Une ou plusieurs apps ? Alternatives aux libs listées ?”  
- **Assistant:** Schéma: **ceus_core** (I/O, motion, TIC, maps), **napari_ceus** (QC, ROI, flash), **ceus_dash** (reporting), **data/jobs** partagé. Alternatifs: SimpleITK/ITK, Orthanc, cornerstone3D.

- **User:** “Challenge pour fiabilité et facilité d’usage.”  
- **Assistant:** Renforcement: **environnements pinés**, schéma de données immuable, **QC bloquant**, machine à états, tests goldens, logs, dé-id DICOM.

- **User:** “Inclure l’analyse des TIC comme le script R attaché.”  
- **Assistant:** Implémente `ceus_core_tic.py` (log-normal, gamma variate, LDRW, FPT) avec **multistart** + métriques (MTT, Tp, Baseline, AUC, Volume).

- **User:** “Je veux que tu génères le projet et que tu testes toi-même toutes les sorties.”  
- **Assistant:** Génère projet **ceus_hybrid** (core+CLI) + test synthétique, fichier `tic_fits.json` OK. Artefact: **ceus_hybrid.zip**.

- **User:** “Voilà le DICOM. Implémente stabilisation + outil pour fixer le flash.”  
- **Assistant:** Ajoute `dicom_io.py` (lecture DICOM multi-frame), `motion.py` (stabilisation rigide translation), CLI `stabilize_dicom.py` et `set_flash.py`. Artefact: **ceus_hybrid_v2.zip**.

- **User:** “Images en PhotometricInterpretation: YBR_FULL_422.”  
- **Assistant:** Patch: **YBR → RGB → luma grayscale** (`convert_color_space`), normalisation, fps tags. Conseille `pylibjpeg` pour DICOM compressés.

- **User:** “Si device = Aixplorer, crop: x0=75, x1=425, y0=125, y1=425.”  
- **Assistant:** Ajoute **crop spécifique Aixplorer** (auto-détection Manufacturer/Model, override via CLI `--device` ou `--crop`). Artefact: **ceus_hybrid_v3.zip**.

---

## Artifacts generated

- **Projet complet v1 (core + CLI + TIC)**  
  `ceus_hybrid.zip`

- **Projet v2 (ajout stabilisation + set flash)**  
  `ceus_hybrid_v2.zip`

- **Projet v3 (YBR_FULL_422 + crop Aixplorer)**  
  `ceus_hybrid_v3.zip`

- **Module models TIC (calqué sur R)**  
  `ceus_core_tic.py`

> Les archives v2/v3 incluent les modules précédents; v3 est la plus à jour.

---

## Quick start (local)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# dépendances minimales pour DICOM couleur + stabilisation
pip install numpy scipy matplotlib pydicom pillow pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg
```

**Stabiliser un DICOM (Aixplorer auto-crop)**
```bash
python -m ceus_cli.stabilize_dicom --dicom /path/to/cine.dcm --job CASE001 --device Aixplorer
# ou crop custom :
# python -m ceus_cli.stabilize_dicom --dicom ... --job CASE001 --crop 75 425 125 425
```

**Fixer manuellement le flash**
```bash
python -m ceus_cli.set_flash --job CASE001 --frame 100
```

**Couper 20 s post-flash (existant dans export.py pour arrays; MP4 en option future)**
```python
from ceus_core.export import cut_segment
```

**Fits TIC (ROI → t,I)**
```python
from ceus_core.tic import fit_all
res = fit_all(t, I, n_starts=200, bounds_C=(0,80))
```

---

## Data model (résumé)

```
data/jobs/<JOB>/
  raw/                     # input DICOM/vidéo (si conservé)
  work/
    video_stab.npy         # stack stabilisé float32 (t,y,x)
    motion.json            # shifts & QC (MSE before/after)
    flash.json             # frame, time_sec, source=manual
  results/
    stabilization_qc.png
    flash_trace.png
    segment_post.npz       # si découpé
    tic_fits.json          # paramètres & métriques des modèles
  meta.json                # fps, device, crop, schema_version
```

---

## Notes

- Pour DICOM compressés JPEG/J2K, installer `pylibjpeg` (ou GDCM selon OS).  
- Le crop **Aixplorer** s’applique au **loader** pour homogénéiser l’ensemble du pipeline (stabilisation, flash, TIC).  
- La stabilisation actuelle est **translation**; on peut ajouter un fallback **affine** si nécessaire.

---

*Fin de l’export résumé.*
