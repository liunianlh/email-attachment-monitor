from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


class TemplateValidationError(RuntimeError):
    pass


def parse_template(path: str | Path) -> dict[str, Any]:
    template_path = Path(path)
    dataframe = _read_template(template_path)
    columns = []
    for column in dataframe.columns:
        series = dataframe[column].dropna()
        column_spec: dict[str, Any] = {"name": str(column), "type": _infer_type(series)}
        if column_spec["type"] == "number":
            numeric = pd.to_numeric(series, errors="coerce")
            column_spec["min"] = float(numeric.min())
            column_spec["max"] = float(numeric.max())
        elif column_spec["type"] == "date":
            dates = pd.to_datetime(series, errors="coerce", format="mixed")
            column_spec["min"] = dates.min().strftime("%Y-%m-%d")
            column_spec["max"] = dates.max().strftime("%Y-%m-%d")
        columns.append(column_spec)
    return {"columns": columns}


def validate_dataframe(dataframe: pd.DataFrame, spec: dict[str, Any]) -> None:
    expected_columns = [column["name"] for column in spec.get("columns", [])]
    missing = [column for column in expected_columns if column not in dataframe.columns]
    if missing:
        raise TemplateValidationError(f"missing columns: {', '.join(missing)}")
    errors: list[str] = []
    for column_spec in spec.get("columns", []):
        name = column_spec["name"]
        series = dataframe[name]
        if column_spec["type"] == "number":
            _validate_number(name, series, column_spec, errors)
        elif column_spec["type"] == "date":
            _validate_date(name, series, column_spec, errors)
    if errors:
        raise TemplateValidationError("; ".join(errors))


def _read_template(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise TemplateValidationError(f"unsupported template type: {path.suffix}")


def _infer_type(series: pd.Series) -> str:
    if series.empty:
        return "text"
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().all():
        return "number"
    dates = pd.to_datetime(series, errors="coerce", format="mixed")
    if dates.notna().all():
        return "date"
    return "text"


def _validate_number(
    name: str,
    series: pd.Series,
    spec: dict[str, Any],
    errors: list[str],
) -> None:
    numeric = pd.to_numeric(series, errors="coerce")
    for index, value in numeric.items():
        original = series.loc[index]
        if pd.isna(original):
            continue
        row_number = int(index) + 2
        if pd.isna(value):
            errors.append(f"row {row_number} {name}: expected number")
            continue
        if value < spec["min"] or value > spec["max"]:
            errors.append(
                f"row {row_number} {name}: {value} outside [{spec['min']}, {spec['max']}]"
            )


def _validate_date(
    name: str,
    series: pd.Series,
    spec: dict[str, Any],
    errors: list[str],
) -> None:
    dates = pd.to_datetime(series, errors="coerce", format="mixed")
    min_date = pd.Timestamp(spec["min"])
    max_date = pd.Timestamp(spec["max"])
    for index, value in dates.items():
        original = series.loc[index]
        if pd.isna(original):
            continue
        row_number = int(index) + 2
        if pd.isna(value):
            errors.append(f"row {row_number} {name}: expected date")
            continue
        if value < min_date or value > max_date:
            errors.append(
                f"row {row_number} {name}: {value.strftime('%Y-%m-%d')} outside "
                f"[{spec['min']}, {spec['max']}]"
            )
