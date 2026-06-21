#!/usr/bin/env python
"""FreeNodeSpider CLI — AI-powered proxy node crawler.

Usage:
    python main.py                     # run all sites
    python main.py clashmeta           # run single site
    python main.py --help              # show usage
"""
import argparse
import asyncio
import sys
from dotenv import load_dotenv

from src.config import load_config, save_config
from src.scheduler import Scheduler

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
    return parser.parse_args()


async def main():
    args = parse_args()
    config = load_config()

    scheduler = Scheduler(config)
    results = await scheduler.run(target=args.target)

    # Persist up_date + self-healed patterns
    save_config(config)

    # Exit code: 0 if all succeeded, 1 if any errors
    errors = [r for r in results if r.errors]
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    asyncio.run(main())
