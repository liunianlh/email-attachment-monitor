from __future__ import annotations

import argparse
import json

from email_monitor.app import create_app
from email_monitor.config import load_config
from email_monitor.db import init_db
from email_monitor.pipeline import run_pipeline_once


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="email-monitor")
    parser.add_argument("--config", default="config.local.json", help="local config path")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="initialize SQLite database")
    subparsers.add_parser("run-once", help="run the email pipeline once")
    serve_parser = subparsers.add_parser("serve", help="start the local dashboard")
    serve_parser.add_argument("--no-scheduler", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.command == "init-db":
        init_db(config.database_path)
        print(f"initialized database: {config.database_path}")
        return 0
    if args.command == "run-once":
        summary = run_pipeline_once(config)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    if args.command == "serve":
        app = create_app(config, start_scheduler=not args.no_scheduler)
        app.run(host=config.web_host, port=config.web_port, debug=True, use_reloader=True)
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
