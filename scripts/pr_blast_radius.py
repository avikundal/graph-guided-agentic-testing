#!/usr/bin/env python3
"""PR blast-radius (Part A stretch).

Given a PR that touches the chosen feature's UI (expressed as changed selectors,
changed concept keys, or a raw diff), print the blast radius:

  - UI elements / actions at risk
  - discovered scenarios at risk (what the crawler actually validated)
  - inferred scenarios at risk (what the graph reasoned about)

Deterministic contract reasoning works with no graph; if Neo4j is configured it
is layered on to show what was *actually* discovered/inferred for this scope.

Examples:
  ./.venv/bin/python scripts/pr_blast_radius.py --changed-selector "#add-to-cart-button"
  ./.venv/bin/python scripts/pr_blast_radius.py --changed-concept action.proceed_to_checkout
  ./.venv/bin/python scripts/pr_blast_radius.py --diff my_pr.diff
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from src.config import settings
from src.graph.blast_radius import scan_diff_for_anchors, static_blast_radius
from src.graph.store import GraphStore


def main():
    p = argparse.ArgumentParser(description="PR blast-radius for the modeled feature")
    p.add_argument("--tenant-id", default="default")
    p.add_argument("--project-id", default="amazon_demo")
    p.add_argument("--feature", default="amazon_checkout")
    p.add_argument("--changed-selector", action="append", default=[], help="A CSS/selector the PR touches (repeatable)")
    p.add_argument("--changed-concept", action="append", default=[], help="A canonical concept key the PR touches (repeatable)")
    p.add_argument("--diff", default=None, help="Path to a PR diff file to scan for known selectors/concepts")
    args = p.parse_args()

    concepts = set(args.changed_concept)
    selectors = set(args.changed_selector)
    if args.diff:
        text = Path(args.diff).read_text(encoding="utf-8", errors="ignore")
        dc, ds = scan_diff_for_anchors(text)
        concepts |= dc
        selectors |= ds

    if not concepts and not selectors:
        print("No changed selectors/concepts provided. Use --changed-selector / --changed-concept / --diff.")
        return

    static = static_blast_radius(list(concepts), list(selectors))

    print("=" * 72)
    print("PR BLAST RADIUS")
    print("=" * 72)
    print(f"Changed selectors: {', '.join(sorted(selectors)) or 'none'}")
    print(f"Changed concepts:  {', '.join(sorted(concepts)) or 'none'}")
    print(f"Impacted concepts (resolved): {', '.join(static['impacted_concepts']) or 'none'}")
    print()

    print("UI elements / actions at risk (from the feature contract):")
    for it in static["impacted_intents"]:
        print(f"  - {it['canonical_key']} ({it['human_label']}, risk={it['risk']}) selectors={it['selectors']}")
    if not static["impacted_intents"]:
        print("  - none")
    print()

    print("Inferred scenarios at risk (graph reasoning rules):")
    for sc in static["impacted_inferred_scenarios"]:
        print(f"  - {sc['key']} [{sc['status']}] :: {sc['title']}  (depends_on={sc['depends_on']}, pivot={sc['pivot']})")
    if not static["impacted_inferred_scenarios"]:
        print("  - none")
    print()

    # Layer the real graph (what was actually discovered/inferred for this scope).
    feature_key = args.feature if args.feature.startswith("feature.") else f"feature.{args.feature}"
    scope = {"tenant_id": args.tenant_id, "project_id": args.project_id, "feature_key": feature_key}
    if not settings.neo4j_enabled:
        print("(Neo4j not configured — showing contract-only blast radius.)")
        return
    store = GraphStore()
    try:
        store.verify()
        live = store.blast_radius(scope, static["impacted_concepts"], list(selectors))
    except Exception as exc:
        print(f"(Graph query failed: {str(exc)[:160]} — contract-only result shown above.)")
        store.close()
        return
    store.close()
    if not live:
        return

    print("Discovered scenarios actually at risk (from the live graph):")
    for it in live["intents"]:
        tag = "validated" if it["validated"] else ("executed" if it["executed"] else "observed")
        print(f"  - {it['key']} ({it['label']}) [{tag}] selector={it['selector']} source={it['source']}")
    if not live["intents"]:
        print("  - none recorded in this scope yet")
    print()

    print("Inferred scenarios actually written for this scope (at risk):")
    for sc in live["scenarios"]:
        print(f"  - {sc['key']} [{sc['status']}] :: {sc['title']}  (depends_on={sc['depends_on']})")
    if not live["scenarios"]:
        print("  - none recorded in this scope yet")


if __name__ == "__main__":
    main()
