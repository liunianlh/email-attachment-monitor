from __future__ import annotations

from pathlib import Path

import pandas as pd

import pytest

from email_monitor.organizer import OrganizerError, organize_attachment_data


def test_organize_attachment_data_detects_aliases_and_value_patterns(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    output_dir = tmp_path / "organized"
    pd.DataFrame(
        [
            ["职工健康体检意向申报", None, None, None],
            ["序号", "姓名", "身份证号", "联系电话"],
            [1, "张三", "11010519491231002X", "13800138000"],
        ]
    ).to_excel(source, index=False, header=False)

    result_path = organize_attachment_data(source, output_dir)

    result = pd.read_excel(result_path, dtype=str)
    assert result_path == output_dir / "source.整理后.xlsx"
    assert list(result.columns) == ["保单号", "客户姓名", "客户身份证号"]
    assert result.iloc[0].to_dict() == {
        "保单号": "13800138000",
        "客户姓名": "张三",
        "客户身份证号": "11010519491231002X",
    }


def test_organize_attachment_data_does_not_write_when_data_checks_fail(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    output_dir = tmp_path / "organized"
    pd.DataFrame(
        [
            ["标题", None, None, None],
            ["序号", "姓名", "身份证号", "联系电话"],
            [1, "张三", "11010519491231002X", "13800138000"],
            [2, "李四", "not-id-card", "13900139000"],
        ]
    ).to_excel(source, index=False, header=False)

    with pytest.raises(OrganizerError, match="整理数据校验失败"):
        organize_attachment_data(source, output_dir)

    assert not (output_dir / "source.整理后.xlsx").exists()
