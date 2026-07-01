"""Engine 2 - LLM-over-graph: find what the autonomous crawl missed.

The crawl (browser-use, unleashed) discovers what it stumbles into. This module
is the other half: it reads the knowledge graph - what was discovered and
validated, what the feature is expected to have, and what is expected-but-
absent - and asks an LLM to reason about the scenarios the crawl likely MISSED.

This is deliberately the opposite of the crawl: structural, not probabilistic.
It can propose hidden controls (behind a tab/expander), unverified effects (a
control was seen but its result never checked), and edge cases a happy-path crawl
skips (empty cart, max quantity, invalid coupon, remove-last-item). Output is
attributed to the graph and fed back to the crawl as targeted probes.

Deterministic fallback (no LLM key, or a bad response) keeps the loop working.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

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
    graph_context: dict | None = None,
    max_items: int = 6,
    debug: bool = False,
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
    graph_context = graph_context or {}

    # A graph containing only seeded expectations is not evidence. If the crawl
    # never grounded a page or recorded an action, LLM expansion just invents a
    # shopping flow from the contract and wastes browser-use calls.
    if not observed and not (graph_context.get("action_attempts") or []):
        if debug:
            print("[engine2][llm] graph has no observed concepts/actions - skipping expansion")
        return []

    proposals = _llm_expand(
        feature, state, observed, validated, expected, absent,
        list(visible_affordances)[:30], seen_not_validated, graph_context, max_items, debug,
    )
    if not proposals:
        proposals = _fallback_expand(seen_not_validated, absent, max_items)
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


_EDGE_SCENARIOS = {
    "action.delete_item": (
        "Removing the last item should empty the cart and zero the subtotal",
        "Delete the cart item and confirm the subtotal/cart-count updates; if it was the last item, confirm an empty-cart state appears."),
    "action.change_quantity": (
        "Changing quantity should recalculate the subtotal",
        "Increase the item quantity by one and confirm the subtotal recalculates accordingly."),
    "action.save_for_later": (
        "Save-for-later should move the item out of the active cart, and move-to-cart should restore it",
        "Save the item for later, confirm it leaves the active cart, then move it back to the cart."),
    "action.move_to_cart": (
        "Moving a saved item back to the cart should restore it to the active cart",
        "From Saved for later, move the item back to the cart and confirm it reappears in the active cart."),
    "capability.promo_code": (
        "Applying an invalid promo code should show an error, not silently accept it",
        "Open the promo/coupon field, enter an obviously invalid code, apply it, and confirm an error message is shown."),
    "action.proceed_to_checkout": (
        "Proceed to checkout should reach the secure checkout / sign-in boundary",
        "Click Proceed to Checkout and confirm a secure-checkout or sign-in boundary is reached (never place an order)."),
    "domain.final_order_boundary": (
        "The final order-placement control must exist at checkout and must never be auto-clicked",
        "Confirm a final 'Place order' control exists at the checkout boundary; do NOT click it."),
}


def _fallback_expand(seen_not_validated: list[str], absent: list[str], max_items: int) -> list[dict]:
    out: list[dict] = []
    seen_titles: set[str] = set()
    for c in list(seen_not_validated) + list(absent):
        sc = _EDGE_SCENARIOS.get(c)
        if not sc:
            if c.startswith("action.") or c.startswith("capability."):
                name = c.split(".")[-1].replace("_", " ")
                sc = (
                    f"Exercise '{name}' and verify its effect on the cart",
                    f"Exercise the {name} control and confirm the cart/subtotal updates.",
                )
            else:
                continue
        if sc[0].lower() in seen_titles:
            continue
        seen_titles.add(sc[0].lower())
        out.append({
            "title": sc[0],
            "why": f"{c} was present but this behaviour was not verified this run.",
            "probe": sc[1],
            "concept": c,
        })
    return out[:max_items]


def _llm_expand(feature, state, observed, validated, expected, absent, visible, seen_not_validated, graph_context, max_items, debug=False) -> list[dict]:
    if not settings.openai_api_key:
        if debug:
            print("[engine2][llm] no OPENAI_API_KEY - using deterministic fallback")
        return []
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)
        graph_brief = _format_graph_brief(graph_context, observed, validated, absent, seen_not_validated)
        prompt = f"""
You are the reasoning layer of an agentic UI-testing system for the "{feature}" feature.

The crawler just updated a knowledge graph. Your job is NOT to brainstorm from
general ecommerce knowledge. Your job is to reason over graph RELATIONSHIPS and
surface only scenarios that buy new graph knowledge.

Current page/state: {state}
Visible controls right now: {visible}

GRAPH BRIEF
{graph_brief}

HOW TO REASON OVER THE GRAPH
1. Follow causal edges first:
   cause Concept --SHOULD_CAUSE--> effect Concept.
   If the cause is observed but not validated, or the effect was never observed
   after an action attempt, propose the action that can prove the edge.
2. Follow scenario dependencies:
   Scenario --DEPENDS_ON--> Concept.
   If all dependency concepts are observed but the pivot/action concept is not
   validated, propose the missing proving action.
3. Follow action transitions:
   before_state --ActionAttempt--> after_state.
   Prefer actions that caused no meaningful after-state/evidence yet, or actions
   that should reveal a new state/control but have not.
4. Follow probe lifecycle:
   GraphProbe(proposed/executed) --PROBES--> Concept.
   Do not repeat a probe that is already executed unless the action history shows
   it failed to test the intended relationship.
5. Missing expected Concepts matter only when a likely page/state or reveal path
   exists in the graph. Do not propose random shopping-site features.

Return ONLY a JSON array of up to {max_items} of the most valuable MISSED scenarios.
Each object: {{"title": str, "why": str, "probe": str, "concept": str|null}}
- "probe" is a short instruction a browser agent can follow to test it.
- "concept" is the canonical concept key if one applies, else null.
- "why" must cite the graph relationship that makes this valuable, for example
  "action.change_quantity SHOULD_CAUSE domain.subtotal but no validating attempt exists".
Prioritize causal proof, then unvalidated scenario pivots, then hidden/absent
controls with graph evidence. Do not repeat already executed graph probes.
NEVER propose final payment / placing an order.
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
    except Exception as exc:
        if debug:
            print(f"[engine2][llm] call failed ({exc}) - using deterministic fallback")
        return []
    return []


def _format_graph_brief(
    graph_context: dict[str, Any],
    observed: list[str],
    validated: list[str],
    absent: list[str],
    seen_not_validated: list[str],
) -> str:
    concept_map = {
        c.get("key"): c
        for c in graph_context.get("concepts", [])
        if c.get("key")
    }
    lines: list[str] = []

    lines.append("Concept nodes:")
    focus = sorted(set(observed) | set(validated) | set(absent) | set(seen_not_validated))
    for key in focus[:40]:
        c = concept_map.get(key, {})
        states = ",".join(c.get("states") or []) or "-"
        lines.append(
            f"- {key}: expected={_yn(c.get('expected') or key in absent)} "
            f"observed={_yn(key in observed or c.get('observed'))} "
            f"validated={_yn(key in validated or c.get('validated'))} "
            f"states={states} source={c.get('last_source') or '-'}"
        )

    causal = graph_context.get("causal_expectations") or []
    if causal:
        lines.append("Causal edges:")
        for ce in causal[:20]:
            cause = ce.get("cause")
            effect = ce.get("effect")
            cause_state = _concept_status(concept_map, cause, observed, validated)
            effect_state = _concept_status(concept_map, effect, observed, validated)
            lines.append(
                f"- {cause} --SHOULD_CAUSE--> {effect} on {ce.get('state')}; "
                f"cause={cause_state}, effect={effect_state}; {ce.get('title')}"
            )

    scenarios = graph_context.get("scenarios") or []
    if scenarios:
        lines.append("Scenario dependency edges:")
        for sc in scenarios[:20]:
            deps = ", ".join(sc.get("depends_on") or []) or "-"
            lines.append(f"- {sc.get('title') or sc.get('key')} [{sc.get('status')}]: DEPENDS_ON {deps}")

    probes = graph_context.get("graph_probes") or []
    if probes:
        lines.append("Graph probe lifecycle edges:")
        for p in probes[-20:]:
            targets = ", ".join(p.get("probes") or []) or "-"
            lines.append(f"- {p.get('title')} [{p.get('status')}] on {p.get('target_state')}: PROBES {targets}")

    actions = graph_context.get("action_attempts") or []
    if actions:
        lines.append("Recent action transition edges:")
        for a in actions[-30:]:
            targets = ", ".join(a.get("targets") or []) or "-"
            lines.append(
                f"- {a.get('before_state') or '?'} --{a.get('source')}/{a.get('status')} "
                f"{a.get('action_type')} '{_trim(a.get('target_label'), 70)}'--> "
                f"{a.get('after_state') or '?'}; TARGETS {targets}"
            )

    lines.append(f"Expected-but-absent concepts: {absent}")
    lines.append(f"Observed-but-not-validated concepts: {seen_not_validated}")
    return "\n".join(lines)


def _concept_status(concept_map: dict[str, dict], key: str | None, observed: list[str], validated: list[str]) -> str:
    c = concept_map.get(key or "", {})
    return f"observed={_yn((key in observed) or c.get('observed'))}, validated={_yn((key in validated) or c.get('validated'))}"


def _yn(value: Any) -> str:
    return "Y" if value else "n"


def _trim(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]
