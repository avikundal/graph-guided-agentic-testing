#!/usr/bin/env python3
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.domain.amazon_auth import base_url_for, save_login_session


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Interactive Amazon login; saves session storage state.")
    p.add_argument("--url", default="https://www.amazon.com",
                   help="Any URL on the marketplace you want to test (e.g. https://www.amazon.in/...). "
                        "Log in on the SAME domain as the products you will crawl.")
    args = p.parse_args()
    print(asyncio.run(save_login_session(base_url=base_url_for(args.url))))
