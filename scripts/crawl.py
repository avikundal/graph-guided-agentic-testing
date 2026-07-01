#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.config import settings
from src.explorer.graph_guided_explorer import GraphGuidedExplorer


for _name in ("browser_use", "browser-use", "Agent", "BrowserSession", "service", "tools"):
    logging.getLogger(_name).setLevel(logging.ERROR)


async def run(args):
    product_url = args.url or settings.target_product_url
    if not args.url:
        print(f"[crawl] no --url passed; falling back to TARGET_PRODUCT_URL = {product_url}")
    print(f"[crawl] crawling: {product_url}  (project_id={args.project_id})")
    explorer = GraphGuidedExplorer(
        product_url=product_url,
        tenant_id=args.tenant_id,
        project_id=args.project_id,
        feature_key=args.feature_key,
        headless=not args.headed,
        enable_living_graph=args.enable_living_graph,
        reset_graph=args.reset_graph,
        reset_cart=args.reset_cart,
        debug=args.debug,
    )
    report = await explorer.run()
    print(report)


def main():
    p = argparse.ArgumentParser(description="Graph-guided autonomous explorer for Amazon checkout")
    p.add_argument("--url", default=None)
    p.add_argument("--tenant-id", default="default")
    p.add_argument("--project-id", default="amazon_demo")
    p.add_argument("--feature-key", default="amazon_checkout")
    p.add_argument("--reset-graph", action="store_true")
    p.add_argument("--reset-cart", action="store_true", help="Empty the Amazon cart before the run so cart-delta provenance is clean.")
    p.add_argument("--enable-living-graph", action="store_true")
    p.add_argument("--headed", action="store_true", help="Show browser window. Default is headless.")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
