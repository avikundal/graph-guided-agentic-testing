"""PR blast-radius reasoning (Part A stretch).

Given the UI selectors / concept keys a code change touches, work out the blast
radius: which UI elements/actions, which discovered (crawler-tested) scenarios,
and which graph-inferred scenarios are at risk.

This module holds the *deterministic* contract-only reasoning so it is testable
without a live graph. `scripts/pr_blast_radius.py` layers the actual Neo4j graph
(what was really discovered/inferred for a given scope/run) on top.
"""
from __future__ import annotations

from ..domain.checkout_contract import INFERENCE_RULES, INTENTS


def _sel_match(a: str, b: str) -> bool:
    a, b = (a or "").lower(), (b or "").lower()
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def concepts_for_selectors(selectors: list[str]) -> set[str]:
    """Map changed CSS/selectors to the canonical concept keys they back."""
    out: set[str] = set()
    for key, spec in INTENTS.items():
        for hint in spec.selector_hints:
            if any(_sel_match(s, hint) for s in selectors):
                out.add(key)
    return out


def scan_diff_for_anchors(diff_text: str) -> tuple[set[str], set[str]]:
    """Best-effort scan of a raw PR diff for known concept keys and selectors."""
    low = (diff_text or "").lower()
    concepts = {k for k in INTENTS if k.lower() in low}
    selectors: set[str] = set()
    for spec in INTENTS.values():
        for hint in spec.selector_hints:
            if hint and hint.lower() in low:
                selectors.add(hint)
    return concepts, selectors


def static_blast_radius(changed_concepts: list[str], changed_selectors: list[str]) -> dict:
    """Contract-only blast radius (no graph needed).

    Returns the impacted concept set, the UI intents/elements that back them,
    and the inferred scenarios whose prerequisites or pivot involve them.
    """
    concepts = set(changed_concepts) | concepts_for_selectors(changed_selectors)
    impacted_intents = [
        {
            "canonical_key": k,
            "human_label": INTENTS[k].human_label,
            "risk": INTENTS[k].risk,
            "selectors": list(INTENTS[k].selector_hints),
        }
        for k in sorted(concepts) if k in INTENTS
    ]
    impacted_scenarios = [
        {
            "key": r["key"],
            "title": r["title"],
            "status": r["status"],
            "depends_on": list(r["requires"]),
            "pivot": r.get("pivot"),
        }
        for r in INFERENCE_RULES
        if (set(r["requires"]) & concepts) or (r.get("pivot") in concepts)
    ]
    return {
        "impacted_concepts": sorted(concepts),
        "impacted_intents": impacted_intents,
        "impacted_inferred_scenarios": impacted_scenarios,
    }
