"""Engine 2 — LLM-over-graph: find what the autonomous crawl missed.

The crawl (browser-use, unleashed) discovers what it stumbles into. This module
is the other half: it reads the knowledge graph — what was discovered and
validated, what the feature is *expected* to have, and what is expected-but-
absent — and asks an LLM to reason about the scenarios the crawl likely MISSED.

This is deliberately the opposite of the crawl: structural, not probabilistic.
It can propose hidden controls (behind a tab/expander), unverified effects (a
control was seen but its result never checked), and edge cases a happy-path crawl
skips (empty cart, max quantity, invalid coupon, remove-last-item). Output is
attributed to the graph and fed back to the crawl as targeted probes.

Deterministic fallback (no LLM key, or a bad response) keeps the loop working.
"""
from __future__ import annotations

import json
from typing import Iterable

from ..config import settings


def expand_from_graph(
    *,
    feature: str,
    state: str,
    observed_concepts: Iterable[str],
    validated_concepts: Iterable[str],
    expected_concepts: Iterable[str],
    absent_concepts: Iterable[str],
    visible_affordances: Iterable[str],
    max_items: int = 6,
) -> list[dict]:
    """Return a list of MISSED-scenario proposals the graph reasons about.

    Each proposal: {title, why, probe, concept}. `probe` is a short natural-
    language instruction the crawl can act on.
    """
    observed = sorted(set(observed_concepts))
    validated = sorted(set(validated_concepts))
    expected = sorted(set(expected_concepts))
    absent = sorted(set(absent_concepts))
    seen_not_validated = [c for c in observed if c not in set(validated)]

    proposals = _llm_expand(
        feature, state, observed, validated, expected, absent,
        list(visible_affordances)[:30], seen_not_validated, max_items,
    )
    if not proposals:
        proposals = _fallback_expand(seen_not_validated, absent, max_items)
    # De-dupe by title, clamp.
    out: list[dict] = []
    seen_titles: set[str] = set()
    for p in proposals:
        title = (p.get("title") or "").strip()
        if not title or title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())
        out.append({
            "title": title[:90],
            "why": (p.get("why") or "").strip()[:160],
            "probe": (p.get("probe") or title).strip()[:160],
            "concept": (p.get("concept") or None),
        })
        if len(out) >= max_items:
            break
    return out


def _fallback_expand(seen_not_validated: list[str], absent: list[str], max_items: int) -> list[dict]:
    """Deterministic mirror: surface unverified-but-seen and expected-but-absent
    concepts as missed scenarios, so the loop works with no LLM."""
    out: list[dict] = []
    for c in seen_not_validated:
        out.append({
            "title": f"Verify the effect of {c}",
            "why": f"{c} was seen but its effect was never confirmed this run.",
            "probe": f"Exercise the {c.split('.')[-1].replace('_',' ')} control and confirm the cart/subtotal updates.",
            "concept": c,
        })
    for c in absent:
        out.append({
            "title": f"Probe for expected-but-absent {c}",
            "why": f"{c} is expected for this feature but was never observed — it may be hidden or missing.",
            "probe": f"Look for a {c.split('.')[-1].replace('_',' ')} control (it may be behind a tab/expander) and exercise it.",
            "concept": c,
        })
    return out[:max_items]


def _llm_expand(feature, state, observed, validated, expected, absent, visible, seen_not_validated, max_items) -> list[dict]:
    if not settings.openai_api_key:
        return []
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)
        prompt = f"""
You are the reasoning layer of an agentic UI-testing system for the "{feature}" feature.
An autonomous crawler just explored it and recorded what it found in a knowledge graph.
Your job: find what the crawler MISSED — scenarios that SHOULD be tested but were not.

Current state: {state}
Concepts the crawler exercised and VALIDATED: {validated}
Concepts it SAW but did NOT verify the effect of: {seen_not_validated}
Concepts EXPECTED for this feature (domain knowledge): {expected}
Expected but NEVER observed this run (possible hidden/missing): {absent}
Controls visible right now: {visible}

Return ONLY a JSON array of up to {max_items} of the most valuable MISSED scenarios.
Each object: {{"title": str, "why": str, "probe": str, "concept": str|null}}
- "probe" is a short instruction a browser agent can follow to test it.
- "concept" is the canonical concept key if one applies, else null.
Focus on: effects seen-but-unverified; expected-but-absent controls likely hidden
behind a tab/expander; and edge cases a happy-path crawl skips (empty cart, max
quantity, invalid coupon, remove the last item, change quantity then re-check
subtotal). NEVER propose final payment / placing an order.
"""
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=900,
        )
        content = resp.choices[0].message.content or "[]"
        start, end = content.find("["), content.rfind("]")
        if start >= 0 and end >= start:
            content = content[start:end + 1]
        data = json.loads(content)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except Exception:
        return []
    return []
