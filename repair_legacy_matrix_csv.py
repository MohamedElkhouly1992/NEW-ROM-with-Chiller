from __future__ import annotations

"""Repair mixed-width matrix_ml_dataset.csv files produced by older memory-safe builds.

Usage:
    python repair_legacy_matrix_csv.py --input matrix_ml_dataset.csv --output matrix_ml_dataset_repaired.csv

The legacy failure mode is recognizable when baseline rows have the header width while
subsequent degraded rows contain the full newer solver schema. The script infers the
full degraded schema from the installed engine, maps each row by its width, and writes
one stable union-schema CSV.
"""

import argparse
import csv
from pathlib import Path

import pandas as pd

from hvac_v3_engine import BuildingSpec, HVACConfig, _load_base_weather, simulate_combo


def infer_degraded_schema() -> list[str]:
    bldg = BuildingSpec()
    cfg = HVACConfig(years=1)
    weather, _ = _load_base_weather("synthetic", None, None, None, 42, cfg.TIME_STEP_HOURS)
    daily, _, _ = simulate_combo("S0", "Mild", "C0_Baseline", bldg, cfg, weather, random_state=42)
    return [str(c) for c in daily.columns]


def repair(input_path: Path, output_path: Path) -> dict:
    full_cols = infer_degraded_schema()
    with input_path.open("r", newline="", encoding="utf-8-sig") as src:
        reader = csv.reader(src)
        legacy_header = next(reader)
        union = list(full_cols)
        for c in legacy_header:
            if c not in union:
                union.append(c)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_rows = degraded_rows = unknown_rows = 0
        with output_path.open("w", newline="", encoding="utf-8") as dst:
            writer = csv.DictWriter(dst, fieldnames=union)
            writer.writeheader()
            for row in reader:
                if len(row) == len(legacy_header):
                    record = dict(zip(legacy_header, row))
                    baseline_rows += 1
                elif len(row) == len(full_cols):
                    record = dict(zip(full_cols, row))
                    degraded_rows += 1
                else:
                    unknown_rows += 1
                    # Preserve what can be safely mapped to the full schema.
                    record = dict(zip(full_cols[: len(row)], row))
                writer.writerow({c: record.get(c, "") for c in union})

    return {
        "baseline_width_rows": baseline_rows,
        "full_width_rows": degraded_rows,
        "unexpected_width_rows": unknown_rows,
        "output_columns": len(union),
        "output": str(output_path),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    result = repair(Path(args.input), Path(args.output))
    print(result)


if __name__ == "__main__":
    main()
