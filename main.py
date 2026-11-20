#!/usr/bin/env python
"""FreeNodeSpider CLI — AI-powered proxy node crawler.

Usage:
    python main.py                     # run all sites
    python main.py clashmeta           # run single site
    python main.py --max-delay 5000     # override probe latency threshold
    python main.py --help              # show usage
"""
import argparse
import asyncio
import logging
import sys
from dotenv import load_dotenv

from src.config import load_config, save_config
from src.scheduler import Scheduler

# Windows console (GBK) can't encode flag emojis in summary output.
# Force UTF-8 with replacement chars so prints don't crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Surface LLM warnings/errors (provider failures, model not found).
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

load_dotenv()
sys.path.insert(0, ".")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FreeNodeSpider — AI-powered proxy node crawler",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Site name to process (default: all sites in config)",
    )
    parser.add_argument(
        "--max-delay",
        type=int,
        default=None,
        metavar="MS",
        help="Override probe.max_delay_ms for this run (e.g. 3000)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    config = load_config()

    # Persist probe tuning even for single-site runs (merger is skipped there,
    # but settings must survive save_config below).
    if args.max_delay is not None:
        if args.max_delay < 0:
            raise SystemExit("--max-delay must be >= 0")
        config.probe.max_delay_ms = args.max_delay

    scheduler = Scheduler(config)
    results = await scheduler.run(target=args.target)

    # Persist up_date + self-healed patterns
    save_config(config)

    # Exit 1 only when ALL sites failed (some errors like CDN 403 are expected)
    all_failed = all(r.errors and r.articles_processed == 0 for r in results)
    sys.exit(1 if all_failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
