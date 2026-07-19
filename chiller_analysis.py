from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Optional

import numpy as np
import pandas as pd

KW_PER_TON = 3.5168525


@dataclass
class ChillerPointInputs:
    cooling_load_kw: float
    nominal_capacity_kw: float
    nominal_cop: float = 4.5
    ambient_temp_c: float = 25.0
    years_in_service: float = 0.0
    cop_aging_rate_per_year: float = 0.005
    fouling_resistance_m2k_w: float = 0.0
    asymptotic_fouling_resistance_m2k_w: float = 2.0e-4
    fouling_cop_beta: float = 0.45
    apply_ambient_derate: bool = True
    ambient_derate_per_c_above_25: float = 0.018
    apply_part_load_modifier: bool = False
    plr_a: float = 0.85
    plr_b: float = 0.25
    plr_c: float = -0.10
    plr_d: float = 0.0
    plr_min_modifier: float = 0.55
    plr_max_modifier: float = 1.15
    pump_power_kw: float = 0.0
    cooling_tower_power_kw: float = 0.0
    other_plant_power_kw: float = 0.0


def _safe_div(a: float, b: float) -> float:
    return float(a / b) if abs(float(b)) > 1e-12 else float("nan")


def calculate_chiller_point(inp: ChillerPointInputs) -> dict:
    """Calculate transparent chiller and plant KPIs using the ROM's fouling-COP relation.

    This calculator intentionally exposes each intermediate term so it can be audited and
    used in external-validation/calibration studies.
    """
    q = max(float(inp.cooling_load_kw), 0.0)
    cap = max(float(inp.nominal_capacity_kw), 1e-9)
    plr = q / cap

    cop_aged = max(0.8, float(inp.nominal_cop) - float(inp.cop_aging_rate_per_year) * max(float(inp.years_in_service), 0.0))
    rf_star = max(float(inp.asymptotic_fouling_resistance_m2k_w), 1e-12)
    fouling_ratio = max(float(inp.fouling_resistance_m2k_w), 0.0) / rf_star
    fouling_denominator = 1.0 + max(float(inp.fouling_cop_beta), 0.0) * fouling_ratio
    cop_after_fouling = cop_aged / fouling_denominator

    ambient_modifier = 1.0
    if bool(inp.apply_ambient_derate):
        ambient_modifier = 1.0 - max(float(inp.ambient_derate_per_c_above_25), 0.0) * max(float(inp.ambient_temp_c) - 25.0, 0.0)
        ambient_modifier = max(0.10, ambient_modifier)

    plr_modifier = 1.0
    if bool(inp.apply_part_load_modifier):
        x = float(np.clip(plr, 0.0, 1.5))
        plr_modifier = inp.plr_a + inp.plr_b * x + inp.plr_c * x * x + inp.plr_d * x * x * x
        plr_modifier = float(np.clip(plr_modifier, inp.plr_min_modifier, inp.plr_max_modifier))

    cop_effective = cop_after_fouling * ambient_modifier * plr_modifier
    cop_effective = float(np.clip(cop_effective, 0.8, max(float(inp.nominal_cop) * 1.25, 0.8)))

    chiller_power_kw = q / cop_effective if q > 0 else 0.0
    plant_power_kw = chiller_power_kw + max(inp.pump_power_kw, 0.0) + max(inp.cooling_tower_power_kw, 0.0) + max(inp.other_plant_power_kw, 0.0)
    plant_cop = q / plant_power_kw if plant_power_kw > 0 else float("nan")
    kw_per_ton = plant_power_kw / (q / KW_PER_TON) if q > 0 else float("nan")
    sec = plant_power_kw / q if q > 0 else float("nan")

    clean_cop_same_conditions = cop_aged * ambient_modifier * plr_modifier
    clean_cop_same_conditions = float(np.clip(clean_cop_same_conditions, 0.8, max(float(inp.nominal_cop) * 1.25, 0.8)))
    clean_chiller_power_kw = q / clean_cop_same_conditions if q > 0 else 0.0
    fouling_energy_penalty_pct = (
        100.0 * (chiller_power_kw / clean_chiller_power_kw - 1.0)
        if clean_chiller_power_kw > 0 else float("nan")
    )
    cop_penalty_pct = (
        100.0 * (cop_effective / clean_cop_same_conditions - 1.0)
        if clean_cop_same_conditions > 0 else float("nan")
    )

    return {
        **asdict(inp),
        "PLR": plr,
        "fouling_ratio_Rf_over_Rfstar": fouling_ratio,
        "COP_aged": cop_aged,
        "fouling_denominator": fouling_denominator,
        "COP_after_fouling": cop_after_fouling,
        "ambient_modifier": ambient_modifier,
        "PLR_modifier": plr_modifier,
        "COP_effective": cop_effective,
        "chiller_power_kw": chiller_power_kw,
        "plant_power_kw": plant_power_kw,
        "plant_COP": plant_cop,
        "kW_per_ton": kw_per_ton,
        "specific_electricity_kW_per_kWcool": sec,
        "clean_COP_same_conditions": clean_cop_same_conditions,
        "fouling_energy_penalty_pct": fouling_energy_penalty_pct,
        "COP_penalty_pct": cop_penalty_pct,
    }


def build_chiller_table_from_rom(
    df: pd.DataFrame,
    nominal_capacity_kw: Optional[float] = None,
    nominal_cop: float = 4.5,
    rf_star: float = 2.0e-4,
    fouling_cop_beta: float = 0.45,
) -> pd.DataFrame:
    """Create publication-oriented chiller KPIs from an existing ROM time-series export."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()

    q_col = next((c for c in ["Q_cool_kw", "Mean Cooling Load kW", "cooling_load_kw"] if c in out.columns), None)
    if q_col is None:
        raise ValueError("No cooling-load column found. Expected Q_cool_kw or an equivalent column.")
    q = pd.to_numeric(out[q_col], errors="coerce").fillna(0.0).clip(lower=0.0)

    if nominal_capacity_kw is None:
        if "Q_cool_des_kw" in out.columns:
            cap_series = pd.to_numeric(out["Q_cool_des_kw"], errors="coerce")
            nominal_capacity_kw = float(cap_series.dropna().median()) if cap_series.notna().any() else max(float(q.max()), 1.0)
        else:
            nominal_capacity_kw = max(float(q.max()), 1.0)
    nominal_capacity_kw = max(float(nominal_capacity_kw), 1e-9)
    out["chiller_PLR"] = q / nominal_capacity_kw

    if "COP_eff" in out.columns:
        cop = pd.to_numeric(out["COP_eff"], errors="coerce")
    else:
        rf = pd.to_numeric(out.get("R_f", 0.0), errors="coerce").fillna(0.0)
        ta = pd.to_numeric(out.get("T_amb_C", 25.0), errors="coerce").fillna(25.0)
        cop = (float(nominal_cop) / (1.0 + float(fouling_cop_beta) * rf / max(float(rf_star), 1e-12))) * (1.0 - 0.018 * (ta - 25.0).clip(lower=0.0))
        cop = cop.clip(lower=0.8, upper=float(nominal_cop))
    out["chiller_COP"] = cop
    out["chiller_power_kw_calc"] = np.where(cop > 0, q / cop, np.nan)

    # Prefer explicit pump/auxiliary powers where available; otherwise infer from period energy.
    if "P_pump_kw" in out.columns:
        pump = pd.to_numeric(out["P_pump_kw"], errors="coerce").fillna(0.0)
    elif "pump_kwh_period" in out.columns and "time_step_hours" in out.columns:
        hrs = pd.to_numeric(out["time_step_hours"], errors="coerce").replace(0, np.nan)
        pump = pd.to_numeric(out["pump_kwh_period"], errors="coerce").fillna(0.0) / hrs
    elif "E_pump" in out.columns:
        # E_pump in the engine is period energy; infer the time step from a field if present, otherwise 24 h.
        hrs = pd.to_numeric(out.get("time_step_hours", 24.0), errors="coerce") if isinstance(out.get("time_step_hours", 24.0), pd.Series) else 24.0
        pump = pd.to_numeric(out["E_pump"], errors="coerce").fillna(0.0) / hrs
    else:
        pump = pd.Series(0.0, index=out.index)

    out["plant_power_kw_calc"] = out["chiller_power_kw_calc"].fillna(0.0) + pump
    positive = q > 1e-9
    out["plant_COP_calc"] = np.where(positive & (out["plant_power_kw_calc"] > 0), q / out["plant_power_kw_calc"], np.nan)
    out["plant_kW_per_ton_calc"] = np.where(positive, out["plant_power_kw_calc"] / (q / KW_PER_TON), np.nan)
    out["specific_electricity_kW_per_kWcool_calc"] = np.where(positive, out["plant_power_kw_calc"] / q, np.nan)
    return out


def summarize_chiller_table(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    q = pd.to_numeric(df.get("Q_cool_kw", 0.0), errors="coerce").fillna(0.0)
    p_ch = pd.to_numeric(df.get("chiller_power_kw_calc", 0.0), errors="coerce").fillna(0.0)
    p_pl = pd.to_numeric(df.get("plant_power_kw_calc", 0.0), errors="coerce").fillna(0.0)
    active = q > 1e-6
    q_sum = float(q[active].sum())
    pch_sum = float(p_ch[active].sum())
    ppl_sum = float(p_pl[active].sum())
    return pd.DataFrame([{
        "active_records": int(active.sum()),
        "mean_cooling_load_kw": float(q[active].mean()) if active.any() else np.nan,
        "seasonal_chiller_COP": _safe_div(q_sum, pch_sum),
        "seasonal_plant_COP": _safe_div(q_sum, ppl_sum),
        "mean_plant_kW_per_ton": float(pd.to_numeric(df.loc[active, "plant_kW_per_ton_calc"], errors="coerce").mean()) if active.any() else np.nan,
        "specific_electricity_kW_per_kWcool": _safe_div(ppl_sum, q_sum),
    }])
