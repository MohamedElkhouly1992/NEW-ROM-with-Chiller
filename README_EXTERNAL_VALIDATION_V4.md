# HVAC ROM-Degradation Suite v4 — Chiller & External Validation Extension

This version extends the existing HVAC v3 dynamic RC core-solver bundle without replacing the central solver architecture.

## New capabilities

### 1. Chiller Calculation tab
The new **Chiller Calculation** tab provides an auditable calculation of:

- cooling-load part-load ratio (PLR),
- aged COP,
- fouling-adjusted COP,
- ambient-temperature COP modifier,
- optional part-load COP modifier,
- chiller electric power,
- total plant power,
- plant COP,
- kW/ton,
- specific plant electricity use,
- isolated fouling-induced energy and COP penalties.

The tab can also post-process the official ROM time-series output and export:

- `chiller_calculation_timeseries.csv`
- `chiller_calculation_summary.csv`

### 2. External Published Validation tab
The new **External Published Validation** tab is configured for the LBNL/DOE Chiller Plant FDD dataset. Upload:

- `ChillerPlant.csv`
- `ChillerPlant_coolingtower_fouling_095.csv`
- `ChillerPlant_coolingtower_fouling_080.csv`
- `ChillerPlant_coolingtower_fouling_065.csv`

The app auto-detects documented LBNL points including:

- `CWL_SEC_LOAD`
- `CHL_POW*`
- `CT_POW*`
- `CDWL_PM_POW*`
- `CWL_PRI_PM_POW*`
- `CWL_SEC_PM_POW*`

It calculates:

- seasonal chiller COP,
- seasonal plant COP,
- specific plant electricity consumption,
- kW/ton,
- fouling-induced energy penalty,
- chiller and plant COP degradation,
- load-bin validation at PLR <0.25, 0.25–0.50, 0.50–0.75, and >=0.75,
- MAE,
- RMSE,
- NRMSE,
- MAPE,
- NMBE,
- R²,
- degradation-response slope agreement.

The tab also estimates a best-fit `FOULING_COP_BETA` for the isolated external fouling benchmark.

## Important scientific interpretation

The LBNL 95%, 80%, and 65% fouling cases multiply the cooling-tower heat-transfer coefficient by those factors. They are **not** mapped directly to the manuscript's Mild, Moderate, Severe, and High multi-mechanism severity scenarios.

External validation therefore isolates fouling and compares normalized degradation response. It does not compare absolute annual MWh between the Egyptian educational building and the Chicago LBNL office building.

The calibrated beta should only be transferred into the complete ROM after confirming the chosen mapping between heat-transfer-coefficient loss and normalized ROM fouling state.

## 3. Configurable fouling-to-COP sensitivity
`HVACConfig` now contains:

```python
FOULING_COP_BETA: float = 0.45
```

The legacy value 0.45 is preserved by default. The cooling COP function now uses this configurable parameter instead of a hard-coded constant.

## 4. Stable matrix CSV schema
The memory-safe CSV writer has been corrected. Earlier builds could write the baseline with 148 columns and degraded scenarios with 163 columns. The updated writer maintains a union schema and expands earlier rows in a streaming pass when new columns appear.

For old files, use:

```bash
python repair_legacy_matrix_csv.py --input matrix_ml_dataset.csv --output matrix_ml_dataset_repaired.csv
```

## Run

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Recommended external-validation workflow

1. Run the ROM and retain the clean/baseline result.
2. Open **External Published Validation**.
3. Upload the four LBNL chiller-plant CSV files.
4. Use hourly aggregation initially.
5. Exclude very low cooling loads using the minimum-load filter.
6. Compare the legacy/current beta against the external response.
7. Run beta calibration.
8. Inspect load-bin agreement and slope agreement before transferring the calibrated beta to the full ROM.
9. Re-run the full ROM with the selected beta and regenerate final manuscript tables and figures.
