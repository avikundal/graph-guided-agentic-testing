from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExplorationEvent:
    step: int
    kind: str
    label: str
    state: str
    status: str
    source: str = "crawler"
    evidence: list[str] = field(default_factory=list)


@dataclass
class ExplorationReport:
    run_id: str
    feature: str
    events: list[ExplorationEvent]
    frontier_stats: dict[str, Any]
    graph_scenarios: list[dict[str, Any]]
    living_graph: dict[str, Any] | None
    run_assertions: dict[str, Any] = field(default_factory=dict)
    safety_notes: list[str] = field(default_factory=list)
    inspect_command: str = ""
    coverage: dict[str, Any] | None = None
    graph_impact: dict[str, Any] | None = None


def render_report(r: ExplorationReport, *, debug: bool = False) -> str:
    events = r.events
    clicked = [e for e in events if e.kind == "clicked"]
    found = [e for e in events if e.kind == "found" and not any(str(x).startswith("wrong-state:") for x in e.evidence)]
    observed = [e for e in events if e.kind == "observed"]
    validated = [e for e in events if e.status == "validated"]
    replay = [e for e in events if e.kind == "replay"]
    blocked = [e for e in events if e.kind == "blocked"]
    frontier = [e for e in events if e.kind == "frontier"]
    by_source = Counter(e.source for e in events)
    by_status = Counter(e.status for e in events)

    lines: list[str] = []
    lines.append("=" * 76)
    lines.append("TESTSIGMA GRAPH-GUIDED DFS EXPLORER REPORT")
    lines.append("=" * 76)
    lines.append("")
    lines.append("Feature:")
    lines.append(f"  - {r.feature}")
    lines.append(f"  - run_id: {r.run_id}")
    lines.append("")

    lines.append("Executive summary:")
    lines.append(f"  - Direct browser clicks executed: {len(clicked)}")
    lines.append(f"  - Browser-validated behaviours: {len(validated)}")
    lines.append(f"  - Observation-only affordances recorded: {len(found)}")
    lines.append(f"  - Frontier intents proposed: {len(frontier)}")
    lines.append(f"  - State replay/verification events: {len(replay)}")
    lines.append(f"  - Blocked/unsafe/failed attempts: {len(blocked)}")
    if r.run_assertions:
        lines.append(f"  - Add to Cart validated: {str(r.run_assertions.get('add_to_cart_validated', False)).lower()}")
        lines.append(f"  - Proceed to Checkout validated: {str(r.run_assertions.get('proceed_to_checkout_validated', False)).lower()}")
        lines.append(f"  - End-to-end checkout flow validated: {str(r.run_assertions.get('end_to_end_checkout_flow_validated', False)).lower()}")
        lines.append(f"  - Cart provenance: {r.run_assertions.get('cart_provenance', 'unknown')}")
    lines.append("")

    lines.append("What the crawler directly clicked/executed:")
    if clicked:
        for e in clicked:
            ev = "; ".join(e.evidence[:4]) if e.evidence else "-"
            lines.append(f"  - {e.label} [{e.status}] state={e.state} source={e.source} evidence={ev}")
    else:
        lines.append("  - none")
    lines.append("")

    if r.run_assertions:
        lines.append("Cart/product provenance:")
        lines.append(f"  - cart pre-existing before run: {str(r.run_assertions.get('cart_preexisting', False)).lower()}")
        lines.append(f"  - cart delta verified from this run: {str(r.run_assertions.get('cart_delta_verified', False)).lower()}")
        lines.append(f"  - cart product match verified: {str(r.run_assertions.get('cart_product_verified', False)).lower()}")
        pt = r.run_assertions.get('product_title') or ''
        ct = r.run_assertions.get('cart_title') or ''
        if pt:
            lines.append(f"  - product title evidence: {pt[:120]}")
        if ct:
            lines.append(f"  - cart title evidence: {ct[:120]}")
        if r.run_assertions.get('cart_preexisting') and not r.run_assertions.get('add_to_cart_validated'):
            lines.append("  - note: cart exploration continued from a pre-existing cart; Add-to-Cart was not validated in this run.")
        lines.append("")

    lines.append("What the crawler/semantic layer found but mostly did not click:")
    if found:
        for e in found[:18]:
            ev = "; ".join(e.evidence[:4]) if e.evidence else "-"
            lines.append(f"  - {e.label} [{e.status}] state={e.state} source={e.source} evidence={ev}")
        if len(found) > 18:
            lines.append(f"  - ... {len(found) - 18} more in debug trace")
    else:
        lines.append("  - none")
    lines.append("")

    fs = r.frontier_stats
    lines.append("Graph-guided DFS frontier value:")
    lines.append(f"  - Unique frontier intents accepted: {fs.get('added', 0)}")
    lines.append(f"  - Duplicate proposals skipped: {fs.get('skipped_duplicate', 0)}")
    lines.append(f"  - Already-completed proposals skipped: {fs.get('skipped_completed', 0)}")
    lines.append(f"  - Stale queued items pruned after success: {fs.get('pruned_after_completion', 0)}")
    lines.append(f"  - Stale queued items skipped on pop: {fs.get('skipped_stale_on_pop', 0)}")
    lines.append(f"  - Intents popped/evaluated: {fs.get('popped', 0)}")
    lines.append(f"  - Executed by explorer: {fs.get('executed', 0)}")
    lines.append(f"  - Observation-only items recorded: {fs.get('observed_only', 0)}")
    lines.append(f"  - Forbidden clicks blocked: {fs.get('blocked_forbidden', 0)}")
    lines.append(f"  - Wrong-state items postponed/replayed: {fs.get('postponed_wrong_state', 0)}")
    lines.append(f"  - Replay/state reacquisition used: {fs.get('requires_replay', 0)}")
    lines.append(f"  - Replay failures: {fs.get('replay_failed', 0)}")
    lines.append("  - Meaning: the explorer observes a state, builds a local frontier, explores local affordances first, and only then moves deeper.")
    lines.append("")

    gi = r.graph_impact or {}
    if gi:
        crawler_only = gi.get("behaviors_validated_by_crawler_alone", 0)
        scen = gi.get("scenarios_surfaced_only_by_graph", 0)
        lines.append("Graph impact (this run) — crawler alone vs. with graph:")
        lines.append(f"  - Behaviors validated by the crawler alone:          {crawler_only}")
        lines.append(f"  - Scenarios surfaced ONLY by graph reasoning:        +{scen}  "
                     f"({gi.get('graph_scenarios_missed_gaps', 0)} coverage gaps + {gi.get('graph_scenarios_boundary_safety', 0)} boundary/safety)")
        lines.append(f"  - Actions the graph pushed into exploration:         +{gi.get('actions_graph_pushed_into_dfs', 0)}  "
                     f"(covered by crawler: {gi.get('graph_pushed_actions_covered', 0)})")
        lines.append(f"  - Actions discovered dynamically from the live page:  +{gi.get('actions_discovered_dynamically', 0)}  "
                     f"(product options/variants/cart controls, no fixed catalogue)")
        lines.append(f"  - Redundant re-executions the graph memory avoided:  {gi.get('redundant_executions_avoided', 0)}")
        lines.append(f"  - Feature concept coverage:                          {gi.get('concept_coverage_pct', 0)}%")
        lines.append(f"  - Structural gaps the graph flagged:                 {', '.join(gi.get('structural_gaps_flagged', [])) or 'none'}")
        lines.append(f"  - Net: {crawler_only} directly-validated behaviors -> {crawler_only + scen} documented + reasoned scenarios.")
        surfaced = gi.get("graph_surfaced_missed", [])
        if surfaced:
            lines.append("")
            lines.append("Engine 2 — scenarios the graph (LLM-over-graph) surfaced as MISSED by the crawl:")
            for t in surfaced[:10]:
                lines.append(f"  - {t}")
        lines.append("")

    cov = r.coverage or {}
    if cov:
        lines.append("Coverage & graph contribution:")
        lines.append(f"  - Feature concepts expected: {cov.get('expected_total', 0)}")
        lines.append(f"  - Observed this run: {cov.get('observed', 0)} ({cov.get('observed_pct', 0)}%)")
        lines.append(f"  - Actions validated by the crawler: {cov.get('validated', 0)}")
        lines.append(f"  - Missed scenarios inferred by the graph: {cov.get('inferred_missed', 0)}")
        lines.append(f"  - Graph-inferred actions fed back into DFS: {cov.get('graph_driven_added', 0)}")
        lines.append(f"  - ...of those, covered (executed/observed) by the crawler: {cov.get('graph_driven_covered', 0)}")
        lines.append(f"  - Structurally absent (expected, never observed): {', '.join(cov.get('absent', [])) or 'none'}")
        lines.append("  - Meaning: the graph turns observed structure into concrete tests the crawler then runs, independent of the LLM.")
        lines.append("")

    lines.append("Graph/LLM value added beyond direct clicks:")
    if r.graph_scenarios:
        for s in r.graph_scenarios:
            deps = ", ".join(s.get("depends_on", []))
            lines.append(f"  - {s['title']} [{s['status']}] source={s.get('source')} depends_on={deps}")
    else:
        lines.append("  - No graph-inferred scenarios were produced.")
    lines.append("")

    lines.append("Run accounting:")
    lines.append("  - Source breakdown: " + (", ".join(f"{k}={v}" for k, v in by_source.items()) or "none"))
    lines.append("  - Status breakdown: " + (", ".join(f"{k}={v}" for k, v in by_status.items()) or "none"))
    lines.append("")

    if r.living_graph:
        lines.append("Living graph bonus:")
        lines.append(f"  - stable signals: {r.living_graph.get('stable', 0)}")
        lines.append(f"  - missing expected concepts: {', '.join(r.living_graph.get('missing', [])) or 'none'}")
        if "neighbor_llm_calls" in r.living_graph:
            lines.append(f"  - neighbor LLM calls: {r.living_graph.get('neighbor_llm_calls', 0)}")
            lines.append(f"  - deterministic fallback calls: {r.living_graph.get('neighbor_fallback_calls', 0)}")
        recs = r.living_graph.get("recommended_retests", [])
        lines.append("  - recommended retests:")
        if recs:
            for rec in recs:
                lines.append(f"      * {rec.get('human_label')} expected_state={rec.get('expected_state')} reason={rec.get('reason')}")
        else:
            lines.append("      none")
        lines.append("")

    if blocked:
        lines.append("Blocked / not executed:")
        for e in blocked[:10]:
            ev = "; ".join(e.evidence[:3]) if e.evidence else "-"
            lines.append(f"  - {e.label} [{e.status}] state={e.state} source={e.source} evidence={ev}")
        if len(blocked) > 10:
            lines.append(f"  - ... {len(blocked) - 10} more in debug trace")
        lines.append("")

    if debug:
        lines.append("Detailed step trace (--debug):")
        for e in events:
            ev = "; ".join(e.evidence[:5]) if e.evidence else "-"
            lines.append(f"  {e.step:02d}. {e.kind.upper()} [{e.state}] {e.label} -> {e.status} ({e.source}) evidence={ev}")
        lines.append("")

    lines.append("Safety:")
    for note in r.safety_notes:
        lines.append(f"  - {note}")
    lines.append("")
    lines.append("Neo4j inspect:")
    lines.append(f"  $ {r.inspect_command}")
    return "\n".join(lines)
