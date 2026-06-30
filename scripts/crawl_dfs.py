#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from src.config import settings
from src.explorer.graph_guided_explorer import GraphGuidedExplorer

import logging

logging.getLogger("browser_use").setLevel(logging.ERROR)
logging.getLogger("browser-use").setLevel(logging.ERROR)
logging.getLogger("Agent").setLevel(logging.ERROR)
logging.getLogger("BrowserSession").setLevel(logging.ERROR)
logging.getLogger("service").setLevel(logging.ERROR)
logging.getLogger("tools").setLevel(logging.ERROR)

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
        max_steps=args.max_steps,
        max_neighbors=args.max_neighbors,
        headless=not args.headed,
        allow_mutating=not args.no_mutating,
        allow_destructive=not args.no_destructive,
        enable_living_graph=args.enable_living_graph,
        reset_graph=args.reset_graph,
        reset_cart=args.reset_cart,
        debug=args.debug,
        autonomous=args.autonomous,
    )
    report = await explorer.run()
    print(report)


def main():
    p = argparse.ArgumentParser(description="Graph-guided DFS frontier explorer for Amazon checkout")
    p.add_argument("--url", default=None)
    p.add_argument("--tenant-id", default="default")
    p.add_argument("--project-id", default="amazon_demo")
    p.add_argument("--feature-key", default="amazon_checkout")
    p.add_argument("--max-steps", type=int, default=24)
    p.add_argument("--max-neighbors", type=int, default=5)
    p.add_argument("--reset-graph", action="store_true")
    p.add_argument("--reset-cart", action="store_true", help="Empty the Amazon cart before the run so cart-delta provenance is clean.")
    p.add_argument("--enable-living-graph", action="store_true")
    p.add_argument("--headed", action="store_true", help="Show browser window. Default is headless.")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--no-mutating", action="store_true", help="Do not execute mutating clicks like quantity changes/save-for-later.")
    p.add_argument("--no-destructive", action="store_true", help="Do not execute destructive clicks like delete/remove (default: they ARE executed and verified, then the cart is restored).")
    p.add_argument("--autonomous", action="store_true", help="Phase 1b: let browser-use explore each state autonomously (it chooses its own actions) under the deny-list safety veto, instead of the catalogue-driven DFS.")
    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
