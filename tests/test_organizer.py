from __future__ import annotations

from pathlib import Path

import pandas as pd

import pytest

from email_monitor.organizer import (
    OrganizerError,
    organize_attachment_data,
    organize_attachment_files,
)


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


def test_organize_attachment_files_combines_multiple_files_and_sheets(tmp_path: Path) -> None:
    first = tmp_path / "first.xlsx"
    second = tmp_path / "second.xlsx"
    output_dir = tmp_path / "organized"
    with pd.ExcelWriter(first) as writer:
        pd.DataFrame(
            [
                ["序号", "姓名", "身份证号", "联系电话"],
                [1, "张三", "11010519491231002X", "13800138000"],
            ]
        ).to_excel(writer, sheet_name="一组", index=False, header=False)
        pd.DataFrame(
            [
                ["序号", "姓名", "身份证号", "联系电话"],
                [1, "李四", "110105199001011234", "13900139000"],
            ]
        ).to_excel(writer, sheet_name="二组", index=False, header=False)
    pd.DataFrame(
        [
            ["序号", "姓名", "身份证号", "联系电话"],
            [1, "王五", "110105198806153219", "13700137000"],
        ]
    ).to_excel(second, index=False, header=False)

    result_path = organize_attachment_files([first, second], output_dir)

    result = pd.read_excel(result_path, dtype=str)
    assert result_path == output_dir / "汇总整理后.xlsx"
    assert result.to_dict("records") == [
        {
            "保单号": "13800138000",
            "客户姓名": "张三",
            "客户身份证号": "11010519491231002X",
        },
        {
            "保单号": "13900139000",
            "客户姓名": "李四",
            "客户身份证号": "110105199001011234",
        },
        {
            "保单号": "13700137000",
            "客户姓名": "王五",
            "客户身份证号": "110105198806153219",
        },
    ]


def test_organize_attachment_data_ignores_empty_excel_sheets(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    output_dir = tmp_path / "organized"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame(
            [
                ["个检家庭医生申请表", None, None, None, None],
                ["序号", "客户姓名", "性别", "联系方式", "身份证号"],
                [1, "张元礼", "男", "15393703876", "41012119730925585X"],
                [2, "郝凯", "男", "15513383155", "140502198204183011"],
            ]
        ).to_excel(writer, sheet_name="Sheet1", index=False, header=False)
        pd.DataFrame().to_excel(writer, sheet_name="Sheet2", index=False, header=False)

    result_path = organize_attachment_data(source, output_dir)

    result = pd.read_excel(result_path, dtype=str)
    assert result.to_dict("records") == [
        {
            "保单号": "15393703876",
            "客户姓名": "张元礼",
            "客户身份证号": "41012119730925585X",
        },
        {
            "保单号": "15513383155",
            "客户姓名": "郝凯",
            "客户身份证号": "140502198204183011",
        },
    ]
