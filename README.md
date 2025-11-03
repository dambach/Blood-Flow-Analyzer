# Blood-Flow-Analyzer
This app analyzes raw time-intensity data generated from contrast-enhanced ultrasound images of the costal diaphragm muscle. Empirical and theoretical parameters related to blood flow and volume are extracted from the raw data and a report is generated.

## Python implementation

A Dash application that recreates and extends the original Shiny workflow is
available in `app.py`. It adds a DICOM preprocessing pipeline that can:

- load multi-frame CEUS clips (`pydicom`),
- crop the ultrasound viewport using presets or a manually drawn rectangle,
- detect the flash frame automatically with manual override,
- capture rectangular regions of interest for the chest wall, diaphragm, and
  liver, and
- export a `example_TIC.csv` compatible with the original R app.

The analysis tab mirrors the BFI computation from the Shiny version.

### Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Navigate to http://127.0.0.1:8050/ to interact with the interface.
