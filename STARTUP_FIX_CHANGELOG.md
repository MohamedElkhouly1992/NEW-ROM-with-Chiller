# v4.1 Startup Fix

- Flattened deployment structure: `streamlit_app.py` is at ZIP/repository root.
- Removed CatBoost and SHAP from mandatory startup requirements.
- Added `requirements_ml_optional.txt` for optional surrogate/SHAP functionality.
- Added Windows and macOS/Linux startup scripts.
- Kept Python 3.12 deployment target.
- Preserved Chiller Analysis and External Published Validation tabs.
- Preserved the mixed-schema CSV export fix and legacy repair utility.
