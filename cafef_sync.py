"""CLI for CafeF audited financials and one-day EOD fallback."""

import argparse
from datetime import date
import json
import os

from common.logging_config import configure_logging
from data.cafef.sync import (
    build_default_sync,
    ho_chi_minh_now,
    next_daily_run,
    sync_catalog,
    sync_financial_history,
)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CafeF financial/EOD fallback sync")
    parser.add_argument("--database", default=os.getenv("DATABASE_PATH", "var/market_data.db"))
    parser.add_argument("--requests-per-second", type=float, default=0.5,
                        help="Reserved for compatibility; client defaults to 0.5 req/s")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    subparsers.add_parser("status")
    daily = subparsers.add_parser("eod-fallback")
    daily.add_argument("--date", type=_date)
    financial = subparsers.add_parser("backfill-financials")
    financial.add_argument("--quarters", type=int, default=8)
    return parser


def run(args: argparse.Namespace) -> None:
    client, store, sync = build_default_sync(
        args.database, requests_per_second=args.requests_per_second
    )
    if args.command == "init-db":
        return
    if args.command == "status":
        print(json.dumps(store.statistics(), ensure_ascii=False))
        return
    if args.command == "eod-fallback":
        results = sync.sync_daily(args.date or ho_chi_minh_now().date())
        print(json.dumps([result.__dict__ for result in results]))
        return
    if args.command == "backfill-financials":
        result = sync_financial_history(
            client, store, max_quarters=args.quarters,
        )
        print(json.dumps(result.__dict__))
        return


def main() -> None:
    configure_logging()
    run(build_parser().parse_args())


if __name__ == "__main__":
    main()
