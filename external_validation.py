from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

import numpy as np
import pandas as pd

KW_PER_TON = 3.5168525
LBNL_FOULING_FACTORS = {
    "Fault-free": 1.00,
    "Fouling 95% HTC": 0.95,
    "Fouling 80% HTC": 0.80,
    "Fouling 65% HTC": 0.65,
}


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(s).upper()).strip("_")


def _numeric(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for c in cols:
        out[c] = pd.to_numeric(df[c], errors="coerce")
    return out


def detect_lbnl_chiller_columns(df: pd.DataFrame) -> Dict[str, object]:
    """Auto-detect the documented LBNL chiller-plant abbreviations with tolerant naming."""
    norm_map = {c: _norm(c) for c in df.columns}

    def exactish(token: str) -> Optional[str]:
        token = _norm(token)
        for c, n in norm_map.items():
            if n == token or token in n:
                return c
        return None

    def family(token: str) -> list[str]:
        token = _norm(token)
        hits = []
        for c, n in norm_map.items():
            if token in n:
                hits.append(c)
        return hits

    timestamp = None
    for token in ["TIMESTAMP", "DATETIME", "DATE_TIME", "TIME"]:
        timestamp = exactish(token)
        if timestamp:
            break

    return {
        "timestamp": timestamp,
        "cooling_load_w": exactish("CWL_SEC_LOAD"),
        "outdoor_temp_f": exactish("OA_TEMP"),
        "chiller_power_kw": family("CHL_POW"),
        "tower_power_kw": family("CT_POW"),
        "condenser_pump_power_kw": family("CDWL_PM_POW"),
        "primary_pump_power_kw": family("CWL_PRI_PM_POW"),
        "secondary_pump_power_kw": family("CWL_SEC_PM_POW"),
    }


def prepare_lbnl_chiller_case(
    df: pd.DataFrame,
    case_label: str,
    htc_factor: float,
    min_cooling_load_kw: float = 50.0,
    resample_rule: str = "1h",
) -> Tuple[pd.DataFrame, dict]:
    if df is None or df.empty:
        raise ValueError("The uploaded LBNL case is empty.")
    cols = detect_lbnl_chiller_columns(df)
    if not cols["cooling_load_w"]:
        raise ValueError("Could not detect CWL_SEC_LOAD (secondary-loop cooling load).")
    if not cols["chiller_power_kw"]:
        raise ValueError("Could not detect chiller power columns containing CHL_POW.")

    work = pd.DataFrame(index=df.index)
    q_raw = pd.to_numeric(df[cols["cooling_load_w"]], errors="coerce")
    # Documentation gives W. Keep a defensive magnitude check for already-converted derivatives.
    if q_raw.dropna().abs().median() > 5000:
        work["cooling_load_kw"] = q_raw / 1000.0
    else:
        work["cooling_load_kw"] = q_raw

    def sum_family(key: str) -> pd.Series:
        family_cols = cols.get(key, []) or []
        if not family_cols:
            return pd.Series(0.0, index=df.index)
        return _numeric(df, family_cols).sum(axis=1, min_count=1).fillna(0.0)

    work["chiller_power_kw"] = sum_family("chiller_power_kw")
    work["tower_power_kw"] = sum_family("tower_power_kw")
    work["condenser_pump_power_kw"] = sum_family("condenser_pump_power_kw")
    work["primary_pump_power_kw"] = sum_family("primary_pump_power_kw")
    work["secondary_pump_power_kw"] = sum_family("secondary_pump_power_kw")
    work["plant_power_kw"] = work[[
        "chiller_power_kw", "tower_power_kw", "condenser_pump_power_kw",
        "primary_pump_power_kw", "secondary_pump_power_kw"
    ]].sum(axis=1)

    if cols.get("outdoor_temp_f"):
        tf = pd.to_numeric(df[cols["outdoor_temp_f"]], errors="coerce")
        work["outdoor_temp_c"] = (tf - 32.0) * 5.0 / 9.0

    if cols.get("timestamp"):
        ts = pd.to_datetime(df[cols["timestamp"]], errors="coerce")
        if ts.notna().sum() > len(ts) * 0.5:
            work.index = ts
            work = work.loc[~work.index.isna()].sort_index()
            # Aggregate powers and loads as mean values over the requested interval.
            if resample_rule and len(work) > 1:
                work = work.resample(resample_rule).mean(numeric_only=True)

    active = (work["cooling_load_kw"] >= float(min_cooling_load_kw)) & (work["plant_power_kw"] > 0) & (work["chiller_power_kw"] > 0)
    work = work.loc[active].copy()
    work["chiller_COP"] = work["cooling_load_kw"] / work["chiller_power_kw"]
    work["plant_COP"] = work["cooling_load_kw"] / work["plant_power_kw"]
    work["plant_kW_per_ton"] = work["plant_power_kw"] / (work["cooling_load_kw"] / KW_PER_TON)
    work["SEC_plant"] = work["plant_power_kw"] / work["cooling_load_kw"]
    work["case"] = str(case_label)
    work["htc_factor"] = float(htc_factor)
    work["htc_loss_fraction"] = 1.0 - float(htc_factor)

    qsum = float(work["cooling_load_kw"].sum())
    chsum = float(work["chiller_power_kw"].sum())
    plsum = float(work["plant_power_kw"].sum())
    summary = {
        "case": str(case_label),
        "htc_factor": float(htc_factor),
        "htc_loss_pct": 100.0 * (1.0 - float(htc_factor)),
        "records_used": int(len(work)),
        "mean_cooling_load_kw": float(work["cooling_load_kw"].mean()) if len(work) else np.nan,
        "seasonal_chiller_COP": qsum / chsum if chsum > 0 else np.nan,
        "seasonal_plant_COP": qsum / plsum if plsum > 0 else np.nan,
        "specific_plant_electricity_kW_per_kWcool": plsum / qsum if qsum > 0 else np.nan,
        "mean_plant_kW_per_ton": float(work["plant_kW_per_ton"].mean()) if len(work) else np.nan,
    }
    return work, summary


def add_relative_penalties(summary_df: pd.DataFrame, clean_label: str = "Fault-free") -> pd.DataFrame:
    if summary_df is None or summary_df.empty:
        return pd.DataFrame()
    out = summary_df.copy()
    clean_rows = out[out["case"].astype(str) == str(clean_label)]
    if clean_rows.empty:
        clean_rows = out.loc[out["htc_factor"].idxmax()].to_frame().T
    clean = clean_rows.iloc[0]
    for metric in ["seasonal_chiller_COP", "seasonal_plant_COP", "specific_plant_electricity_kW_per_kWcool", "mean_plant_kW_per_ton"]:
        base = float(clean[metric])
        if not np.isfinite(base) or abs(base) < 1e-12:
            out[f"{metric}_change_pct"] = np.nan
        else:
            out[f"{metric}_change_pct"] = 100.0 * (pd.to_numeric(out[metric], errors="coerce") / base - 1.0)
    # Positive penalty convention for energy and COP deterioration.
    out["plant_energy_penalty_pct"] = out["specific_plant_electricity_kW_per_kWcool_change_pct"]
    out["plant_COP_degradation_pct"] = -out["seasonal_plant_COP_change_pct"]
    out["chiller_COP_degradation_pct"] = -out["seasonal_chiller_COP_change_pct"]
    return out


def load_bin_summary(prepared_cases: Dict[str, pd.DataFrame], capacity_kw: Optional[float] = None) -> pd.DataFrame:
    frames = []
    for label, df in prepared_cases.items():
        if df is None or df.empty:
            continue
        d = df.copy()
        if capacity_kw is None or capacity_kw <= 0:
            cap = max(float(d["cooling_load_kw"].quantile(0.99)), 1.0)
        else:
            cap = float(capacity_kw)
        d["PLR_external"] = d["cooling_load_kw"] / cap
        d["load_bin"] = pd.cut(
            d["PLR_external"],
            bins=[-np.inf, 0.25, 0.50, 0.75, np.inf],
            labels=["<0.25", "0.25-0.50", "0.50-0.75", ">=0.75"],
            right=False,
        )
        for lb, g in d.groupby("load_bin", observed=True):
            qsum = float(g["cooling_load_kw"].sum())
            plsum = float(g["plant_power_kw"].sum())
            chsum = float(g["chiller_power_kw"].sum())
            frames.append({
                "case": label,
                "htc_factor": float(g["htc_factor"].iloc[0]),
                "load_bin": str(lb),
                "records": int(len(g)),
                "seasonal_plant_COP": qsum / plsum if plsum > 0 else np.nan,
                "seasonal_chiller_COP": qsum / chsum if chsum > 0 else np.nan,
                "SEC_plant": plsum / qsum if qsum > 0 else np.nan,
            })
    out = pd.DataFrame(frames)
    if out.empty:
        return out
    # Relative penalties within each load bin against fault-free/highest HTC factor.
    result = []
    for lb, g in out.groupby("load_bin", observed=True):
        g = g.copy()
        base = g.loc[g["htc_factor"].idxmax()]
        for metric in ["seasonal_plant_COP", "seasonal_chiller_COP", "SEC_plant"]:
            b = float(base[metric])
            g[f"{metric}_change_pct"] = 100.0 * (g[metric] / b - 1.0) if abs(b) > 1e-12 else np.nan
        g["plant_energy_penalty_pct"] = g["SEC_plant_change_pct"]
        g["plant_COP_degradation_pct"] = -g["seasonal_plant_COP_change_pct"]
        result.append(g)
    return pd.concat(result, ignore_index=True)


def rom_fouling_response(
    htc_factors: Iterable[float],
    beta: float,
    clean_cop: float = 4.5,
    clean_specific_energy: Optional[float] = None,
) -> pd.DataFrame:
    """Create an isolated ROM fouling response for comparison/calibration.

    The normalized fouling state is defined as d = 1 - HTC_factor for this external
    validation experiment only. It is deliberately separate from the manuscript's
    multi-mechanism severity axis.
    """
    rows = []
    beta = max(float(beta), 0.0)
    clean_cop = max(float(clean_cop), 1e-9)
    clean_specific_energy = float(clean_specific_energy) if clean_specific_energy is not None else 1.0 / clean_cop
    for h in htc_factors:
        h = float(h)
        d = max(0.0, 1.0 - h)
        cop = clean_cop / (1.0 + beta * d)
        sec = clean_specific_energy * (1.0 + beta * d)
        rows.append({
            "htc_factor": h,
            "htc_loss_pct": 100.0 * d,
            "normalized_fouling_state": d,
            "ROM_COP": cop,
            "ROM_COP_degradation_pct": 100.0 * (1.0 - cop / clean_cop),
            "ROM_specific_energy": sec,
            "ROM_energy_penalty_pct": 100.0 * (sec / clean_specific_energy - 1.0),
        })
    return pd.DataFrame(rows)


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    y_true, y_pred = y_true[mask], y_pred[mask]
    if len(y_true) == 0:
        return {"N": 0, "MAE": np.nan, "RMSE": np.nan, "NRMSE_pct": np.nan, "MAPE_pct": np.nan, "NMBE_pct": np.nan, "R2": np.nan}
    err = y_pred - y_true
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mean_true = float(np.mean(y_true))
    nrmse = 100.0 * rmse / abs(mean_true) if abs(mean_true) > 1e-12 else np.nan
    nonzero = np.abs(y_true) > 1e-12
    mape = float(100.0 * np.mean(np.abs(err[nonzero] / y_true[nonzero]))) if nonzero.any() else np.nan
    nmbe = float(100.0 * np.mean(err) / mean_true) if abs(mean_true) > 1e-12 else np.nan
    if len(y_true) >= 2 and np.sum((y_true - mean_true) ** 2) > 1e-12:
        r2 = 1.0 - float(np.sum(err ** 2) / np.sum((y_true - mean_true) ** 2))
    else:
        r2 = np.nan
    return {"N": int(len(y_true)), "MAE": mae, "RMSE": rmse, "NRMSE_pct": nrmse, "MAPE_pct": mape, "NMBE_pct": nmbe, "R2": r2}


def compare_rom_to_external(external_summary: pd.DataFrame, beta: float, target: str = "plant_energy_penalty_pct") -> Tuple[pd.DataFrame, pd.DataFrame]:
    if external_summary is None or external_summary.empty:
        return pd.DataFrame(), pd.DataFrame()
    ext = external_summary.copy()
    rom = rom_fouling_response(ext["htc_factor"].astype(float).tolist(), beta=beta)
    merged = ext.merge(rom, on=["htc_factor", "htc_loss_pct"], how="left")
    if target == "plant_COP_degradation_pct":
        true = pd.to_numeric(merged[target], errors="coerce").values
        pred = pd.to_numeric(merged["ROM_COP_degradation_pct"], errors="coerce").values
        pred_col = "ROM_COP_degradation_pct"
    else:
        true = pd.to_numeric(merged["plant_energy_penalty_pct"], errors="coerce").values
        pred = pd.to_numeric(merged["ROM_energy_penalty_pct"], errors="coerce").values
        pred_col = "ROM_energy_penalty_pct"
    # Exclude clean zero-penalty row from percentage-error metrics/calibration comparison.
    fault_mask = pd.to_numeric(merged["htc_factor"], errors="coerce") < 0.999999
    metric = _metrics(true[fault_mask.values], pred[fault_mask.values])
    metric.update({"target": target, "ROM_prediction_column": pred_col, "beta": float(beta)})
    return merged, pd.DataFrame([metric])


def calibrate_beta(external_summary: pd.DataFrame, target: str = "plant_energy_penalty_pct", beta_min: float = 0.0, beta_max: float = 5.0, steps: int = 5001) -> Tuple[float, pd.DataFrame]:
    if external_summary is None or external_summary.empty:
        raise ValueError("External summary is empty.")
    betas = np.linspace(float(beta_min), float(beta_max), int(max(steps, 10)))
    rows = []
    for b in betas:
        _, m = compare_rom_to_external(external_summary, beta=float(b), target=target)
        row = m.iloc[0].to_dict()
        rows.append(row)
    curve = pd.DataFrame(rows)
    valid = curve[np.isfinite(pd.to_numeric(curve["RMSE"], errors="coerce"))]
    if valid.empty:
        raise ValueError("Could not calibrate beta because no valid fault-case metrics were available.")
    best = valid.loc[valid["RMSE"].astype(float).idxmin()]
    return float(best["beta"]), curve


def slope_agreement(external_summary: pd.DataFrame, beta: float) -> pd.DataFrame:
    if external_summary is None or len(external_summary) < 2:
        return pd.DataFrame()
    ext = external_summary.copy().sort_values("htc_factor", ascending=False)
    x = 1.0 - pd.to_numeric(ext["htc_factor"], errors="coerce").values
    y_ext = pd.to_numeric(ext["plant_energy_penalty_pct"], errors="coerce").values
    y_rom = rom_fouling_response(ext["htc_factor"].astype(float).tolist(), beta=beta)["ROM_energy_penalty_pct"].values
    mask = np.isfinite(x) & np.isfinite(y_ext) & np.isfinite(y_rom)
    if mask.sum() < 2:
        return pd.DataFrame()
    se = float(np.polyfit(x[mask], y_ext[mask], 1)[0])
    sr = float(np.polyfit(x[mask], y_rom[mask], 1)[0])
    return pd.DataFrame([{
        "external_energy_penalty_slope_pct_per_unit_fouling": se,
        "ROM_energy_penalty_slope_pct_per_unit_fouling": sr,
        "slope_difference": sr - se,
        "slope_ratio_ROM_over_external": sr / se if abs(se) > 1e-12 else np.nan,
    }])
