from __future__ import annotations

import html
import json
import re
import uuid
from dataclasses import asdict
from typing import Any
from urllib.parse import urlparse

from ..config import DATA_DIR
from ..domain.amazon_auth import AUTH_FILE, base_url_for, reset_amazon_cart, verify_auth_state
from ..domain.checkout_contract import (
    EXPECTED_CONCEPTS,
    INFERENCE_RULES,
    INTENTS,
    RISK_DESTRUCTIVE_CLICK,
    RISK_FORBIDDEN_CLICK,
    RISK_MUTATING_CLICK,
    RISK_OBSERVE_ONLY,
    SOURCE_CRAWLER,
    SOURCE_DOMAIN,
    SOURCE_GRAPH,
    STATE_CART,
    STATE_CART_CONFIRMATION,
    STATE_CHECKOUT,
    STATE_PRODUCT,
)
from ..graph.store import GraphStore
from ..reporting.report import ExplorationEvent, ExplorationReport, render_report
from .browser_use_executor import BrowserUseIntentExecutor, BrowserUseResult
from .dynamic_discovery import discover_dynamic_intents
from .frontier import IntentFrontier
from .llm_neighbors import NeighborGenerator
from .page_observer import PageObservation
from .semantic_normalizer import NormalizedIntent, SemanticNormalizer


class GraphGuidedExplorer:
    """Browser-use powered graph-guided DFS frontier explorer.

    Correct responsibility split for Part A:
      - browser-use owns actual crawling/execution using DOM + ARIA + screenshot + page understanding.
      - DFS/frontier/graph owns what should be explored next, safety, state, replay, and reasoning.

    The explorer no longer micromanages obvious clicks like Add to Cart with CSS selectors.
    It gives browser-use a narrow one-intent task, ingests the returned artifacts, then updates
    Neo4j and the exploration frontier.
    """

    def __init__(
        self,
        *,
        product_url: str,
        tenant_id: str,
        project_id: str,
        feature_key: str,
        max_steps: int = 24,
        max_neighbors: int = 5,
        headless: bool = True,
        allow_mutating: bool = True,
        allow_destructive: bool = True,
        enable_living_graph: bool = False,
        reset_graph: bool = False,
        reset_cart: bool = False,
        debug: bool = False,
        autonomous: bool = False,
    ):
        self.autonomous = autonomous
        self.product_url = product_url
        self.scope = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "feature_key": f"feature.{feature_key}" if not feature_key.startswith("feature.") else feature_key,
        }
        self.feature_display_key = feature_key
        self.run_id = f"run_{uuid.uuid4().hex[:12]}"
        self.max_steps = max_steps
        self.max_neighbors = max_neighbors
        self.headless = headless
        self.allow_mutating = allow_mutating
        self.allow_destructive = allow_destructive
        self.enable_living_graph = enable_living_graph
        self.reset_graph = reset_graph
        self.reset_cart = reset_cart
        self.debug = debug

        self.executor = BrowserUseIntentExecutor(headless=headless, debug=debug)
        # Deny-list safety scope: block off-product navigation + final payment.
        self.executor.set_safety_context(product_url)
        self.normalizer = SemanticNormalizer()
        self.frontier = IntentFrontier()
        self.neighbor_generator = NeighborGenerator()
        self.graph = GraphStore()
        self.events: list[ExplorationEvent] = []
        self.scenarios: list[dict[str, Any]] = []
        self.step = 0
        self.visited_states: set[str] = set()
        self.observed_concepts: set[str] = set()
        self.observed_signatures: set[str] = set()

        self.checkout_reached = False
        self.final_forbidden_detected = False
        self.add_to_cart_validated = False
        self.proceed_to_checkout_validated = False
        self.cart_preexisting = False
        self.cart_delta_verified = False
        self.cart_product_verified = False
        self.cart_provenance = "unknown"
        self.product_title = ""
        self.cart_title = ""
        self.product_asin = _asin_from_url(product_url)
        # Cart/checkout must stay on the SAME Amazon domain as the product
        # (amazon.in product -> amazon.in cart), otherwise the item is added on
        # one marketplace while the cart is read on another (empty) one.
        self.cart_url = _cart_url_for(product_url)
        self.cart_count_baseline: int | None = None
        self.graph_driven_added = 0
        self.dynamic_discovered = 0
        self.restores_done = 0

    def log(self, kind: str, msg: str) -> None:
        if self.debug:
            print(f"[dfs][{kind}] {msg}")

    async def run(self) -> str:
        self.graph.verify()
        self.graph.ensure_constraints()
        if self.reset_graph:
            self.graph.reset_scope(self.scope)
        self.graph.init_run(self.scope, self.run_id, self.product_url)
        # Seed the feature contract so absence is a queryable graph property.
        self.graph.seed_expected_concepts(self.scope, EXPECTED_CONCEPTS)

        signed_in, reason = await verify_auth_state(headless=True, base_url=base_url_for(self.product_url))
        if not signed_in:
            return (
                "NOT SIGNED IN for this marketplace — run scripts/login_amazon.py "
                f"(log in on {base_url_for(self.product_url)}).\n" + reason
            )
        if not AUTH_FILE.exists():
            return f"Amazon auth file missing: {AUTH_FILE}"

        if self.reset_cart:
            summary = await reset_amazon_cart(headless=self.headless, cart_url=self.cart_url)
            self.log("reset", summary)
            self._event("replay", "Reset cart before run", STATE_CART, "reset", SOURCE_CRAWLER, [summary])

        await self.executor.start()
        try:
            await self._cart_preflight()
            initial = await self.executor.navigate_and_observe(
                self.product_url,
                expected_state=STATE_PRODUCT,
                label="Initial product page",
            )
            self._record_replay_like(initial, "Initial product page", STATE_PRODUCT)
            current_obs = await self._observe_update_frontier(initial.observation, source=SOURCE_CRAWLER)
            if self.autonomous:
                await self._autonomous_loop(current_obs)
            else:
                await self._seed_domain_intents()
                await self._dfs_loop(current_obs)
        finally:
            await self.executor.close()

        living = self._living_graph_section() if self.enable_living_graph else None
        coverage = self._coverage_summary()
        report = ExplorationReport(
            run_id=self.run_id,
            feature="Amazon checkout — browser-use + graph-guided DFS frontier exploration",
            events=self.events,
            frontier_stats=asdict(self.frontier.stats),
            graph_scenarios=self.scenarios,
            living_graph=living,
            run_assertions=self._run_assertions(),
            safety_notes=[
                "browser-use executes the actual UI actions using DOM, ARIA labels, screenshots/layout, and page context.",
                "DFS/graph decides what to explore next; browser-use decides how to perform the narrow action.",
                "Only two things are off-limits: final payment (Buy Now / Place Order / Pay) and navigating to a different product. Everything else — quantity, delete/remove, save-for-later, promo/offers, gift options — is clicked and verified.",
                "Destructive and mutating cart actions are executed by default, verified by a real cart item-count/subtotal delta, then the cart is auto-restored (re-add) so the flow still completes. Disable with --no-destructive / --no-mutating.",
                "State gate and replay run before intent execution; cart actions are not searched on checkout pages.",
            ],
            inspect_command=(
                f"./.venv/bin/python scripts/inspect_graph.py --tenant-id {self.scope['tenant_id']} "
                f"--project-id {self.scope['project_id']} --feature {self.feature_display_key} --run-id {self.run_id}"
            ),
            coverage=coverage,
            graph_impact=self._graph_impact_summary(coverage),
        )
        self.graph.close()
        report_text = render_report(report, debug=self.debug)
        self._write_outputs(report, report_text)
        return report_text

    def _write_outputs(self, report: ExplorationReport, report_text: str) -> None:
        """Persist the run report and a structured sample-output artifact.

        Writes both a per-run copy and a stable `latest_*` copy so a reviewer can
        open the deliverable (discovered vs. inferred vs. missed scenarios)
        without re-running the crawl.
        """
        out_dir = DATA_DIR / "run_logs"
        out_dir.mkdir(parents=True, exist_ok=True)
        discovered = [
            {"label": e.label, "status": e.status, "state": e.state, "source": e.source}
            for e in self.events if e.kind in {"clicked", "found"}
        ]
        sample = {
            "run_id": self.run_id,
            "feature": report.feature,
            "product_url": self.product_url,
            "scenarios_discovered_by_agent": discovered,
            "scenarios_inferred_by_graph": self.scenarios,
            "missed_by_agent_surfaced_by_graph": [s for s in self.scenarios if s.get("status") == "INFERRED_MISSED"],
            "run_assertions": report.run_assertions,
            "coverage": report.coverage,
            "graph_impact": report.graph_impact,
        }
        try:
            (out_dir / f"report_{self.run_id}.txt").write_text(report_text, encoding="utf-8")
            (out_dir / "latest_report.txt").write_text(report_text, encoding="utf-8")
            payload = json.dumps(sample, indent=2, ensure_ascii=False)
            (out_dir / f"sample_output_{self.run_id}.json").write_text(payload, encoding="utf-8")
            (out_dir / "latest_sample_output.json").write_text(payload, encoding="utf-8")
            self.log("output", f"wrote report + sample_output to {out_dir}")
        except Exception as exc:
            self.log("output", f"failed to write outputs: {exc}")

    def _coverage_summary(self) -> dict[str, Any]:
        expected = set(EXPECTED_CONCEPTS)
        observed = self.observed_concepts & expected
        validated = self._validated_concepts() & expected
        inferred_missed = [s for s in self.scenarios if s.get("status") == "INFERRED_MISSED"]
        # How many graph-fed actions the crawler actually exercised (executed or
        # safely observed because of a risk gate).
        graph_events = [e for e in self.events if e.source == SOURCE_GRAPH]
        covered = len({
            e.label for e in graph_events
            if e.kind in {"clicked", "found"} or e.status in {"validated", "clicked_observed", "observed_only", "destructive_observed_not_clicked"}
        })
        absent = []
        if self.graph.enabled:
            try:
                absent = sorted(set(self.graph.missing_expected_concepts(self.scope)) & expected)
            except Exception:
                absent = []
        if not absent:
            absent = sorted(expected - self.observed_concepts)
        total = max(1, len(expected))
        return {
            "expected_total": len(expected),
            "observed": len(observed),
            "observed_pct": round(100.0 * len(observed) / total, 1),
            "validated": len(validated),
            "inferred_missed": len(inferred_missed),
            "graph_driven_added": self.graph_driven_added,
            "graph_driven_covered": covered,
            "absent": absent,
        }

    def _graph_impact_summary(self, coverage: dict[str, Any]) -> dict[str, Any]:
        """Quantify what the graph layer contributed vs. the bare crawler.

        'Crawler alone' = behaviours browser-use validated by direct action.
        'With graph' adds: reasoned scenarios the agent never executed, actions
        the graph pushed into exploration, redundant work the graph memory
        avoided, and the absence it flagged.
        """
        validated_total = sum(1 for e in self.events if e.status == "validated")
        validated_graph = sum(1 for e in self.events if e.status == "validated" and e.source == SOURCE_GRAPH)
        validated_direct = validated_total - validated_graph
        scenarios_total = len(self.scenarios)
        missed = sum(1 for s in self.scenarios if s.get("status") == "INFERRED_MISSED")
        st = self.frontier.stats
        redundant_avoided = st.skipped_completed + st.skipped_duplicate + st.pruned_after_completion
        return {
            "behaviors_validated_by_crawler_alone": validated_direct,
            "scenarios_surfaced_only_by_graph": scenarios_total,
            "graph_scenarios_missed_gaps": missed,
            "graph_scenarios_boundary_safety": scenarios_total - missed,
            "actions_graph_pushed_into_dfs": self.graph_driven_added,
            "actions_discovered_dynamically": self.dynamic_discovered,
            "graph_pushed_actions_covered": coverage.get("graph_driven_covered", 0),
            "redundant_executions_avoided": redundant_avoided,
            "concept_coverage_pct": coverage.get("observed_pct", 0),
            "structural_gaps_flagged": coverage.get("absent", []),
        }

    async def _autonomous_loop(self, current_obs: PageObservation) -> None:
        """Two-engine crawl: browser-use explores each state autonomously (it
        chooses its own actions, the deny-list veto keeps it safe), then the graph
        reasons over what it found. No catalogue, no scripted intents.
        """
        # 1) Product page — let it try options, then add to cart.
        res = await self.executor.explore_autonomously(
            goal="You are on a product page. First try any product options you see (size, colour, style, quantity), then add the product to the cart.",
            expected_state=STATE_PRODUCT, max_steps=10,
        )
        self._ingest_autonomous(res, STATE_PRODUCT)

        # 2) Open the canonical cart and confirm the item landed.
        cart = await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label="Open cart after product exploration")
        await self._observe_update_frontier(cart.observation, source=SOURCE_CRAWLER)
        if (_cart_item_count(cart.observation) or 0) > 0:
            self.add_to_cart_validated = True
            self.cart_provenance = "cart_confirmation_or_cart_delta_verified"
            if not self.cart_preexisting:
                self.cart_delta_verified = True
            self.observed_concepts.update({"action.add_to_cart", "domain.cart_item"})
        else:
            restored = await self._restore_product_to_cart()
            await self._observe_update_frontier(restored, source=SOURCE_CRAWLER)
            if (_cart_item_count(restored) or 0) > 0:
                self.add_to_cart_validated = True

        # 3) Cart — explore the cart controls freely.
        res2 = await self.executor.explore_autonomously(
            goal="You are on the shopping cart. Test the cart controls: change the quantity, save an item for later, remove/delete an item, apply a coupon or offer if present, try gift options. Try each available control once and observe what changes.",
            expected_state=STATE_CART, max_steps=16,
        )
        self._ingest_autonomous(res2, STATE_CART)

        # 4) Re-read the cart; restore the product if exploration emptied it.
        cart2 = await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label="Cart after exploration")
        cart2_obs = cart2.observation
        if (_cart_item_count(cart2_obs) or 0) == 0:
            cart2_obs = await self._restore_product_to_cart()
        await self._observe_update_frontier(cart2_obs, source=SOURCE_CRAWLER)

        # 5) Graph reasons about what the crawl missed.
        self._infer_graph_scenarios()

        # 6) Proceed to the checkout boundary. The veto guarantees no order is placed.
        res3 = await self.executor.explore_autonomously(
            goal="Click 'Proceed to Checkout' to reach the secure checkout page. Do NOT place an order or pay — stop as soon as the checkout page appears.",
            expected_state=STATE_CART, max_steps=4,
        )
        self._ingest_autonomous(res3, STATE_CHECKOUT)
        final_obs = res3.observation
        if final_obs.state == STATE_CHECKOUT or "checkout" in (final_obs.url or "").lower():
            self.checkout_reached = True
            self.proceed_to_checkout_validated = True
            self.observed_concepts.add("domain.checkout_boundary")
            await self._observe_update_frontier(final_obs, source=SOURCE_CRAWLER)
        self._infer_graph_scenarios()
        self.log("stop", "autonomous exploration complete")

    def _ingest_autonomous(self, res: BrowserUseResult, state: str) -> None:
        """Record the actions browser-use chose on its own as crawl-discovered
        scenarios (attributed to the crawl), plus any safety veto."""
        seen: set[str] = set()
        for art in res.artifacts:
            if art.action_type not in {"click", "fill", "select"}:
                continue
            label = (art.target_label or "").strip()
            key = label.lower()
            if not label or key in seen:
                continue
            seen.add(key)
            self._event("clicked", label[:60], state, "crawl_explored", SOURCE_CRAWLER,
                        [f"autonomous {art.action_type}", f"state={art.state}"])
        if res.error and "safety_veto" in res.error:
            self._event("blocked", "Safety veto (deny-list)", state, "vetoed", SOURCE_CRAWLER, [res.error[:120]])

    async def _dfs_loop(self, current_obs: PageObservation) -> None:
        for _ in range(self.max_steps):
            if current_obs.state == STATE_CHECKOUT:
                self.checkout_reached = True
                self._infer_graph_scenarios()
                self.log("stop", "checkout reached; terminal prototype boundary")
                return

            intent = self.frontier.pop_for_state(current_obs.state)
            if intent is None:
                transition = self._next_transition_intent(current_obs.state)
                if transition and self.frontier.push(transition):
                    self._event("frontier", transition.human_label, transition.expected_state, "added", transition.source, [transition.canonical_key, "state transition after local frontier exhausted"])
                intent = self.frontier.pop_for_state(current_obs.state)

            if intent is None:
                intent = self.frontier.pop_any()
                if intent is None:
                    self._infer_graph_scenarios()
                    self.log("stop", "frontier empty")
                    return

            current_obs = await self._process_intent(intent, current_obs)
            self._infer_graph_scenarios()

    async def _process_intent(self, intent: NormalizedIntent, current_obs: PageObservation) -> PageObservation:
        # Phase 1 execution memory: a canonical intent that already succeeded
        # in this run must never execute again, even if an old duplicate was
        # still queued before completion.
        if self.frontier.is_completed(intent.canonical_key):
            self.frontier.stats.skipped_completed += 1
            self._event(
                "blocked",
                intent.human_label,
                current_obs.state,
                "already_completed",
                intent.source,
                [intent.canonical_key, "canonical intent already succeeded in this run"],
            )
            return current_obs

        # State gate before execution. If the page is wrong, ask browser-use to replay/navigate
        # to the expected state, then observe; do not ground against the wrong page.
        # Forbidden / observe-only intents (e.g. Final Order Boundary) never justify
        # navigating deeper just to look — that only produces guaranteed replay
        # failures. Record them from the current page instead.
        skip_replay = intent.risk in {RISK_FORBIDDEN_CLICK, RISK_OBSERVE_ONLY} or not intent.click_allowed
        if current_obs.state != intent.expected_state and not skip_replay:
            self.frontier.stats.postponed_wrong_state += 1
            self.frontier.stats.requires_replay += 1
            self._event(
                "replay",
                f"Reacquire {intent.expected_state} for {intent.human_label}",
                current_obs.state,
                "requires_replay",
                intent.source,
                [f"current={current_obs.state}", f"expected={intent.expected_state}"],
            )
            replay_result = await self._replay_to(intent.expected_state)
            self._record_replay_like(replay_result, f"Reacquire {intent.expected_state}", intent.expected_state)
            if replay_result.observation.state != intent.expected_state:
                self.frontier.stats.replay_failed += 1
                self.frontier.mark_blocked(intent, "replay_failed")
                self._event("blocked", intent.human_label, replay_result.observation.state, "replay_failed", intent.source, [f"expected={intent.expected_state}", f"observed={replay_result.observation.state}"])
                return replay_result.observation
            current_obs = await self._observe_update_frontier(replay_result.observation, source=SOURCE_CRAWLER)

        # Phase 3 readiness gate: some Amazon transitional pages (especially
        # smart-wagon after add/quantity changes) report shopping_cart but are
        # not stable enough for checkout. Stabilize before asking browser-use
        # to execute the checkout transition.
        readiness_result = await self._ensure_ready_for_intent(intent, current_obs)
        if readiness_result is not None:
            self._record_replay_like(readiness_result, f"Readiness check for {intent.human_label}", intent.expected_state)
            current_obs = await self._observe_update_frontier(readiness_result.observation, source=SOURCE_CRAWLER)
            if current_obs.state != intent.expected_state:
                self.frontier.stats.replay_failed += 1
                self.frontier.mark_blocked(intent, "readiness_failed")
                self._event("blocked", intent.human_label, current_obs.state, "readiness_failed", intent.source, [f"expected={intent.expected_state}", f"observed={current_obs.state}"])
                return current_obs

        if intent.risk == RISK_FORBIDDEN_CLICK:
            self.frontier.stats.blocked_forbidden += 1
            self.frontier.mark_completed(intent, "forbidden boundary recorded")
            self.observed_concepts.add(intent.canonical_key)
            self.graph.write_intent(self.scope, self.run_id, intent, "forbidden_blocked", ["safety boundary"])
            self._event("blocked", intent.human_label, current_obs.state, "forbidden", intent.source, ["safety boundary observed; never clicked"])
            return current_obs

        if intent.risk == RISK_DESTRUCTIVE_CLICK and not self.allow_destructive:
            self.frontier.stats.observed_only += 1
            self.frontier.mark_completed(intent, "destructive action observed but not clicked")
            self.observed_concepts.add(intent.canonical_key)
            self.graph.write_intent(self.scope, self.run_id, intent, "destructive_observed_not_clicked", ["destructive clicks disabled by default"])
            self._event("found", intent.human_label, current_obs.state, "destructive_observed_not_clicked", intent.source, [intent.canonical_key, "destructive clicks disabled by default"])
            return current_obs

        if intent.risk == RISK_MUTATING_CLICK and not self.allow_mutating:
            self.frontier.stats.observed_only += 1
            self.frontier.mark_blocked(intent, "mutating disabled")
            self.graph.write_intent(self.scope, self.run_id, intent, "mutating_disabled", ["set --allow-mutating to execute"])
            self._event("blocked", intent.human_label, current_obs.state, "mutating_disabled", intent.source, ["set --allow-mutating to execute"])
            return current_obs

        if intent.risk == RISK_OBSERVE_ONLY or not intent.click_allowed:
            self.frontier.stats.observed_only += 1
            self.frontier.mark_completed(intent, "observe-only intent recorded")
            self.observed_concepts.add(intent.canonical_key)
            self.graph.write_intent(self.scope, self.run_id, intent, "observed_only", intent.success_criteria)
            self._event("found", intent.human_label, current_obs.state, "observed_only", intent.source, [intent.canonical_key] + list(intent.success_criteria[:2]))
            return current_obs

        # ANY cart mutation (quantity, delete, save-for-later, promo, gift, ...) is
        # verified the same authoritative way: snapshot the canonical cart, perform
        # the action, then re-read the cart and require a real item-count/subtotal
        # delta. This is genuine testing — not browser-use's flaky in-window guess.
        # Product-page options (state != cart) are not cart mutations and validate
        # via the executor's own verdict.
        mutation_pre = None
        is_cart_mutation = (
            current_obs.state == STATE_CART
            and intent.risk in {RISK_MUTATING_CLICK, RISK_DESTRUCTIVE_CLICK}
        )
        if is_cart_mutation:
            pre = await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label=f"Cart before: {intent.human_label}")
            mutation_pre = (_cart_item_count(pre.observation), _cart_subtotal(pre.observation))

        # Let browser-use execute the action. Do not rediscover selectors manually.
        result = await self.executor.execute_intent(intent)
        after = result.observation
        status = result.status
        ui_action_taken = result.action_type in {"click", "fill", "select"}

        if is_cart_mutation and mutation_pre is not None:
            changed, after, ev = await self._verify_cart_mutation(mutation_pre)
            result.evidence = (result.evidence or []) + ev
            status = "validated" if changed else "clicked_observed"
            post_count = _cart_item_count(after)
            # A delete/save that empties the cart is a verified pass even if the
            # subtotal text disappears with the last line.
            if (mutation_pre[0] or 0) > 0 and post_count == 0:
                changed, status = True, "validated"
            self._event(
                "replay", f"Verify {intent.human_label}", after.state,
                "validated" if changed else "not_validated", SOURCE_CRAWLER, ev,
            )
            # Self-healing: if the active cart is now empty, add the product back so
            # the destructive/save test does not dead-end the end-to-end flow. The
            # removal was already proven; this restores state and demonstrates a
            # complete add -> remove -> verify -> re-add test loop.
            if changed and post_count == 0:
                after = await self._restore_product_to_cart()

        # Reaching secure checkout is the success criterion for Proceed to Checkout.
        # Some marketplaces (e.g. amazon.in) insert a benign interstitial
        # ("Continue to checkout" on a same-day/bundle carousel), so a second click
        # is expected and must not be penalised as "wandering" — PROVIDED it is not
        # a sign-in redirect and not a wrong-target click (logo/search/cart).
        # Forbidden final-purchase actions are still never clicked.
        if intent.canonical_key == "action.proceed_to_checkout" and status != "validated":
            if _checkout_reached_ok(after.state, after.url, result.error):
                status = "validated"
                result.evidence = (result.evidence or []) + ["secure checkout reached (benign interstitial step allowed)"]

        if status == "validated":
            self.frontier.stats.executed += 1
            self.frontier.mark_completed(intent, "browser-use validated intent")
            self.observed_concepts.add(intent.canonical_key)
        elif status == "already_satisfied":
            # Useful state proof, but not a direct browser click.
            self.frontier.mark_completed(intent, "intent already satisfied in current state")
            self.observed_concepts.add(intent.canonical_key)
        elif status in {"blocked_signin"}:
            # Auth boundary after checkout click is a meaningful observed boundary,
            # but not a validated secure-checkout transition.
            self.frontier.mark_blocked(intent, status)
            self.observed_concepts.add("domain.checkout_boundary")
        elif intent.risk in {RISK_MUTATING_CLICK, RISK_DESTRUCTIVE_CLICK} and ui_action_taken:
            # A side-effecting UI action already fired (e.g. the quantity stepper
            # was clicked and the cart did update) even though browser-use could
            # not confirm the change within its short observe window. Never re-run
            # a mutating/destructive intent or the cart keeps changing on every
            # re-discovery — this is what inflated the cart to 4 items per run.
            self.frontier.stats.executed += 1
            self.frontier.mark_completed(intent, f"{status}; side effect applied, not repeated")
            self.observed_concepts.add(intent.canonical_key)
        else:
            self.frontier.mark_failed(intent, status)

        if intent.canonical_key == "action.add_to_cart":
            if status == "validated":
                self.add_to_cart_validated = True
            if self.add_to_cart_validated:
                self.cart_provenance = "cart_confirmation_or_cart_delta_verified"
                if not self.cart_preexisting:
                    self.cart_delta_verified = True
        elif intent.canonical_key == "action.go_to_cart" and status in {"validated", "already_satisfied"}:
            self.observed_concepts.add("domain.cart_item")
        elif intent.canonical_key == "action.proceed_to_checkout" and status == "validated":
            self.checkout_reached = True
            self.proceed_to_checkout_validated = True
            self.observed_concepts.add("domain.checkout_boundary")
        elif intent.canonical_key == "action.change_quantity" and status == "validated":
            self.observed_concepts.add("domain.subtotal")

        self.graph.write_intent(self.scope, self.run_id, intent, status, result.evidence + [f"browser_use_selector={result.selector}"])
        if status in {"validated", "clicked_observed"} and ui_action_taken:
            kind = "clicked"
        elif status == "already_satisfied":
            kind = "found"
        else:
            kind = "blocked"
        self._event(kind, intent.human_label, current_obs.state, status, intent.source, result.evidence[:5] + ([f"next_state={after.state}"] if after.state else []))
        # After Add to Cart, open the full canonical cart right away so its controls
        # (quantity, delete, save-for-later, promo) are discovered and queued BEFORE
        # Proceed to Checkout is considered. The add-to-cart interstitial is sparse,
        # which previously hid those controls and let checkout fire too early.
        if intent.canonical_key == "action.add_to_cart" and status == "validated" and after.state != STATE_CART:
            cart_nav = await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label="Open full cart after add")
            after = cart_nav.observation
        obs = await self._observe_update_frontier(after, source=SOURCE_CRAWLER)
        return obs

    async def _observe_update_frontier(self, obs: PageObservation, *, source: str) -> PageObservation:
        self._capture_identity_from_observation(obs)
        self.step += 1
        self.visited_states.add(obs.state)
        self.observed_concepts |= obs.detected_concepts
        self.graph.write_observation(self.scope, self.run_id, self.step, obs)

        signature = f"{obs.state}:{','.join(sorted(obs.detected_concepts))}:{len(obs.elements)}"
        if signature not in self.observed_signatures:
            self.observed_signatures.add(signature)
            evidence = sorted(obs.detected_concepts)[:8]
            state_ev = obs.state_evidence.get(obs.state, [])[:3]
            self._event("observed", f"Observe {obs.state}", obs.state, "observed", source, evidence + state_ev)

        crawler_intents = self.normalizer.normalize_observation(obs, source=SOURCE_CRAWLER)
        # Dynamic, page-driven discovery: whatever actionable controls THIS product
        # actually exposes — size/colour/variant options, quantity selects,
        # save-for-later, gift options, etc. — become executable intents too, not
        # just the fixed catalogue. Risk is classified deterministically and
        # safety-first, and every one still flows through the same gate/validator.
        dynamic_intents = discover_dynamic_intents(obs, source=SOURCE_CRAWLER)
        self.dynamic_discovered += len(dynamic_intents)
        crawler_intents += dynamic_intents
        added = self.frontier.push_many(crawler_intents)
        for ni in added:
            self.graph.write_intent(self.scope, self.run_id, ni, "frontier_added", [ni.reason])
            if ni.risk == RISK_OBSERVE_ONLY or not ni.click_allowed:
                if ni.confidence >= 0.60:
                    self._event("found", ni.human_label, ni.expected_state, "observed_only", ni.source, [ni.canonical_key, ni.reason, f"conf={ni.confidence}"])

        if obs.state == STATE_CART and {"domain.cart_item", "domain.subtotal"} & self.observed_concepts:
            # CLOSE THE LOOP: the graph reasons about what SHOULD be tested here
            # (missed-scenario pivots) and feeds those actions back into the DFS
            # frontier FIRST — deterministically, independent of the LLM. This is
            # the graph improving coverage, not just reporting it.
            graph_intents = self._graph_driven_intents(obs.state)
            for n in self.frontier.push_many(graph_intents):
                self.graph_driven_added += 1
                self.graph.write_intent(self.scope, self.run_id, n, "frontier_added", ["graph-inferred missed scenario fed back into DFS"])
                self._event("frontier", n.human_label, n.expected_state, "added", n.source, [n.canonical_key, "graph reasoning -> coverage"])

            visible = [e.label for e in obs.elements if e.visible][:80]
            neighbors = self.neighbor_generator.generate(
                observed_concepts=self.observed_concepts,
                current_state=obs.state,
                visible_affordances=visible,
                max_neighbors=self.max_neighbors,
                normalizer=self.normalizer,
            )
            added_neighbors = self.frontier.push_many(neighbors)
            for n in added_neighbors:
                self.graph.write_intent(self.scope, self.run_id, n, "frontier_added", ["generated from graph/LLM neighbor search"])
                self._event("frontier", n.human_label, n.expected_state, "added", n.source, [n.canonical_key, n.risk])
        return obs

    async def _cart_preflight(self) -> None:
        result = await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label="Cart preflight")
        obs = result.observation
        # Baseline item count lets us prove a delta from THIS run even when a
        # previous run (or the user) left items in the cart, so provenance does
        # not silently report cart_delta_verified=false on a polluted cart.
        self.cart_count_baseline = _cart_item_count(obs)
        # Pre-existing must mean "had items", not "the word subtotal appears" —
        # an empty cart still renders "Subtotal (0 items)". Trust the nav count;
        # only fall back to concept detection if the count can't be parsed.
        if self.cart_count_baseline is not None:
            self.cart_preexisting = self.cart_count_baseline > 0
        else:
            self.cart_preexisting = "domain.cart_item" in obs.detected_concepts or "domain.subtotal" in obs.detected_concepts
        if self.cart_preexisting:
            self.cart_provenance = "preexisting_cart_before_run"
            self._capture_identity_from_observation(obs)
        self.graph.write_run_assertions(self.scope, self.run_id, {
            "cart_preflight": {
                "cart_preexisting": self.cart_preexisting,
                "cart_provenance": self.cart_provenance,
                "cart_title": self.cart_title,
            }
        })

    async def _seed_domain_intents(self) -> None:
        # Seed only gateway actions. Observed/LLM frontier fills the rest.
        for key in ["action.add_to_cart", "action.go_to_cart"]:
            spec = INTENTS[key]
            ni = self.normalizer._from_spec(spec, SOURCE_DOMAIN, None, 0.85, 0.85, 0.0, "domain gateway seed")
            if self.frontier.push(ni):
                self._event("frontier", ni.human_label, ni.expected_state, "added", ni.source, [ni.canonical_key, "domain gateway seed"])

    def _next_transition_intent(self, state: str) -> NormalizedIntent | None:
        if state == STATE_PRODUCT and not self.add_to_cart_validated:
            key = "action.add_to_cart"
        elif state in {STATE_PRODUCT, STATE_CART_CONFIRMATION}:
            key = "action.go_to_cart"
        elif state == STATE_CART:
            key = "action.proceed_to_checkout"
        else:
            return None
        spec = INTENTS[key]
        return self.normalizer._from_spec(spec, SOURCE_DOMAIN, None, 0.80, 0.80, 0.0, f"transition from {state}")

    async def _ensure_ready_for_intent(self, intent: NormalizedIntent, current_obs: PageObservation) -> BrowserUseResult | None:
        """Return a fresh observation when the current page needs stabilization.

        This is intentionally narrow. It does not change browser-use behavior;
        it prevents sending browser-use into a transitional cart surface for the
        checkout button, which caused ELEMENT_NOT_FOUND on Amazon smart-wagon.
        """
        if intent.canonical_key != "action.proceed_to_checkout":
            return None
        if current_obs.state != STATE_CART:
            return None
        text = (current_obs.text or "").lower()
        url = (current_obs.url or "").lower()
        has_checkout_concept = "action.proceed_to_checkout" in current_obs.detected_concepts
        transitional = (
            "smart-wagon" in url
            or "newitems=" in url
            or "placeholder" in text
            or "still loading" in text
            or not has_checkout_concept
        )
        if not transitional:
            return None
        self.frontier.stats.requires_replay += 1
        self._event(
            "replay",
            "Stabilize cart before Proceed to Checkout",
            current_obs.state,
            "requires_replay",
            intent.source,
            ["reason=cart_not_ready_for_checkout", f"url={current_obs.url[:120]}", f"has_checkout_concept={has_checkout_concept}"],
        )
        return await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label="Stable cart before checkout")

    async def _replay_to(self, state: str) -> BrowserUseResult:
        if state == STATE_PRODUCT:
            return await self.executor.navigate_and_observe(self.product_url, expected_state=STATE_PRODUCT, label="Replay product page")
        if state in {STATE_CART, STATE_CART_CONFIRMATION}:
            return await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label="Replay cart page")
        if state == STATE_CHECKOUT:
            # Checkout is reached through the frontier; do not replay by clicking final actions.
            return await self.executor.observe_current(label="Replay checkout unsupported", expected_state=STATE_CHECKOUT)
        return await self.executor.observe_current(label=f"Replay {state}", expected_state=state)

    def _record_replay_like(self, result: BrowserUseResult, label: str, expected_state: str) -> None:
        ok = result.observation.state == expected_state or (expected_state == STATE_CART_CONFIRMATION and result.observation.state == STATE_CART)
        status = "verified" if ok else "failed"
        ev = [f"expected={expected_state}", f"observed={result.observation.state}"] + result.evidence[:4]
        self._event("replay", label, result.observation.state, status, SOURCE_CRAWLER, ev)

    def _capture_identity_from_observation(self, obs: PageObservation) -> None:
        """Capture product identity by ASIN — no hardcoded name, no false matches.

        Identity is anchored on the ASIN from the product URL. Recommendation
        carousels ("customers also bought ...") have *different* ASINs, so a name
        is only trusted when it sits next to OUR ASIN. Cart/product match is
        proven by OUR ASIN actually appearing in the cart observation, never by a
        loose title overlap (which previously matched a recommended book).
        """
        # Titles are evidence only, and are read from the alt text adjacent to
        # our ASIN so a recommended product can never be mistaken for ours.
        if obs.state == STATE_PRODUCT and not self.product_title:
            self.product_title = _title_near_asin(obs, self.product_asin)[:220]
        if obs.state == STATE_CART:
            cart_name = _title_near_asin(obs, self.product_asin)
            if cart_name and not self.cart_title:
                self.cart_title = cart_name[:220]
            # Item-count delta from this run, robust to a pre-existing cart.
            count = _cart_item_count(obs)
            if (
                self.add_to_cart_validated
                and count is not None
                and self.cart_count_baseline is not None
                and count > self.cart_count_baseline
            ):
                self.cart_delta_verified = True
            # Authoritative product match: OUR ASIN is present in the cart.
            if _asin_in_observation(obs, self.product_asin):
                self.cart_product_verified = True

    def _infer_graph_scenarios(self) -> None:
        # Primary path: let the GRAPH infer missed scenarios with a Cypher query
        # over the Concept nodes (which exist, which were validated). Falls back
        # to in-memory rule evaluation only when Neo4j is unavailable, so the
        # reasoning is genuinely graph-driven whenever a graph is present.
        candidates = self._infer_from_graph()
        if candidates is None:
            candidates = self._infer_in_memory()
        existing = {s["key"] for s in self.scenarios}
        for s in candidates:
            if s["key"] not in existing:
                self.scenarios.append(s)
                self.graph.write_scenario(self.scope, self.run_id, s["key"], s["title"], s["status"], s["depends_on"], s["source"])

    def _infer_from_graph(self) -> list[dict[str, Any]] | None:
        if not self.graph.enabled:
            return None
        try:
            rows = self.graph.infer_missed_scenarios(self.scope, INFERENCE_RULES)
        except Exception as exc:
            self.log("graph", f"graph inference failed, using fallback: {exc}")
            return None
        return [
            {"key": r["key"], "title": r["title"], "status": r["status"], "depends_on": r["depends_on"], "source": SOURCE_GRAPH}
            for r in rows
        ]

    async def _verify_cart_mutation(self, pre: tuple) -> tuple[bool, PageObservation, list[str]]:
        """Re-read the canonical cart and confirm a real item-count/subtotal delta.

        Returns (changed, post_observation, evidence). This is the authoritative
        check for quantity changes, independent of browser-use's flaky SPA view.
        """
        pre_count, pre_sub = pre
        post = await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label="Cart state after quantity change")
        post_obs = post.observation
        post_count, post_sub = _cart_item_count(post_obs), _cart_subtotal(post_obs)
        changed = bool(
            (pre_count is not None and post_count is not None and post_count != pre_count)
            or (pre_sub and post_sub and pre_sub != post_sub)
        )
        ev = [f"cart_count {pre_count}->{post_count}", f"subtotal {pre_sub}->{post_sub}", f"verified_change={changed}"]
        return changed, post_obs, ev

    async def _restore_product_to_cart(self) -> PageObservation:
        """Re-add the product after a destructive/save test emptied the cart.

        Removing the item was already verified; re-adding it lets the end-to-end
        flow still reach checkout and demonstrates a full add -> remove -> verify
        -> re-add loop. Capped so a failed re-add can never loop forever.
        """
        if self.restores_done >= 3:
            back = await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label="Cart (restore capped)")
            return back.observation
        self.restores_done += 1
        spec = INTENTS.get("action.add_to_cart")
        await self.executor.navigate_and_observe(self.product_url, expected_state=STATE_PRODUCT, label="Restore: reopen product to re-add")
        ni = self.normalizer._from_spec(spec, SOURCE_CRAWLER, None, 0.9, 0.9, 0.0, "restore cart after destructive/save test")
        ni.expected_state = STATE_PRODUCT
        res = await self.executor.execute_intent(ni)
        ok = res.status in {"validated", "clicked_observed", "already_satisfied"}
        self._event(
            "replay", "Restore product to cart", res.observation.state,
            "restored" if ok else res.status, SOURCE_CRAWLER,
            ["re-added the product after a destructive/save test so checkout can still complete"],
        )
        back = await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label="Cart after restore")
        return back.observation

    def _graph_driven_intents(self, state: str) -> list[NormalizedIntent]:
        """Turn graph-inferred missed scenarios into executable frontier intents.

        For each inferred-missed scenario whose pivot is an action valid in the
        current state and not yet completed, emit a SOURCE_GRAPH intent. The
        frontier's risk gates still decide whether it is clicked or observed, so
        this only ever ADDS coverage, never bypasses safety.
        """
        candidates = self._infer_from_graph()
        if candidates is None:
            candidates = self._infer_in_memory()
        out: list[NormalizedIntent] = []
        for s in candidates:
            rule = _RULE_BY_KEY.get(s["key"])
            pivot = rule.get("pivot") if rule else None
            if not pivot:
                continue
            if self.frontier.is_completed(pivot):
                continue
            spec = INTENTS.get(pivot)
            if not spec or state not in spec.expected_states:
                continue
            ni = self.normalizer._from_spec(spec, SOURCE_GRAPH, None, 0.82, 0.82, 0.0, f"graph inference: {s['key']}")
            ni.expected_state = state
            out.append(ni)
        return out

    def _infer_in_memory(self) -> list[dict[str, Any]]:
        """Deterministic fallback mirroring the graph rules (no Neo4j needed)."""
        return infer_missed_in_memory(self.observed_concepts, self._validated_concepts(), INFERENCE_RULES)

    def _validated_concepts(self) -> set[str]:
        return {rec.canonical_key for rec in self.frontier.canonical_success.values()}

    def _run_assertions(self) -> dict[str, Any]:
        end_to_end = bool(self.add_to_cart_validated and (self.cart_delta_verified or self.cart_product_verified) and self.proceed_to_checkout_validated)
        assertions = {
            "add_to_cart_validated": self.add_to_cart_validated,
            "proceed_to_checkout_validated": self.proceed_to_checkout_validated,
            "cart_preexisting": self.cart_preexisting,
            "cart_delta_verified": self.cart_delta_verified,
            "cart_product_verified": self.cart_product_verified,
            "cart_provenance": self.cart_provenance or "unknown",
            "product_title": self.product_title,
            "cart_title": self.cart_title,
            "end_to_end_checkout_flow_validated": end_to_end,
            "crawler_engine": "browser-use",
        }
        try:
            self.graph.write_run_assertions(self.scope, self.run_id, assertions)
        except Exception:
            pass
        return assertions

    def _living_graph_section(self) -> dict[str, Any]:
        seen = self.graph.observed_keys(self.scope) | self.observed_concepts
        expected = ["action.add_to_cart", "action.go_to_cart", "action.proceed_to_checkout", "domain.quantity_control", "domain.subtotal", "action.delete_item", "action.save_for_later", "domain.checkout_boundary", "domain.final_order_boundary"]
        # Prefer the graph's own notion of absence (expected Concept never
        # validated); fall back to the local seen-set diff when Neo4j is off.
        missing = []
        if self.graph.enabled:
            try:
                graph_missing = set(self.graph.missing_expected_concepts(self.scope))
                missing = [k for k in expected if k in graph_missing]
            except Exception:
                missing = []
        if not missing:
            missing = [k for k in expected if k not in seen]
        recs = []
        for key in missing[:5]:
            spec = INTENTS.get(key)
            if spec:
                recs.append({"canonical_key": key, "human_label": spec.human_label, "expected_state": spec.expected_states[0] if spec.expected_states else "unknown", "reason": f"{key} is expected but not yet observed/validated in this scoped graph."})
        return {
            "stable": max(0, len(seen) - len(missing)),
            "missing": missing,
            "recommended_retests": recs,
            "neighbor_llm_calls": self.neighbor_generator.total_llm_calls,
            "neighbor_fallback_calls": self.neighbor_generator.total_fallback_calls,
        }

    def _event(self, kind: str, label: str, state: str, status: str, source: str, evidence: list[str]) -> None:
        self.events.append(ExplorationEvent(len(self.events) + 1, kind, label, state, status, source, evidence))
        if self.debug:
            # quiet mode: only print important events (clicked, blocked, key transitions)
            quiet_skip = {"found", "observed", "frontier", "replay"}
            if kind.lower() not in quiet_skip:
                print(f"[dfs][event] {kind.upper()} {label} state={state} status={status} source={source} evidence={evidence[:3]}")


def _looks_like_dom_line(line: str) -> bool:
    """True for browser-use DOM-representation lines that are not human text.

    The browser-use ``llm_representation`` text contains markup such as
    ``[4631]<a id=nav-global-location-popover-link role=button />`` which must
    not be captured as a product title.
    """
    s = line.strip()
    if not s:
        return True
    if "<" in s or ">" in s:
        return True
    if s.startswith("[") and "]" in s[:8]:
        return True
    low = s.lower()
    return any(tok in low for tok in ("id=", "role=", "href=", "aria-label=", "class=", "selector=", "xpath="))


def _asin_from_url(url: str) -> str:
    """Extract the Amazon ASIN (stable product id) from a product URL."""
    m = re.search(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})", url or "")
    return m.group(1) if m else ""


def _checkout_reached_ok(after_state: str, after_url: str, error: str) -> bool:
    """True when Proceed to Checkout reached the prototype boundary.

    For this take-home prototype, checkout is the terminal boundary. Amazon may
    redirect to sign-in before showing address/payment; that still proves the
    checkout boundary was reached. Wrong-target clicks are still not accepted.
    """
    err_low = (error or "").lower()
    reached = after_state in {STATE_CHECKOUT, "final_order_boundary"}
    wrong_target = "wrong_target_for_checkout" in err_low
    return reached and not wrong_target


def _cart_url_for(product_url: str) -> str:
    """Cart URL on the SAME Amazon marketplace/domain as the product URL.

    amazon.in product -> amazon.in cart, amazon.co.uk -> amazon.co.uk, etc.
    Falls back to amazon.com if the host can't be parsed.
    """
    try:
        p = urlparse(product_url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}/gp/cart/view.html"
    except Exception:
        pass
    return "https://www.amazon.com/gp/cart/view.html"


def _clean_name(name: str) -> str:
    return html.unescape(name or "").strip()


_RULE_BY_KEY: dict[str, dict] = {r["key"]: r for r in INFERENCE_RULES}


def infer_missed_in_memory(observed_concepts: set[str], validated_concepts: set[str], rules: list[dict]) -> list[dict]:
    """Pure mirror of the graph inference query (used when Neo4j is unavailable).

    A scenario is MISSED when every prerequisite concept was observed but the
    pivot action that would prove the behaviour was never validated.
    """
    from ..domain.checkout_contract import SOURCE_GRAPH as _SG
    out = []
    for rule in rules:
        if not set(rule["requires"]) <= observed_concepts:
            continue
        pivot = rule.get("pivot")
        if pivot is None or pivot not in validated_concepts:
            out.append({
                "key": rule["key"], "title": rule["title"], "status": rule["status"],
                "depends_on": list(rule["requires"]), "source": _SG,
            })
    return out


def _asin_in_observation(obs, asin: str) -> bool:
    """True when OUR ASIN appears in the observation (text or element hrefs).

    Recommendation links carry different ASINs, so this stays specific to the
    product under test.
    """
    if not asin:
        return False
    a = asin.lower()
    if a in (obs.text or "").lower():
        return True
    for e in getattr(obs, "elements", []) or []:
        if a in (getattr(e, "href", "") or "").lower() or a in (e.haystack or ""):
            return True
    return False


def _title_near_asin(obs, asin: str) -> str:
    """Product name taken from the alt text adjacent to OUR ASIN.

    Anchoring on the ASIN avoids picking the longest recommendation alt on the
    page. Falls back to Amazon's productTitle element when present.
    """
    text = obs.text or ""
    if asin:
        idx = text.find(asin)
        if idx >= 0:
            # Pick the alt text physically CLOSEST to our ASIN link — the item's
            # own image — not the longest alt on the page (a recommendation could
            # be longer but sits far from our ASIN).
            best, best_dist = "", 10 ** 9
            for m in re.finditer(r"alt=([^/\n>]+?)(?:\s*/?>|\n)", text):
                a = m.group(1).strip()
                if len(a) <= 12 or any(b in a.lower() for b in ("sprite", "logo", "icon", "amazon")):
                    continue
                dist = abs(m.start() - idx)
                if dist < best_dist:
                    best, best_dist = a, dist
            if best and best_dist <= 500:
                return _clean_name(best)
    m = re.search(r"id=productTitle[^\n]*\n\s*([^\n\[<]{10,200})", text)
    if m:
        return _clean_name(m.group(1).strip())
    return ""


def _cart_item_count(obs) -> int | None:
    """Parse the nav cart count (``aria-label=N items in cart``)."""
    m = re.search(r"(\d+)\s+items?\s+in\s+cart", (obs.text or "").lower())
    return int(m.group(1)) if m else None


def _cart_subtotal(obs) -> str | None:
    """Parse the cart subtotal amount as a normalized numeric string.

    Currency-agnostic: handles "Subtotal (2 items): INR 2,467.73", "$13.08", etc.
    Returns the digits ("2467.73") for stable equality comparison, or None.
    """
    # Require a money-shaped value (two decimals) so "(2 items)" is not mistaken
    # for the amount. Non-greedy skip jumps over "(N items): INR " etc.
    m = re.search(r"subtotal[^\n]{0,40}?([0-9][0-9.,]*\.\d{2})", (obs.text or "").lower())
    if not m:
        return None
    return m.group(1).replace(",", "")
