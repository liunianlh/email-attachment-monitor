from __future__ import annotations

import argparse
import json
import os

import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="command-output.json")
    args = parser.parse_args()

    attachment = os.environ["EMAIL_MONITOR_ATTACHMENT"]
    rule_name = os.environ["EMAIL_MONITOR_RULE_NAME"]
    if attachment.lower().endswith((".xlsx", ".xls")):
        dataframe = pd.read_excel(attachment)
    else:
        dataframe = pd.read_csv(attachment)
    payload = {
        "rule": rule_name,
        "attachment": attachment,
        "rows": dataframe.to_dict("records"),
    }
    with open(args.output, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
