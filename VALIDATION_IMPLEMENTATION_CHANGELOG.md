# Validation / Chiller Extension — Implementation Change Log

## Added
- `chiller_analysis.py`
  - transparent single-point chiller calculation
  - ROM time-series chiller post-processing
  - PLR, COP, chiller power, plant COP, kW/ton, specific electricity
- `external_validation.py`
  - LBNL chiller-plant point auto-detection
  - fault-free and 95/80/65% HTC fouling processing
  - chiller/plant COP and specific-energy calculation
  - normalized fouling penalties
  - load-bin analysis
  - MAE, RMSE, NRMSE, MAPE, NMBE, R²
  - degradation-response slope comparison
  - beta calibration by RMSE minimization
- Streamlit tab: **Chiller Calculation**
- Streamlit tab: **External Published Validation**
- `repair_legacy_matrix_csv.py`
- `README_EXTERNAL_VALIDATION_V4.md`

## Changed
- `HVACConfig` now exposes `FOULING_COP_BETA` with legacy default 0.45.
- `cop_cooling()` uses the configurable beta instead of hard-coded 0.45.
- Main setup UI exposes the fouling-to-COP sensitivity parameter.
- Memory-safe CSV append now uses a stable union schema and streaming schema expansion.

## Verified
- Python compilation completed for all bundle `.py` files.
- Chiller-calculation smoke test passed.
- Configurable-beta cooling COP smoke test passed.
- Stable-schema append test passed for changing DataFrame column sets.
- LBNL parser/calibration workflow passed using a synthetic dataset with documented point names.
- The uploaded legacy `matrix_ml_dataset (1).csv` was diagnostically parsed as 1,825 baseline rows with 148 fields and 29,200 degraded rows with 163 fields. The included repair utility addresses this legacy format.

## Current uploaded ROM reference (before external LBNL validation)
See `example_current_rom_reference/current_uploaded_rom_degradation_reference.csv`.
This file reports the degradation response recovered from the user's uploaded mixed-schema matrix using the full 163-column solver schema for degraded rows.
