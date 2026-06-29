#!/usr/bin/env python3
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.domain.amazon_auth import base_url_for, verify_auth_state


async def main(base_url: str):
    ok, msg = await verify_auth_state(headless=True, base_url=base_url)
    print("\n" + msg)
    print("\n  RESULT:", "SIGNED IN" if ok else "NOT SIGNED IN")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Verify the saved Amazon session on a marketplace.")
    p.add_argument("--url", default="https://www.amazon.com",
                   help="A URL on the marketplace to verify against (e.g. https://www.amazon.in/...).")
    args = p.parse_args()
    asyncio.run(main(base_url_for(args.url)))
