# HVAC ROM-Degradation Suite v4.1 — Startup-Fixed Build

## Streamlit Cloud
1. Upload the **contents of this folder** to the root of a GitHub repository.
2. Confirm that `streamlit_app.py` and `requirements.txt` are visible at the repository root.
3. In Streamlit Community Cloud, set the main file path to:
   `streamlit_app.py`
4. Deploy.

The core application starts without CatBoost or SHAP. Those packages are optional because their large binary installations can delay or fail deployment before the UI appears.

## Enable surrogate/SHAP features
Add the two lines from `requirements_ml_optional.txt` to `requirements.txt`, then redeploy. Do this only after the core app is confirmed working.

## Local Windows startup
Run `start_app.bat`.

## Local macOS/Linux startup
Run:
`bash start_app.sh`

## Important
Do not deploy the previous ZIP with an extra `hvac_bundle_work/` directory unless the Streamlit main-file path is explicitly set to `hvac_bundle_work/streamlit_app.py`.
