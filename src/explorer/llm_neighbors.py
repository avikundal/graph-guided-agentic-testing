from __future__ import annotations

import json
from typing import Iterable

from ..config import settings
from ..domain.checkout_contract import SOURCE_GRAPH, SOURCE_LLM
from .semantic_normalizer import NormalizedIntent, SemanticNormalizer


FALLBACK_SUGGESTIONS = [
    {
        "canonical_key": "action.change_quantity",
        "title": "Changing quantity should recalculate subtotal",
        "aliases": ["quantity", "qty", "increase quantity", "change quantity"],
        "risk": "mutating_click",
        "priority": 0.86,
        "source": SOURCE_GRAPH,
    },
    {
        "canonical_key": "action.delete_item",
        "title": "Deleting an item should update subtotal",
        "aliases": ["delete", "remove", "remove from cart"],
        "risk": "destructive_click",
        "priority": 0.78,
        "source": SOURCE_GRAPH,
    },
    {
        "canonical_key": "action.save_for_later",
        "title": "Save for later should move item out of active cart",
        "aliases": ["save for later"],
        "risk": "mutating_click",
        "priority": 0.72,
        "source": SOURCE_GRAPH,
    },
    {
        "canonical_key": "capability.promo_code",
        "title": "Promo or gift code capability may exist",
        "aliases": ["promo", "coupon", "gift card"],
        "risk": "observe_only",
        "priority": 0.55,
        "source": SOURCE_GRAPH,
    },
    {
        "canonical_key": "domain.final_order_boundary",
        "title": "Final order boundary must be detected and protected",
        "aliases": ["place order", "pay now", "confirm purchase"],
        "risk": "forbidden_click",
        "priority": 0.99,
        "source": SOURCE_GRAPH,
    },
]


class NeighborGenerator:
    """LLM + graph neighbor generator with graph-state signature caching."""

    def __init__(self):
        self.generated_signatures: set[str] = set()
        self.total_generated = 0
        self.total_llm_calls = 0
        self.total_fallback_calls = 0

    def signature(self, *, observed_concepts: Iterable[str], current_state: str, visible_affordances: list[str]) -> str:
        visible_keys = sorted(set(v.lower()[:40] for v in visible_affordances if v))[:25]
        concepts = sorted(set(observed_concepts))
        return json.dumps({"state": current_state, "concepts": concepts, "visible": visible_keys}, sort_keys=True)

    def generate(
        self,
        *,
        observed_concepts: Iterable[str],
        current_state: str,
        visible_affordances: list[str],
        max_neighbors: int,
        normalizer: SemanticNormalizer,
    ) -> list[NormalizedIntent]:
        sig = self.signature(observed_concepts=observed_concepts, current_state=current_state, visible_affordances=visible_affordances)
        if sig in self.generated_signatures:
            return []
        self.generated_signatures.add(sig)

        suggestions = _llm_suggestions(observed_concepts, current_state, visible_affordances, max_neighbors)
        if suggestions:
            self.total_llm_calls += 1
        if not suggestions:
            self.total_fallback_calls += 1
            suggestions = FALLBACK_SUGGESTIONS[:max_neighbors]
        intents: list[NormalizedIntent] = []
        for s in suggestions[:max_neighbors]:
            source = s.get("source") or SOURCE_LLM
            ni = normalizer.normalize_suggestion(s, source=source)
            if ni:
                intents.append(ni)
        intents = normalizer.dedupe(intents)
        self.total_generated += len(intents)
        return intents


def generate_neighbor_intents(
    *,
    observed_concepts: Iterable[str],
    current_state: str,
    visible_affordances: list[str],
    max_neighbors: int,
    normalizer: SemanticNormalizer,
) -> list[NormalizedIntent]:
    # Compatibility wrapper for older tests/imports.
    return NeighborGenerator().generate(
        observed_concepts=observed_concepts,
        current_state=current_state,
        visible_affordances=visible_affordances,
        max_neighbors=max_neighbors,
        normalizer=normalizer,
    )


def _llm_suggestions(observed_concepts: Iterable[str], current_state: str, visible_affordances: list[str], max_neighbors: int) -> list[dict]:
    if not settings.openai_api_key:
        return []
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        prompt = f"""
You are helping an agentic UI testing explorer. Generate {max_neighbors} nearby checkout/cart scenarios as JSON.
Current state: {current_state}
Observed concepts: {sorted(set(observed_concepts))}
Visible affordances: {visible_affordances[:30]}

Return ONLY a JSON array. Each object must have:
canonical_key, title, aliases, risk, priority.
Use canonical_key only from:
action.change_quantity, action.delete_item, action.save_for_later, capability.promo_code, action.proceed_to_checkout, domain.checkout_boundary, domain.final_order_boundary.
Risk must be one of: safe_click, mutating_click, destructive_click, forbidden_click, observe_only.
Never propose clicking place order/pay now/confirm purchase. final_order_boundary is observe_only/forbidden only.
Prioritize actions that are likely missed by a crawler but structurally implied by cart facts.
"""
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=900,
        )
        content = resp.choices[0].message.content or "[]"
        start = content.find("[")
        end = content.rfind("]")
        if start >= 0 and end >= start:
            content = content[start:end + 1]
        data = json.loads(content)
        if isinstance(data, list):
            for d in data:
                d["source"] = SOURCE_LLM
            return [d for d in data if isinstance(d, dict)]
    except Exception:
        return []
    return []
