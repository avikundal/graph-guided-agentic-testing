from __future__ import annotations

import html
import json
import re
import uuid
from typing import Any
from urllib.parse import urlparse

from ..config import DATA_DIR
from ..domain.amazon_auth import AUTH_FILE, base_url_for, reset_amazon_cart, verify_auth_state
from ..domain.checkout_contract import (
    CAUSAL_EXPECTATIONS,
    EXPECTED_CONCEPTS,
    INFERENCE_RULES,
    INTENTS,
    RISK_MUTATING_CLICK,
    SOURCE_CRAWLER,
    SOURCE_GRAPH,
    STATE_CART,
    STATE_CHECKOUT,
    STATE_PRODUCT,
)
from ..graph.store import GraphStore
from ..reporting.report import ExplorationEvent, ExplorationReport, render_report
from .browser_use_executor import BrowserUseIntentExecutor, BrowserUseResult
from .graph_expansion import expand_from_graph
from .page_observer import PageObservation
from .safety_guard import is_cart_relevant_action, is_other_product_label, product_tokens
from .semantic_normalizer import NormalizedIntent, SemanticNormalizer


class GraphGuidedExplorer:
    """Autonomous browser-use crawler followed by graph-directed gap probes."""

    _CRAWL_MAX_ROUNDS = 3
    _GRAPH_MAX_ROUNDS = 2

    def __init__(
        self,
        *,
        product_url: str,
        tenant_id: str,
        project_id: str,
        feature_key: str,
        headless: bool = True,
        enable_living_graph: bool = False,
        reset_graph: bool = False,
        reset_cart: bool = False,
        debug: bool = False,
    ):
        self.product_url = product_url
        self.scope = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "feature_key": f"feature.{feature_key}" if not feature_key.startswith("feature.") else feature_key,
        }
        self.feature_display_key = feature_key
        self.run_id = f"run_{uuid.uuid4().hex[:12]}"
        self.headless = headless
        self.enable_living_graph = enable_living_graph
        self.reset_graph = reset_graph
        self.reset_cart = reset_cart
        self.debug = debug

        self.executor = BrowserUseIntentExecutor(headless=headless, debug=debug)
        self.executor.set_safety_context(product_url)
        self.normalizer = SemanticNormalizer()
        self.graph = GraphStore()
        self.events: list[ExplorationEvent] = []
        self.scenarios: list[dict[str, Any]] = []
        self.step = 0
        self.visited_states: set[str] = set()
        self.observed_concepts: set[str] = set()
        self.observed_signatures: set[str] = set()

        self.checkout_reached = False
        self.add_to_cart_validated = False
        self.proceed_to_checkout_validated = False
        self.cart_preexisting = False
        self.cart_delta_verified = False
        self.cart_product_verified = False
        self.cart_provenance = "unknown"
        self.product_title = ""
        self.cart_title = ""
        self.product_asin = _asin_from_url(product_url)
        self.cart_url = _cart_url_for(product_url)
        self.cart_count_baseline: int | None = None
        self.restores_done = 0

        self.crawl_validated_concepts: set[str] = set()
        self.graph_surfaced_scenarios: list[dict] = []
        self.graph_directed_clicks = 0
        self.clicked_labels: set[str] = set()
        self.action_attempt_seq = 0
        self.graph_probe_round = 0

    def log(self, kind: str, msg: str) -> None:
        if self.debug:
            print(f"[{kind}] {msg}")

    async def run(self) -> str:
        self.graph.verify()
        self.graph.ensure_constraints()
        if self.reset_graph:
            self.graph.reset_scope(self.scope)
        self.graph.init_run(self.scope, self.run_id, self.product_url)
        self.graph.seed_expected_concepts(self.scope, EXPECTED_CONCEPTS)
        self.graph.seed_causal_expectations(self.scope, CAUSAL_EXPECTATIONS)

        signed_in, reason = await verify_auth_state(headless=True, base_url=base_url_for(self.product_url))
        if not signed_in:
            return (
                "NOT SIGNED IN for this marketplace - run scripts/login_amazon.py "
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
            self._record_observation_check(initial, "Initial product page", STATE_PRODUCT)
            current_obs = await self._ingest_observation(initial.observation, source=SOURCE_CRAWLER)
            if current_obs.state != STATE_PRODUCT:
                self._event(
                    "blocked",
                    "Product page not grounded",
                    current_obs.state,
                    "aborted",
                    SOURCE_CRAWLER,
                    [
                        f"expected={STATE_PRODUCT}",
                        f"observed={current_obs.state}",
                        "crawl/graph skipped because graph needs real page evidence before probing",
                    ],
                )
                self.log("stop", f"aborted: initial product page observed as {current_obs.state}")
            else:
                await self._autonomous_loop(current_obs)
        finally:
            await self.executor.close()

        living = self._living_graph_section() if self.enable_living_graph else None
        coverage = self._coverage_summary()
        report = ExplorationReport(
            run_id=self.run_id,
            feature="Amazon checkout - autonomous browser-use + graph-guided gap exploration",
            events=self.events,
            graph_scenarios=self.scenarios,
            living_graph=living,
            run_assertions=self._run_assertions(),
            safety_notes=[
                "browser-use executes UI actions using DOM, ARIA labels, screenshots/layout, and page context.",
                "The free crawl stops on action-level convergence, not on first concept stagnation.",
                "Graph expansion runs after crawler convergence and sends targeted probes back to browser-use.",
                "The deny-list veto blocks final payment, cross-product/external navigation, repeated free-crawl actions, and account/session-destroying controls.",
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
        graph_events = [e for e in self.events if e.source == SOURCE_GRAPH]
        graph_covered = len({
            e.label for e in graph_events
            if e.kind in {"clicked", "found"} or e.status in {"graph_directed", "crawl_validated"}
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
            "graph_directed_covered": graph_covered,
            "absent": absent,
        }

    def _graph_impact_summary(self, coverage: dict[str, Any]) -> dict[str, Any]:
        validation_statuses = {"crawl_validated", "graph_directed"}
        validated_total = sum(1 for e in self.events if e.status in validation_statuses)
        validated_graph = sum(1 for e in self.events if e.status in validation_statuses and e.source == SOURCE_GRAPH)
        validated_direct = validated_total - validated_graph
        scenarios_total = len(self.scenarios)
        missed = sum(1 for s in self.scenarios if s.get("status") == "INFERRED_MISSED")
        return {
            "behaviors_validated_by_crawler_alone": validated_direct,
            "scenarios_surfaced_only_by_graph": scenarios_total,
            "graph_scenarios_missed_gaps": missed,
            "graph_scenarios_boundary_safety": scenarios_total - missed,
            "graph_surfaced_missed": [s.get("title", "") for s in self.graph_surfaced_scenarios],
            "graph_directed_clicks": self.graph_directed_clicks,
            "graph_directed_covered": coverage.get("graph_directed_covered", 0),
            "concept_coverage_pct": coverage.get("observed_pct", 0),
            "structural_gaps_flagged": coverage.get("absent", []),
        }

    async def _autonomous_loop(self, current_obs: PageObservation) -> None:
        if current_obs.state != STATE_PRODUCT:
            self.log("stop", f"crawl skipped: expected product_detail, got {current_obs.state}")
            return
        add_spec = INTENTS.get("action.add_to_cart")
        add_intent = self.normalizer._from_spec(add_spec, SOURCE_CRAWLER, None, 0.95, 0.95, 0.0, "required cart setup")
        add_intent.expected_state = STATE_PRODUCT
        res = await self.executor.execute_intent(add_intent)
        self._ingest_autonomous(res, STATE_PRODUCT)
        await self._open_cart_after_add()

        last_obs = current_obs
        stagnant = 0
        prev_sig = None
        crawl_rounds = 0
        while crawl_rounds < self._CRAWL_MAX_ROUNDS and stagnant < 2:
            crawl_rounds += 1
            untried = self._untried_visible_labels(last_obs)
            hint = (" Controls you have NOT tried yet include: " + "; ".join(sorted(untried)[:6]) + ".") if untried else ""
            res = await self.executor.explore_autonomously(
                goal=(
                    "Test this shopping cart thoroughly. Try every distinct control you have not tried yet: "
                    "increase and decrease quantity, save for later, move back to cart, remove/delete, "
                    "apply a coupon including an invalid value, and gift options." + hint
                ),
                expected_state=STATE_CART,
                max_steps=8,
            )
            self._ingest_autonomous(res, res.observation.state or STATE_CART)
            await self._ingest_observation(res.observation, source=SOURCE_CRAWLER)
            last_obs = res.observation
            sig = (len(self.observed_concepts), len(self.clicked_labels), len(self.crawl_validated_concepts))
            stagnant = stagnant + 1 if sig == prev_sig else 0
            prev_sig = sig
            self.log("crawl", f"round {crawl_rounds}: concepts={sig[0]} labels={sig[1]} validated={sig[2]} untried={len(untried)} stagnant={stagnant}")

        graph_rounds = 0
        while graph_rounds < self._GRAPH_MAX_ROUNDS:
            graph_rounds += 1
            self._infer_graph_scenarios()
            missed = await self._graph_expansion(STATE_CART)
            if not missed:
                break
            before = len(self.observed_concepts)
            await self._run_graph_probes(missed)
            self.log("graph", f"gap-closing round {graph_rounds}: surfaced {len(missed)}, concepts now {len(self.observed_concepts)}")
            if len(self.observed_concepts) == before:
                break

        res3 = await self.executor.explore_autonomously(
            goal="Go to your shopping cart and click Proceed to Checkout to reach the secure checkout page. Do NOT place an order or pay. Stop as soon as checkout appears.",
            expected_state=STATE_CART,
            max_steps=4,
            block_repeats=False,
        )
        self._ingest_autonomous(res3, STATE_CHECKOUT)
        final_obs = res3.observation
        if final_obs.state == STATE_CHECKOUT or "checkout" in (final_obs.url or "").lower():
            self.checkout_reached = True
            self.proceed_to_checkout_validated = True
            self.observed_concepts.add("domain.checkout_boundary")
            await self._ingest_observation(final_obs, source=SOURCE_CRAWLER)
        self._infer_graph_scenarios()
        self.log("stop", f"converged after {crawl_rounds} free-crawl + {graph_rounds} graph round(s)")

    async def _open_cart_after_add(self) -> PageObservation:
        cart = await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label="Open cart after add")
        obs = cart.observation
        if (_cart_item_count(obs) or 0) > 0:
            self.add_to_cart_validated = True
            self.cart_provenance = "cart_confirmation_or_cart_delta_verified"
            if not self.cart_preexisting:
                self.cart_delta_verified = True
            self.observed_concepts.update({"action.add_to_cart", "domain.cart_item"})
            self.crawl_validated_concepts.add("action.add_to_cart")
        else:
            obs = await self._restore_product_to_cart()
            if (_cart_item_count(obs) or 0) > 0:
                self.add_to_cart_validated = True
                self.crawl_validated_concepts.add("action.add_to_cart")
        await self._ingest_observation(obs, source=SOURCE_CRAWLER)
        self.executor.set_product_title(self.product_title or self.cart_title)
        return obs

    def _untried_visible_labels(self, obs: PageObservation) -> set[str]:
        brand = product_tokens(self.product_title or self.cart_title)
        out: set[str] = set()
        for el in getattr(obs, "elements", None) or []:
            if not getattr(el, "visible", False) or getattr(el, "in_nav_or_header", False):
                continue
            if not (getattr(el, "clickable", False) or getattr(el, "interactable", False)):
                continue
            lbl = " ".join((getattr(el, "aria_label", "") or getattr(el, "text", "") or getattr(el, "value", "") or "").split())
            low = lbl.lower()[:60]
            if len(low) < 3 or low.startswith("<") or low in self.clicked_labels:
                continue
            if is_other_product_label(lbl, brand):
                continue
            if obs.state == STATE_CART and not is_cart_relevant_action(lbl):
                continue
            out.add(low)
        return out

    def _ingest_autonomous(
        self,
        res: BrowserUseResult,
        state: str,
        *,
        source: str = SOURCE_CRAWLER,
        graph_concepts: set[str] | None = None,
    ) -> None:
        graph_concepts = graph_concepts or set()
        probe = source == SOURCE_GRAPH
        title_tokens = product_tokens(self.product_title or self.cart_title)
        seen: set[str] = set()
        for art in res.artifacts:
            if art.action_type not in {"click", "fill", "select"}:
                continue
            label = html.unescape(html.unescape((art.target_label or "").strip()))
            key = label.lower()
            if not label or key in seen:
                continue
            seen.add(key)
            if is_other_product_label(label, title_tokens):
                continue
            if (art.state or state) == STATE_CART and not is_cart_relevant_action(label):
                continue
            self.clicked_labels.add(key)
            concept = _action_to_concept(label)
            act_state = art.state or state
            is_graph = probe
            eff_source = SOURCE_GRAPH if is_graph else SOURCE_CRAWLER
            status = "graph_directed" if is_graph and concept else ("graph_explored" if is_graph else ("crawl_validated" if concept else "crawl_explored"))
            self._write_action_attempt(
                art,
                res,
                status=status,
                source=eff_source,
                concept=concept,
                probe_key=self._probe_key_for_concept(concept) if is_graph else None,
            )
            if concept:
                ni = NormalizedIntent(
                    canonical_key=concept,
                    human_label=label[:60],
                    expected_state=act_state,
                    source=eff_source,
                    risk=RISK_MUTATING_CLICK,
                    priority=0.6,
                    confidence=0.9,
                )
                self.graph.write_intent(self.scope, self.run_id, ni, status, [f"autonomous {art.action_type}"])
                self.observed_concepts.add(concept)
                self.crawl_validated_concepts.add(concept)
            if is_graph:
                self.graph_directed_clicks += 1
            self._event(
                "clicked",
                label[:58] or concept or "action",
                act_state,
                status,
                eff_source,
                [("graph-directed probe" if is_graph else "autonomous") + f" {art.action_type}"] + ([f"concept={concept}"] if concept else []),
            )
        if res.error and "safety_veto" in res.error:
            self._event("blocked", "Safety veto (deny-list)", state, "vetoed", source, [res.error[:120]])

    def _write_action_attempt(
        self,
        art,
        res: BrowserUseResult,
        *,
        status: str,
        source: str,
        concept: str | None,
        probe_key: str | None,
    ) -> None:
        self.action_attempt_seq += 1
        before = res.before
        after = res.observation
        self.graph.write_action_attempt(
            self.scope,
            self.run_id,
            action_id=f"action_{self.action_attempt_seq:04d}",
            step=self.action_attempt_seq,
            source=source,
            action_type=art.action_type,
            target_label=html.unescape(html.unescape((art.target_label or "").strip()))[:180],
            selector=(art.selector or "")[:240],
            status=status,
            page_state_before=(before.state if before else art.state) or "",
            page_state_after=(after.state if after else "") or "",
            url_before=(before.url if before else art.url) or "",
            url_after=(after.url if after else "") or "",
            concept=concept,
            probe_key=probe_key,
            evidence=list(art.evidence or [])[:12],
            veto_reason=_extract_veto_reason(res.error),
            repeat_key=_action_repeat_key(art.target_label),
        )

    async def _graph_expansion(self, state: str) -> list[dict]:
        try:
            absent = self.graph.missing_expected_concepts(self.scope) or []
        except Exception:
            absent = [c for c in EXPECTED_CONCEPTS if c not in self.observed_concepts]
        try:
            graph_context = self.graph.graph_view(self.scope) or {}
        except Exception:
            graph_context = {}
        proposals = expand_from_graph(
            feature=self.feature_display_key,
            state=state,
            observed_concepts=self.observed_concepts,
            validated_concepts=self.crawl_validated_concepts,
            expected_concepts=EXPECTED_CONCEPTS,
            absent_concepts=absent,
            visible_affordances=[],
            graph_context=graph_context,
            max_items=4,
            debug=self.debug,
        )
        self.graph_probe_round += 1
        for p in proposals:
            p["key"] = _probe_key(p, self.graph_probe_round, len(self.graph_surfaced_scenarios) + 1)
            self.graph_surfaced_scenarios.append(p)
            self.graph.write_graph_probe(
                self.scope,
                self.run_id,
                key=p["key"],
                title=p["title"],
                why=p.get("why", ""),
                instruction=p.get("probe", ""),
                concept=p.get("concept"),
                target_state=self._state_for_concept(p.get("concept") or ""),
                status="proposed",
                round_no=self.graph_probe_round,
                source=SOURCE_GRAPH,
            )
            self._event(
                "graph_surfaced",
                p["title"][:60],
                state,
                "graph_reasoned",
                SOURCE_GRAPH,
                [p.get("why", "")[:80]] + ([f"concept={p['concept']}"] if p.get("concept") else []),
            )
        if proposals:
            self.log("graph", f"surfaced {len(proposals)} missed scenario(s)")
        return proposals

    def _state_for_concept(self, concept: str) -> str:
        spec = INTENTS.get(concept)
        if spec and getattr(spec, "expected_states", None):
            return spec.expected_states[0]
        if concept == "action.add_to_cart":
            return STATE_PRODUCT
        if concept in ("domain.checkout_boundary", "domain.final_order_boundary"):
            return STATE_CHECKOUT
        return STATE_CART

    def _probe_key_for_concept(self, concept: str | None) -> str | None:
        if not concept:
            return None
        for p in reversed(self.graph_surfaced_scenarios):
            if p.get("concept") == concept and p.get("key"):
                return p["key"]
        return None

    async def _run_graph_probes(self, missed: list[dict]) -> None:
        for m in missed:
            st = self._state_for_concept(m.get("concept") or "")
            if st == STATE_CHECKOUT:
                continue
            if st == STATE_PRODUCT:
                await self.executor.navigate_and_observe(self.product_url, expected_state=STATE_PRODUCT, label="Graph probe product page")
                probe_state = STATE_PRODUCT
            else:
                await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label="Graph probe cart")
                probe_state = STATE_CART
            surfaced_concepts = {m["concept"]} if m.get("concept") else set()
            self.log("graph", f"probing 1 scenario on {st}: {m.get('title', '')[:60]}")
            if m.get("key"):
                self.graph.write_graph_probe(
                    self.scope,
                    self.run_id,
                    key=m["key"],
                    title=m["title"],
                    why=m.get("why", ""),
                    instruction=m.get("probe", ""),
                    concept=m.get("concept"),
                    target_state=st,
                    status="executing",
                    round_no=self.graph_probe_round,
                    source=SOURCE_GRAPH,
                )
            res = await self.executor.explore_autonomously(
                goal=(
                    "A testing knowledge graph believes this one scenario was missed on this page. "
                    f"Try only this scenario, then stop: {m['probe']}"
                ),
                expected_state=probe_state,
                max_steps=4,
                block_repeats=False,
            )
            self._ingest_autonomous(res, probe_state, source=SOURCE_GRAPH, graph_concepts=surfaced_concepts)
            await self._ingest_observation(res.observation, source=SOURCE_CRAWLER)
            if m.get("key"):
                self.graph.write_graph_probe(
                    self.scope,
                    self.run_id,
                    key=m["key"],
                    title=m["title"],
                    why=m.get("why", ""),
                    instruction=m.get("probe", ""),
                    concept=m.get("concept"),
                    target_state=st,
                    status="executed",
                    round_no=self.graph_probe_round,
                    source=SOURCE_GRAPH,
                )

    async def _ingest_observation(self, obs: PageObservation, *, source: str) -> PageObservation:
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
        return obs

    async def _cart_preflight(self) -> None:
        result = await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label="Cart preflight")
        obs = result.observation
        self.cart_count_baseline = _cart_item_count(obs)
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

    def _record_observation_check(self, result: BrowserUseResult, label: str, expected_state: str) -> None:
        ok = result.observation.state == expected_state
        status = "verified" if ok else "failed"
        ev = [f"expected={expected_state}", f"observed={result.observation.state}"] + result.evidence[:4]
        self._event("replay", label, result.observation.state, status, SOURCE_CRAWLER, ev)

    def _capture_identity_from_observation(self, obs: PageObservation) -> None:
        if obs.state == STATE_PRODUCT and not self.product_title:
            self.product_title = _title_near_asin(obs, self.product_asin)[:220]
        if obs.state == STATE_CART:
            cart_name = _title_near_asin(obs, self.product_asin)
            if cart_name and not self.cart_title:
                self.cart_title = cart_name[:220]
            count = _cart_item_count(obs)
            if (
                self.add_to_cart_validated
                and count is not None
                and self.cart_count_baseline is not None
                and count > self.cart_count_baseline
            ):
                self.cart_delta_verified = True
            if _asin_in_observation(obs, self.product_asin):
                self.cart_product_verified = True

    def _infer_graph_scenarios(self) -> None:
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

    async def _restore_product_to_cart(self) -> PageObservation:
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
            "replay",
            "Restore product to cart",
            res.observation.state,
            "restored" if ok else res.status,
            SOURCE_CRAWLER,
            ["re-added the product after a destructive/save test so checkout can still complete"],
        )
        back = await self.executor.navigate_and_observe(self.cart_url, expected_state=STATE_CART, label="Cart after restore")
        return back.observation

    def _infer_in_memory(self) -> list[dict[str, Any]]:
        return infer_missed_in_memory(self.observed_concepts, self._validated_concepts(), INFERENCE_RULES)

    def _validated_concepts(self) -> set[str]:
        return set(self.crawl_validated_concepts)

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
        expected = [
            "action.add_to_cart",
            "action.go_to_cart",
            "action.proceed_to_checkout",
            "domain.quantity_control",
            "domain.subtotal",
            "action.delete_item",
            "action.save_for_later",
            "domain.checkout_boundary",
            "domain.final_order_boundary",
        ]
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
                recs.append({
                    "canonical_key": key,
                    "human_label": spec.human_label,
                    "expected_state": spec.expected_states[0] if spec.expected_states else "unknown",
                    "reason": f"{key} is expected but not yet observed/validated in this scoped graph.",
                })
        return {"stable": max(0, len(seen) - len(missing)), "missing": missing, "recommended_retests": recs}

    def _event(self, kind: str, label: str, state: str, status: str, source: str, evidence: list[str]) -> None:
        self.events.append(ExplorationEvent(len(self.events) + 1, kind, label, state, status, source, evidence))
        if self.debug:
            quiet_skip = {"found", "observed", "replay"}
            if kind.lower() not in quiet_skip:
                actor = "graph" if source == SOURCE_GRAPH else "crawler"
                print(f"[event][{actor}] {kind.upper()} {label} state={state} status={status} evidence={evidence[:3]}")


def _asin_from_url(url: str) -> str:
    m = re.search(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})", url or "")
    return m.group(1) if m else ""


_ACTION_CONCEPT_MAP = (
    ("save for later", "action.save_for_later"),
    ("move to cart", "action.move_to_cart"),
    ("decrease quantity", "action.change_quantity"),
    ("increase quantity", "action.change_quantity"),
    ("change quantity", "action.change_quantity"),
    ("quantity", "action.change_quantity"),
    ("delete", "action.delete_item"),
    ("remove", "action.delete_item"),
    ("proceed to checkout", "action.proceed_to_checkout"),
    ("proceed to buy", "action.proceed_to_checkout"),
    ("checkout", "action.proceed_to_checkout"),
    ("add to cart", "action.add_to_cart"),
    ("addtocart", "action.add_to_cart"),
    ("coupon", "capability.promo_code"),
    ("promo", "capability.promo_code"),
    ("offer", "capability.promo_code"),
    ("gift", "capability.promo_code"),
)


_RULE_BY_KEY: dict[str, dict] = {r["key"]: r for r in INFERENCE_RULES}


def _action_to_concept(label: str) -> str | None:
    low = (label or "").lower()
    for kw, concept in _ACTION_CONCEPT_MAP:
        if kw in low:
            return concept
    return None


def _probe_key(proposal: dict, round_no: int, index: int) -> str:
    raw = proposal.get("concept") or proposal.get("title") or f"probe_{index}"
    slug = re.sub(r"[^a-z0-9]+", "_", str(raw).lower()).strip("_")[:48] or f"probe_{index}"
    return f"probe_r{round_no}_{index}_{slug}"


def _extract_veto_reason(error: str) -> str:
    if "safety_veto:" not in (error or ""):
        return ""
    return (error.split("safety_veto:", 1)[1].split(";", 1)[0].split("|", 1)[0]).strip()[:120]


def _action_repeat_key(label: str) -> str:
    low = re.sub(r"\s+", " ", (label or "").strip().lower())
    if not low:
        return ""
    if any(t in low for t in ("coupon", "promo", "voucher", "gift card", "claim code")):
        return "cart:promo_code"
    low = re.sub(r"\b\d+(?:\.\d+)?\b", "<num>", low)
    return low[:120]


def _checkout_reached_ok(after_state: str, after_url: str, error: str) -> bool:
    err_low = (error or "").lower()
    reached = after_state in {STATE_CHECKOUT, "final_order_boundary"} or "checkout" in (after_url or "").lower()
    wrong_target = "wrong_target_for_checkout" in err_low
    return reached and not wrong_target


def _cart_url_for(product_url: str) -> str:
    try:
        p = urlparse(product_url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}/gp/cart/view.html"
    except Exception:
        pass
    return "https://www.amazon.com/gp/cart/view.html"


def _clean_name(name: str) -> str:
    return html.unescape(name or "").strip()


def infer_missed_in_memory(observed_concepts: set[str], validated_concepts: set[str], rules: list[dict]) -> list[dict]:
    out = []
    for rule in rules:
        if not set(rule["requires"]) <= observed_concepts:
            continue
        pivot = rule.get("pivot")
        if pivot is None or pivot not in validated_concepts:
            out.append({
                "key": rule["key"],
                "title": rule["title"],
                "status": rule["status"],
                "depends_on": list(rule["requires"]),
                "source": SOURCE_GRAPH,
            })
    return out


def _asin_in_observation(obs, asin: str) -> bool:
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
    text = obs.text or ""
    if asin:
        idx = text.find(asin)
        if idx >= 0:
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
    m = re.search(r"(\d+)\s+items?\s+in\s+cart", (obs.text or "").lower())
    return int(m.group(1)) if m else None


def _cart_subtotal(obs) -> str | None:
    m = re.search(r"subtotal[^\n]{0,40}?([0-9][0-9.,]*\.\d{2})", (obs.text or "").lower())
    if not m:
        return None
    return m.group(1).replace(",", "")
