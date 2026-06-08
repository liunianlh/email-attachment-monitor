from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class NormalizedData:
    csv_path: Path
    dataframe: pd.DataFrame


class TransformError(RuntimeError):
    pass


def normalize_attachment(
    source_path: str | Path,
    transform_config: dict[str, Any],
    output_dir: str | Path,
) -> NormalizedData:
    source = Path(source_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    dataframe = _read_table(source, transform_config)
    dataframe = dataframe.dropna(how="all")
    dataframe = _extract_fields(dataframe, transform_config.get("extract_fields"))
    dataframe = dataframe.rename(columns=dict(transform_config.get("field_mapping", {})))
    dataframe = _clean_dataframe(dataframe, transform_config.get("cleaning", {}))
    dataframe = dataframe.dropna(how="all")
    csv_path = output / f"{source.stem}.normalized.csv"
    dataframe.to_csv(csv_path, index=False, encoding="utf-8")
    return NormalizedData(csv_path=csv_path, dataframe=dataframe)


def _read_table(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    suffix = path.suffix.lower()
    header_row = int(config.get("header_row", 0))
    skip_rows = config.get("skip_rows", config.get("skiprows"))
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, header=header_row, skiprows=skip_rows)
    if suffix == ".csv":
        encoding = config.get("encoding", "auto")
        if encoding == "auto":
            for candidate in ("utf-8-sig", "utf-8", "gb18030", "latin1"):
                try:
                    return pd.read_csv(
                        path,
                        header=header_row,
                        skiprows=skip_rows,
                        encoding=candidate,
                    )
                except UnicodeDecodeError:
                    continue
            raise TransformError(f"cannot decode csv file: {path}")
        return pd.read_csv(path, header=header_row, skiprows=skip_rows, encoding=encoding)
    raise TransformError(f"unsupported attachment type: {path.suffix}")


def _extract_fields(dataframe: pd.DataFrame, fields: list[Any] | None) -> pd.DataFrame:
    if not fields:
        return dataframe.copy()
    columns: list[Any] = []
    for field in fields:
        if isinstance(field, int):
            try:
                columns.append(dataframe.columns[field])
            except IndexError as exc:
                raise TransformError(f"column index out of range: {field}") from exc
        else:
            if field not in dataframe.columns:
                raise TransformError(f"missing source column: {field}")
            columns.append(field)
    return dataframe.loc[:, columns].copy()


def _clean_dataframe(dataframe: pd.DataFrame, cleaning: dict[str, Any]) -> pd.DataFrame:
    result = dataframe.copy()
    for column in cleaning.get("amount_fields", []):
        if column in result.columns:
            result[column] = result[column].map(_clean_amount)
    for column in cleaning.get("date_fields", []):
        if column in result.columns:
            parsed = pd.to_datetime(result[column], errors="coerce", format="mixed")
            result[column] = parsed.dt.strftime("%Y-%m-%d")
    return result


def _clean_amount(value: Any) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"[¥￥$,，\s]", "", text)
    try:
        return float(text)
    except ValueError as exc:
        raise TransformError(f"invalid amount value: {value}") from exc
