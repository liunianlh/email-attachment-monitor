from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd


class OrganizerError(RuntimeError):
    pass


def organize_attachment_data(source_path: str | Path, output_path: str | Path) -> Path:
    return _organize_sources([Path(source_path)], output_path)


def organize_attachment_files(source_paths: list[str | Path], output_path: str | Path) -> Path:
    sources = [Path(source_path) for source_path in source_paths]
    return _organize_sources(sources, output_path)


def _organize_sources(sources: list[Path], output_path: str | Path) -> Path:
    if not sources:
        raise OrganizerError("没有可整理的附件")
    frames = []
    for source in sources:
        for dataframe in _read_tables(source):
            frames.append(_organized_dataframe(dataframe))
    result = pd.concat(frames, ignore_index=True)
    result = _checked_output_dataframe(result)
    output_file = _output_file_path(output_path, sources)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    _write_verified_result(result, output_file)
    return output_file


def _organized_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    columns = _detect_columns(dataframe)
    return pd.DataFrame(
        {
            "保单号": dataframe[columns["policy_no"]].map(_clean_text),
            "客户姓名": dataframe[columns["customer_name"]].map(_clean_text),
            "客户身份证号": dataframe[columns["id_card"]].map(_clean_text),
        }
    )


def _read_tables(path: Path) -> list[pd.DataFrame]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        sheets = pd.read_excel(path, dtype=str, header=None, sheet_name=None)
        tables = [
            _table_with_detected_header(sheet)
            for sheet in sheets.values()
            if not sheet.empty
        ]
        if not tables:
            raise OrganizerError("源文件没有可整理的数据")
        return tables
    if suffix == ".csv":
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin1"):
            try:
                return [
                    _table_with_detected_header(
                        pd.read_csv(path, dtype=str, encoding=encoding, header=None)
                    )
                ]
            except UnicodeDecodeError:
                continue
        raise OrganizerError(f"无法读取 CSV 文件: {path}")
    raise OrganizerError(f"不支持的附件类型: {path.suffix}")


def _table_with_detected_header(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        raise OrganizerError("源文件没有可整理的数据")
    header_row = _detect_header_row(raw)
    columns = _unique_columns([_clean_text(value) for value in raw.iloc[header_row].tolist()])
    dataframe = raw.iloc[header_row + 1 :].copy().reset_index(drop=True)
    dataframe.columns = columns
    return dataframe.dropna(how="all")


def _detect_header_row(raw: pd.DataFrame) -> int:
    best_index = 0
    best_score = -1
    keywords = (
        "姓名",
        "客户",
        "身份证",
        "证件",
        "手机",
        "电话",
        "联系方式",
        "联系电话",
        "保单",
    )
    for index in range(min(len(raw), 10)):
        row_text = " ".join(_clean_text(value) for value in raw.iloc[index].tolist())
        score = sum(1 for keyword in keywords if keyword in row_text)
        if score > best_score:
            best_index = index
            best_score = score
    return best_index if best_score >= 2 else 0


def _unique_columns(columns: list[str]) -> list[str]:
    result: list[str] = []
    seen: dict[str, int] = {}
    for index, column in enumerate(columns):
        name = column or f"未命名列{index + 1}"
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name}_{seen[name]}"
        result.append(name)
    return result


def _detect_columns(dataframe: pd.DataFrame) -> dict[str, str]:
    if dataframe.empty:
        raise OrganizerError("源文件没有可整理的数据")
    phone = _best_column(
        dataframe,
        name_keywords=("手机", "手机号", "电话", "联系方式", "联系电话", "mobile", "phone"),
        validator=_is_phone,
    )
    id_card = _best_column(
        dataframe,
        name_keywords=("身份证", "身份证号", "证件", "证件号", "证件号码", "idcard", "id_card"),
        validator=_is_id_card,
    )
    customer_name = _best_column(
        dataframe,
        name_keywords=("客户姓名", "姓名", "客户", "被保人", "投保人", "name"),
        validator=_looks_like_name,
        excluded={phone, id_card},
    )
    return {
        "phone": phone,
        "id_card": id_card,
        "policy_no": phone,
        "customer_name": customer_name,
    }


def _checked_output_dataframe(result: pd.DataFrame) -> pd.DataFrame:
    checked = result.map(_clean_text)
    checked = checked[checked.apply(lambda row: any(row), axis=1)].copy()
    if checked.empty:
        raise OrganizerError("整理数据校验失败: 没有可输出数据")
    invalid_rows: list[str] = []
    for index, row in checked.iterrows():
        row_number = int(index) + 2
        if not _is_phone(row["保单号"]):
            invalid_rows.append(f"第 {row_number} 行手机号无效")
        if not row["客户姓名"]:
            invalid_rows.append(f"第 {row_number} 行客户姓名为空")
        if not _is_id_card(row["客户身份证号"]):
            invalid_rows.append(f"第 {row_number} 行客户身份证号无效")
    if invalid_rows:
        raise OrganizerError("整理数据校验失败: " + "；".join(invalid_rows[:5]))
    duplicated = checked.duplicated(subset=["保单号", "客户身份证号"], keep=False)
    if duplicated.any():
        raise OrganizerError("整理数据校验失败: 存在重复的手机号和身份证号组合")
    return checked.reset_index(drop=True)


def _write_verified_result(result: pd.DataFrame, output_file: Path) -> None:
    temp_file = output_file.with_name(f".{output_file.stem}.tmp{output_file.suffix}")
    if temp_file.exists():
        temp_file.unlink()
    try:
        if output_file.suffix.lower() == ".csv":
            result.to_csv(temp_file, index=False, encoding="utf-8-sig")
        else:
            result.to_excel(temp_file, index=False)
        written = _read_output_table(temp_file)
        expected = result.astype(str).fillna("").reset_index(drop=True)
        actual = written.astype(str).fillna("").reset_index(drop=True)
        if list(actual.columns) != list(expected.columns):
            raise OrganizerError("整理数据校验失败: 输出列名核对不一致")
        if len(actual) != len(expected):
            raise OrganizerError(
                f"整理数据校验失败: 输出条数核对不一致，预期 {len(expected)} 行，实际 {len(actual)} 行"
            )
        if not actual.equals(expected):
            raise OrganizerError("整理数据校验失败: 输出内容回读核对不一致")
        temp_file.replace(output_file)
    except Exception:
        if temp_file.exists():
            temp_file.unlink()
        raise


def _read_output_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, dtype=str)
    return pd.read_excel(path, dtype=str)


def _best_column(
    dataframe: pd.DataFrame,
    *,
    name_keywords: tuple[str, ...],
    validator: Any,
    excluded: set[str] | None = None,
) -> str:
    excluded = excluded or set()
    scores: list[tuple[float, str]] = []
    for column in dataframe.columns:
        column_name = str(column)
        if column_name in excluded:
            continue
        name_score = _name_score(column_name, name_keywords)
        value_score = _value_score(dataframe[column], validator)
        score = name_score + value_score
        if score > 0:
            scores.append((score, column_name))
    if not scores:
        raise OrganizerError(f"找不到字段: {'/'.join(name_keywords[:2])}")
    scores.sort(reverse=True)
    return scores[0][1]


def _name_score(name: str, keywords: tuple[str, ...]) -> float:
    lowered = name.lower()
    return 3.0 if any(keyword.lower() in lowered for keyword in keywords) else 0.0


def _value_score(series: pd.Series, validator: Any) -> float:
    if validator is None:
        return 0.0
    values = [_clean_text(value) for value in series.dropna().head(50)]
    values = [value for value in values if value]
    if not values:
        return 0.0
    matched = sum(1 for value in values if validator(value))
    ratio = matched / len(values)
    return 5.0 * ratio if ratio >= 0.5 else 0.0


def _clean_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _digits_and_x(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", value)


def _is_phone(value: str) -> bool:
    text = re.sub(r"\D", "", value)
    return re.fullmatch(r"1[3-9]\d{9}", text) is not None


def _is_id_card(value: str) -> bool:
    text = _digits_and_x(value)
    return (
        re.fullmatch(r"\d{17}[\dXx]", text) is not None
        or re.fullmatch(r"\d{15}", text) is not None
    )


def _looks_like_name(value: str) -> bool:
    text = value.strip()
    return re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", text) is not None


def _output_file_path(output_path: str | Path, sources: list[Path]) -> Path:
    output = Path(output_path).expanduser()
    if output.suffix.lower() in {".xlsx", ".xls", ".csv"}:
        return output
    if len(sources) == 1:
        return output / f"{sources[0].stem}.整理后.xlsx"
    return output / "汇总整理后.xlsx"
