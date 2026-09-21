"""Generate a JSON strategy/data review for the best-covered symbols."""

import argparse
import json
from pathlib import Path

from signal_engine.review import run_review


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("var/market_data.db"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--exchange", choices=("HOSE", "HNX", "UPCOM"))
    parser.add_argument("--output", type=Path, default=Path("var/strategy_review.json"))
    args = parser.parse_args()
    report = run_review(args.database, limit=args.limit, exchange=args.exchange)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output), "symbols": len(report["results"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
