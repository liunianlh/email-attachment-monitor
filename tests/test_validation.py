from __future__ import annotations

from pathlib import Path

import pandas as pd

from email_monitor.validation import TemplateValidationError, parse_template, validate_dataframe


def test_parse_template_and_validate_strict_range(tmp_path: Path) -> None:
    template_file = tmp_path / "template.xlsx"
    pd.DataFrame(
        {
            "supplier_name": ["A", "B"],
            "order_amount": [100.0, 200.0],
            "order_date": ["2026-06-08", "2026-06-09"],
        }
    ).to_excel(template_file, index=False)

    spec = parse_template(template_file)

    validate_dataframe(
        pd.DataFrame(
            {
                "supplier_name": ["C"],
                "order_amount": [150.0],
                "order_date": ["2026-06-08"],
            }
        ),
        spec,
    )

    try:
        validate_dataframe(
            pd.DataFrame(
                {
                    "supplier_name": ["C"],
                    "order_amount": [300.0],
                    "order_date": ["2026-06-10"],
                }
            ),
            spec,
        )
    except TemplateValidationError as exc:
        assert "order_amount" in str(exc)
        assert "row 2" in str(exc)
    else:
        raise AssertionError("expected strict range validation failure")


def test_validate_dataframe_reports_missing_column(tmp_path: Path) -> None:
    template_file = tmp_path / "template.xlsx"
    pd.DataFrame({"supplier_name": ["A"], "order_amount": [100.0]}).to_excel(
        template_file,
        index=False,
    )
    spec = parse_template(template_file)

    try:
        validate_dataframe(pd.DataFrame({"supplier_name": ["A"]}), spec)
    except TemplateValidationError as exc:
        assert "missing columns: order_amount" in str(exc)
    else:
        raise AssertionError("expected missing column failure")
