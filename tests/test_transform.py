from __future__ import annotations

from pathlib import Path

import pandas as pd

from email_monitor.transform import normalize_attachment


def test_normalize_excel_extracts_maps_and_cleans_fields(tmp_path: Path) -> None:
    source = tmp_path / "orders.xlsx"
    pd.DataFrame(
        {
            "供应商名称": ["A", None, "B"],
            "金额": ["¥1,200.50", None, "$3,000"],
            "订单日期": ["2026/06/08", None, "2026-06-09"],
            "备注": ["x", None, "y"],
        }
    ).to_excel(source, index=False)

    result = normalize_attachment(
        source,
        {
            "header_row": 0,
            "extract_fields": ["供应商名称", "金额", "订单日期"],
            "field_mapping": {
                "供应商名称": "supplier_name",
                "金额": "order_amount",
                "订单日期": "order_date",
            },
            "cleaning": {
                "amount_fields": ["order_amount"],
                "date_fields": ["order_date"],
            },
        },
        tmp_path / "normalized",
    )

    assert result.csv_path.exists()
    assert list(result.dataframe.columns) == [
        "supplier_name",
        "order_amount",
        "order_date",
    ]
    assert result.dataframe.to_dict("records") == [
        {
            "supplier_name": "A",
            "order_amount": 1200.5,
            "order_date": "2026-06-08",
        },
        {
            "supplier_name": "B",
            "order_amount": 3000.0,
            "order_date": "2026-06-09",
        },
    ]


def test_normalize_csv_supports_column_indexes(tmp_path: Path) -> None:
    source = tmp_path / "orders.csv"
    source.write_text("供应商,金额,日期\nA,10,2026-06-08\n", encoding="utf-8")

    result = normalize_attachment(
        source,
        {
            "header_row": 0,
            "extract_fields": [0, 2],
            "field_mapping": {"供应商": "supplier", "日期": "date"},
            "cleaning": {"date_fields": ["date"]},
        },
        tmp_path / "normalized",
    )

    assert result.dataframe.to_dict("records") == [
        {"supplier": "A", "date": "2026-06-08"}
    ]
