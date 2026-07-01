from __future__ import annotations

import base64
import json
import shutil
import tempfile
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
import contextlib
import io
from ..config import DATA_DIR, settings
from ..domain.amazon_auth import AUTH_FILE, BROWSER_ARGS
from ..domain.checkout_contract import (
    RISK_FORBIDDEN_CLICK,
    RISK_OBSERVE_ONLY,
    STATE_CART,
    STATE_CHECKOUT,
)
from .page_observer import PageObservation, PageObserver
from .semantic_normalizer import NormalizedIntent

SCREENSHOTS_DIR = DATA_DIR / "screenshots"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
RUN_LOGS_DIR = DATA_DIR / "run_logs"
for _d in (SCREENSHOTS_DIR, ARTIFACTS_DIR, RUN_LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


import contextlib
import io
import logging


@contextlib.contextmanager
def suppress_browser_use_output():
    """Suppress browser-use console/log noise during agent.run()."""
    logger_names = [
        "browser_use",
        "browser-use",
        "browser_use.agent",
        "browser_use.browser",
        "browser_use.browser.session",
        "browser_use.service",
        "browser_use.telemetry",
        "Agent",
        "BrowserSession",
        "tools",
        "service",
    ]

    old_disable = logging.root.manager.disable
    old_levels = {}
    old_propagate = {}

    try:
        # Nuclear switch: disables all logging <= CRITICAL during agent.run().
        # This is intentional because browser-use installs its own handlers.
        logging.disable(logging.CRITICAL)

        for name in logger_names:
            logger = logging.getLogger(name)
            old_levels[name] = logger.level
            old_propagate[name] = logger.propagate
            logger.setLevel(logging.CRITICAL + 1)
            logger.propagate = False

            for handler in logger.handlers:
                handler.setLevel(logging.CRITICAL + 1)

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            yield

    finally:
        logging.disable(old_disable)

        for name in logger_names:
            logger = logging.getLogger(name)
            if name in old_levels:
                logger.setLevel(old_levels[name])
            if name in old_propagate:
                logger.propagate = old_propagate[name]


@dataclass
class BrowserUseStepArtifact:
    step: int
    url: str
    title: str
    state: str
    action_type: str
    target_label: str
    selector: str
    dom_excerpt: str
    screenshot_path: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass
class BrowserUseResult:
    status: str
    observation: PageObservation
    before: PageObservation | None = None
    artifacts: list[BrowserUseStepArtifact] = field(default_factory=list)
    action_type: str = "observe"
    target_label: str = ""
    selector: str = ""
    evidence: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def validated(self) -> bool:
        return self.status == "validated"


class BrowserUseIntentExecutor:
    """Thin browser-use adapter for the autonomous graph-guided explorer.

    Responsibility split:
      - browser-use freely explores under a hard veto for discovery.
      - graph-directed probes can ask browser-use to execute a narrow intent
        using its own page model
        (DOM, accessibility labels, screenshot/layout, internal element indices).
      - this adapter converts browser-use observations back into PageObservation
        and raw step artifacts for graph ingestion.
    """

    def __init__(self, *, headless: bool = True, debug: bool = False):
        self.headless = headless
        self.debug = debug
        self.observer = PageObserver()
        self._browser_session = None
        self._llm = None
        self._temp_user_data_dir: str | None = None
        self._last_observation: PageObservation | None = None
        self._last_artifacts: list[BrowserUseStepArtifact] = []
        self._current_task = "unknown"
        self._task_counter = 0
        # Narrow directed-probe support, used by restore/probe utilities.
        self._active_intent: NormalizedIntent | None = None
        self._task_execution_actions: list[BrowserUseStepArtifact] = []
        self._task_warnings: list[str] = []
        # Deny-list safety context (set by the explorer). The veto blocks only
        # final payment and off-product navigation; everything else is allowed.
        self._safety_product_asin: str = ""
        self._safety_base_host: str = ""
        self._safety_title_tokens = frozenset()
        self._vetoes: list[str] = []
        # Token-saving no-repeat guard: an action label done once is not run again
        # (persists across bursts within a run). Active only when _block_repeats.
        self._done_labels: set[str] = set()
        self._block_repeats: bool = False

    def set_safety_context(self, product_url: str) -> None:
        """Tell the veto which product/marketplace is in scope so it can block
        navigation to a different product or an external site."""
        from .safety_guard import asin_from_url, host_of
        self._safety_product_asin = asin_from_url(product_url)
        self._safety_base_host = host_of(product_url)

    def set_product_title(self, title: str) -> None:
        """Once the product title is known, the veto can also block cart actions on
        a DIFFERENT product (recommendation/cross-sell tiles)."""
        from .safety_guard import product_tokens
        self._safety_title_tokens = product_tokens(title)

    async def start(self) -> None:
        if self._browser_session is not None:
            return
        if not AUTH_FILE.exists():
            raise RuntimeError(f"Auth file missing: {AUTH_FILE}. Run scripts/login_amazon.py first")
        try:
            from browser_use import BrowserSession
            from browser_use.llm.openai.chat import ChatOpenAI
        except Exception as exc:
            raise RuntimeError(
                "browser-use is required for the agentic crawler. Install requirements.txt. "
                f"Import error: {exc}"
            )
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required because browser-use uses an LLM agent for crawling")

        self._llm = ChatOpenAI(
            model=settings.openai_model or "gpt-4o-mini",
            api_key=settings.openai_api_key,
            temperature=0.0,
        )
        self._temp_user_data_dir = tempfile.mkdtemp(prefix="browser-use-autonomous-", dir="/tmp")
        storage_state_path = _sanitized_storage_state(AUTH_FILE, self._temp_user_data_dir)
        self._browser_session = BrowserSession(
            headless=self.headless,
            user_data_dir=self._temp_user_data_dir,
            storage_state=storage_state_path,
            args=BROWSER_ARGS,
            keep_alive=True,
            minimum_wait_page_load_time=1.0,
            wait_for_network_idle_page_load_time=2.0,
        )
        await self._browser_session.start()

    async def close(self) -> None:
        if self._browser_session is not None:
            try:
                await self._browser_session.close()
            except Exception:
                pass
            self._browser_session = None
        if self._temp_user_data_dir:
            shutil.rmtree(self._temp_user_data_dir, ignore_errors=True)
            self._temp_user_data_dir = None

    async def navigate_and_observe(self, url: str, *, expected_state: str, label: str) -> BrowserUseResult:
        await self.start()
        task = f"""
Navigate to the provided initial URL using the browser action supplied by the caller, then observe the page.
Do not click any purchase, checkout, payment, or destructive button during this observation task.
Expected page/state: {expected_state}
After the page loads, use the final done action immediately with a concise summary of:
- current page/state
- visible actions/buttons/forms
- cart/checkout indicators
- safety boundaries
Do not invent or navigate to any URL from this prompt text.
"""
        return await self._run_agent_task(task, label=label, start_url=url, max_steps=3, expected_state=expected_state)

    async def observe_current(self, *, label: str = "Observe current page", expected_state: str | None = None) -> BrowserUseResult:
        await self.start()
        task = f"""
Observe the current browser page. Do not click anything.
Use the visible page, accessibility labels, DOM, and screenshot/layout.
Expected state if known: {expected_state or 'unknown'}.
Use the final done action immediately with a concise summary of visible actions, forms, cart/checkout indicators, and safety boundaries.
Do not navigate to any URL. Do not invent a URL from this prompt text.
"""
        return await self._run_agent_task(task, label=label, start_url=None, max_steps=2, expected_state=expected_state)

    async def execute_intent(self, intent: NormalizedIntent) -> BrowserUseResult:
        await self.start()
        if intent.risk == RISK_OBSERVE_ONLY or intent.risk == RISK_FORBIDDEN_CLICK or not intent.click_allowed:
            return await self.observe_current(label=f"Observe {intent.human_label}", expected_state=intent.expected_state)
        task = self._intent_task(intent)
        # Three steps is enough for one directed click, one observation/wait, and done.
        # Longer runs let the agent keep planning and wander.
        return await self._run_agent_task(task, label=intent.human_label, start_url=None, max_steps=3, expected_state=intent.expected_state, intent=intent)

    async def explore_autonomously(
        self, *, goal: str, expected_state: str, max_steps: int = 10, start_url: str | None = None,
        block_repeats: bool = True,
    ) -> BrowserUseResult:
        """Let browser-use explore freely (it chooses its own actions), with the
        deny-list veto active. This is the crawl-discovery engine: the agent tries
        whatever controls it finds, and we capture the trace as discovered
        scenarios. Safety is the veto, not a script.

        block_repeats: when True (free crawl), an action label already done is
        vetoed so the agent can't burn tokens re-doing the same thing. Graph
        probes pass False so the graph can deliberately re-test a behaviour."""
        await self.start()
        self._block_repeats = block_repeats
        task = self._exploration_task(goal, expected_state)
        return await self._run_agent_task(
            task, label=f"explore:{expected_state}", start_url=start_url,
            max_steps=max_steps, expected_state=expected_state, intent=None,
            max_actions_per_step=2,
        )

    def _exploration_task(self, goal: str, expected_state: str) -> str:
        forbidden = "Buy Now, Place Order, Pay Now, Confirm Purchase, Complete Purchase, Submit Order"
        expected_words = (expected_state or "").replace("_", " ")
        return f"""
You are an exploratory UI tester for a graph-guided testing system. Expected page/state: {expected_words}.

{goal}

You may freely click, select, and fill the controls you discover. Prefer trying MANY DIFFERENT controls (quantity, save-for-later, remove/delete, coupon/offer, gift options, product variants) one at a time, observing what changes after each — that variety is the whole point.

HARD RULES — never break these:
- NEVER click final purchase or payment: {forbidden}. Stop before any payment step.
- Do NOT navigate to a DIFFERENT product or any external site. Stay on THIS product and its own cart/checkout.
- Only operate on the item under test. Do NOT add other or recommended products to the cart, and do NOT click 'Buy again', 'Customers also bought', or recommendation tiles.
- Do NOT touch account controls: never click Sign out, Switch account, Sign in, or change the logged-in user.
- Do not repeat a control you already tried.

When you have exercised the available controls, call done with a short summary of what you tried and what changed.
"""

    def _intent_task(self, intent: NormalizedIntent) -> str:
        """Build a browser-use task without URL-like internal identifiers.

        browser-use scans task text for URLs. Earlier versions exposed canonical
        keys such as ``action.proceed_to_checkout`` and the agent interpreted
        them as domains like https://action.proceed. This prompt deliberately
        hides internal dotted keys and uses plain-language labels only.
        """
        forbidden = "Buy Now, Place Order, Pay Now, Confirm Purchase, Complete Purchase, Submit Order"
        safe_id = _safe_intent_id(intent.canonical_key)
        safe_aliases = _safe_prompt_list(intent.aliases[:10])
        safe_success = _safe_prompt_list(intent.success_criteria[:8])
        risk_words = intent.risk.replace("_", " ")
        expected_words = intent.expected_state.replace("_", " ")
        base = f"""
You are executing exactly ONE UI-testing intent for a graph-guided DFS explorer.

Important: no URL is provided in this task. Stay on the current browser page. Do not navigate to a URL unless the page itself changes because of the intended click.

Intent ID: {safe_id}
Intent label: {intent.human_label}
Expected current page/state: {expected_words}
Risk class: {risk_words}
Semantic target words: {safe_aliases}
Success evidence to look for: {safe_success}

Use browser-use normally: visible page, accessibility tree/ARIA labels, DOM, screenshot/layout, and internal element indices.
Do NOT rely only on CSS selectors. Choose the actual visible UI control that satisfies the intent.

STRICT EXECUTION CONTRACT:
- You are the executor, not the planner.
- Execute at most ONE UI-changing action for this intent: one click, one select, or one fill.
- After that one action, do not click, select, fill, search, navigate, reload, use logo/search/cart links, or open unrelated pages.
- After the one action, only observe/wait briefly if needed, then call done.
- If the intended target is not confidently visible, do not click anything; return ELEMENT_NOT_FOUND.
- If you are already on the requested destination/state, do not click again; call done and report already_satisfied.
- If confidence is below 0.80, return ELEMENT_NOT_FOUND instead of trying alternatives.
Never click these forbidden purchase/final-payment actions: {forbidden}.
Return final answer as short JSON-like text with: clicked, target, result, evidence.
"""
        if intent.canonical_key == "action.add_to_cart":
            base += """
Special instruction for Add to Cart:
Click the MAIN product-page Add to Cart control for the selected item.
Prefer the visible product buy-box Add to Cart button/input. Do NOT click Buy Now. Do NOT click a nav/header helper if the real product Add to Cart exists.
After clicking, stop after cart confirmation / cart subtotal / cart item evidence appears.
"""
        elif intent.canonical_key == "action.go_to_cart":
            base += """
Special instruction for Go to Cart:
If the shopping cart page/surface is already visible, do not click; return already_satisfied.
Otherwise open the shopping cart using the cart navigation/icon or cart link. Stop once the shopping cart page/surface is visible.
Negative targets: search box, Amazon logo, Add to Cart, Proceed to Checkout, Buy Now.
"""
        elif intent.canonical_key == "action.change_quantity":
            base += """
Special instruction for Change Quantity:
Change the cart item quantity by one safe step using ONE visible quantity stepper/dropdown/control.
After one click/select, do not click another quantity control. Wait/observe once, then done.
Success means quantity changed or subtotal changed. If the page does not visibly update, report NOT_VALIDATED, not success.
Negative targets: Delete, Save for later, Proceed to Checkout, Add to Cart, search, logo.
"""
        elif intent.canonical_key == "action.proceed_to_checkout":
            base += """
Special instruction for Proceed to Checkout:
Click the exact Proceed to Checkout / Proceed to retail checkout button only.
Positive target examples: Proceed to Checkout, Proceed to checkout, Proceed to retail checkout.
Negative targets: Add to Cart, cart icon/link, Amazon logo, search submit, bookstore links, Buy Now, Place Order, Pay Now.
After the one checkout click, only observe whether the page reaches secure checkout, sign-in boundary, address/payment boundary, or another blocking page; then done.
Do NOT click again if redirected to sign-in or another page.
"""
        return base

    async def _run_agent_task(
        self,
        task: str,
        *,
        label: str,
        start_url: str | None,
        max_steps: int,
        expected_state: str | None,
        intent: NormalizedIntent | None = None,
        max_actions_per_step: int = 1,
    ) -> BrowserUseResult:
        from browser_use import Agent
        self._task_counter += 1
        self._current_task = label
        self._last_artifacts = []
        self._active_intent = intent
        self._task_execution_actions = []
        self._task_warnings = []
        self._vetoes = []
        before = self._last_observation
        initial_actions = [{"navigate": {"url": start_url, "new_tab": False}}] if start_url else []
        agent = Agent(
            task=task,
            llm=self._llm,
            browser_session=self._browser_session,
            initial_actions=initial_actions,
            register_new_step_callback=self._on_step,
            max_actions_per_step=max_actions_per_step,
        )
        error = ""
        try:
            with suppress_browser_use_output():
                await agent.run(max_steps=max_steps)
        except Exception as exc:
            error = str(exc)[:300]
        after = self._last_observation
        if after is None:
            after = PageObservation(
                url="", title="", state="unknown", state_scores={}, state_evidence={}, text="",
                elements=[], detected_concepts=set(), forbidden_action_detected=False, forbidden_boundary_detected=False,
            )
        # Phase 3: report the primary UI-changing action, not the final `done` action.
        # browser-use usually ends with done(), so using the last artifact made
        # already-satisfied and attempted-click cases hard to classify.
        ui_actions = [a for a in self._last_artifacts if a.action_type in {"click", "fill", "select"}]
        primary = self._task_execution_actions[0] if self._task_execution_actions else (ui_actions[0] if ui_actions else (self._last_artifacts[-1] if self._last_artifacts else None))
        action_type = primary.action_type if primary else "observe"
        target = primary.target_label if primary else label
        selector = primary.selector if primary else ""
        if _looks_like_internal_action_url(after.url):
            error = (error + " | " if error else "") + "browser-use navigated to internal action-like URL; prompt/plumbing bug guarded"
        if self._vetoes:
            error = (error + " | " if error else "") + "safety_veto:" + ",".join(sorted(set(self._vetoes))[:4])
        if self._task_warnings:
            error = (error + " | " if error else "") + "; ".join(self._task_warnings[:4])
        artifact_json = _persist_artifact_bundle(self._task_counter, label, self._last_artifacts)
        if intent is None:
            # Autonomous exploration burst: no single-intent verdict; just report
            # what was tried and whether the veto fired.
            evidence = [f"actions={len(ui_actions)}", f"final_state={after.state}"]
            evidence += [f"veto={v}" for v in sorted(set(self._vetoes))[:3]]
            if error:
                evidence.append(f"error={error[:160]}")
            if artifact_json:
                evidence.append(f"artifact_json={artifact_json}")
            status = "vetoed" if self._vetoes else ("explored" if ui_actions else "observed")
        else:
            evidence = self._evidence_for_result(intent, before, after, target, error)
            if artifact_json:
                evidence.append(f"artifact_json={artifact_json}")
            status = self._status_for_result(intent, before, after, action_type, evidence, error)
        return BrowserUseResult(
            status=status,
            before=before,
            observation=after,
            artifacts=list(self._last_artifacts),
            action_type=action_type,
            target_label=target,
            selector=selector,
            evidence=evidence,
            error=error,
        )

    async def _on_step(self, browser_state: Any, agent_output: Any, step_num: int) -> None:
        obs = self.observer.from_browser_use_state(browser_state)
        self._last_observation = obs
        action = None
        try:
            if getattr(agent_output, "action", None):
                action = agent_output.action[0]
        except Exception:
            action = None
        action_type = _action_type(action) if action is not None else "observe"
        # Resolve the PRECISE element label (its text/aria) for the thing being
        # acted on — not browser-use's verbose page summary. This keeps the report
        # legible AND makes the veto precise: a done() summary that merely mentions
        # "Buy now" must not trigger a false payment veto.
        el_label = _element_label_for_action(action, browser_state) if action is not None else ""
        target = el_label or (_action_target_label(action) if action is not None else self._current_task)
        selector = _resolve_selector(action, browser_state) if action is not None else ""

        # DENY-LIST VETO — runs before the action executes. Only for actions that
        # actually do something (click/select/navigate), using the precise label.
        if action_type in {"click", "select", "fill", "navigate", "go_back", "go_to_url"}:
            from .safety_guard import ForbiddenActionVeto, veto_reason
            reason = veto_reason(
                target_label=target if action_type in {"click", "select", "fill"} else "",
                action_url=_action_url(action),
                action_type=action_type,
                product_asin=self._safety_product_asin,
                base_host=self._safety_base_host,
                product_title_tokens=self._safety_title_tokens,
                page_state=getattr(obs, "state", "") or "",
            )
            # No-repeat guard: an identifiable action done once must not run again
            # (saves tokens). Tracked across bursts; only enforced when active.
            if not reason and action_type in {"click", "select", "fill"}:
                rk = _repeat_key(target)
                if rk and rk in self._done_labels:
                    if self._block_repeats:
                        reason = "repeat:already_done"
                elif rk:
                    self._done_labels.add(rk)
            if reason:
                self._vetoes.append(reason)
                if self.debug:
                    print(f"[safety][veto] blocked action: {reason}")
                raise ForbiddenActionVeto(reason)
        screenshot_path = _persist_screenshot(browser_state, self._task_counter, step_num)
        dom_excerpt = obs.text[:3000]
        artifact = BrowserUseStepArtifact(
            step=step_num,
            url=obs.url,
            title=obs.title,
            state=obs.state,
            action_type=action_type,
            target_label=target,
            selector=selector,
            dom_excerpt=dom_excerpt,
            screenshot_path=screenshot_path,
            evidence=sorted(obs.detected_concepts)[:10],
        )
        self._last_artifacts.append(artifact)
        if self._active_intent is None and action_type in {"click", "fill", "select"}:
            self._task_execution_actions.append(artifact)
        if self._active_intent is not None:
            self._track_phase2_contract(artifact)
        if self.debug:
            print(f"[browser-use][step {step_num}] {action_type} target={target[:80]} state={obs.state} url={obs.url[:100]}")


    def _track_phase2_contract(self, artifact: BrowserUseStepArtifact) -> None:
        """Detect when browser-use stops acting like a one-intent executor.

        We cannot safely interrupt browser-use mid-run across versions, but we can
        classify the run as wandered/not validated if it performs extra clicks,
        navigations, search-box/logo actions, writes files, or otherwise keeps
        planning after the intended click.
        """
        action_type = artifact.action_type
        target = (artifact.target_label or "").lower()
        selector = (artifact.selector or "").lower()

        # Observation-ish actions are allowed after the single UI action.
        if action_type in {"observe", "done", "wait", "search_page", "find_text"}:
            return

        if action_type in {"write_file", "evaluate", "navigate", "go_back", "reload"}:
            self._task_warnings.append(f"agent_wandered:{action_type}")
            return

        if action_type in {"click", "fill", "select"}:
            self._task_execution_actions.append(artifact)
            if len(self._task_execution_actions) > 1:
                self._task_warnings.append("agent_wandered:multiple_ui_actions")

            # Common wrong-target symptoms seen in the live run. These should
            # never be counted as a validated intent execution.
            wrong_target_tokens = ["logo", "search", "nav-search", "reload"]
            if any(tok in target or tok in selector for tok in wrong_target_tokens):
                self._task_warnings.append(f"agent_wandered:wrong_target:{target[:40] or selector[:40]}")

            if self._active_intent and self._active_intent.canonical_key == "action.proceed_to_checkout":
                # Proceed-to-checkout must not click Add to Cart, cart icon, logo, or search.
                negative = ["add to cart", "cart", "logo", "search", "nav-cart", "add-to-cart"]
                if any(tok in target or tok in selector for tok in negative):
                    self._task_warnings.append(f"wrong_target_for_checkout:{target[:60] or selector[:60]}")

    def _evidence_for_result(self, intent: NormalizedIntent | None, before: PageObservation | None, after: PageObservation, target: str, error: str) -> list[str]:
        ev: list[str] = []
        if target:
            ev.append(f"browser-use target={target[:120]}")
        if after.state:
            ev.append(f"after_state={after.state}")
        ev.extend(sorted(after.detected_concepts)[:8])
        low = (after.text or "").lower()
        if "added to cart" in low or "added to your cart" in low:
            ev.append("added-to-cart confirmation text")
        if "subtotal" in low:
            ev.append("subtotal visible")
        if "secure checkout" in low:
            ev.append("secure checkout visible")
        if error:
            ev.append(f"error={error[:160]}")
        return ev

    def _status_for_result(self, intent: NormalizedIntent | None, before: PageObservation | None, after: PageObservation, action_type: str, evidence: list[str], error: str) -> str:
        """Classify the browser-use run using explorer-side verification.

        browser-use is allowed to operate the page, but this adapter is the
        authority for whether the business intent was actually satisfied.
        """
        combined = " ".join(evidence).lower() + " " + (after.text or "")[:2500].lower()
        had_ui_action = action_type in {"click", "fill", "select"}
        if "internal action-like url" in (error or ""):
            return "executor_prompt_bug"
        if "agent_wandered" in (error or "") or "wrong_target_for_checkout" in (error or ""):
            return "agent_wandered"
        if error and after.state == "unknown":
            return "agent_error"
        if intent is None:
            return "observed"

        failure = _result_text_indicates_failure(combined)
        already_satisfied = _result_text_indicates_already_satisfied(combined)

        if intent.canonical_key == "action.add_to_cart":
            if failure:
                return "clicked_observed" if had_ui_action else "not_grounded"
            if had_ui_action and (after.state in {"cart_confirmation", "shopping_cart"} or "added-to-cart confirmation text" in evidence or "subtotal visible" in evidence):
                return "validated"
            return "clicked_observed" if had_ui_action else "not_grounded"

        if intent.canonical_key == "action.go_to_cart":
            # Being on cart already is a useful fact but not a direct click.
            if after.state == STATE_CART and (already_satisfied or not had_ui_action):
                return "already_satisfied"
            if after.state == STATE_CART and had_ui_action:
                return "validated"
            if failure:
                return "not_grounded"
            return "clicked_observed" if had_ui_action else "not_grounded"

        if intent.canonical_key == "action.change_quantity":
            success_words = ["successfully increased", "successfully changed", "quantity was successfully", "subtotal changed", "changing the subtotal", "updated from", "changed from"]
            if after.state == STATE_CART and any(w in combined for w in success_words):
                return "validated"
            if failure:
                return "clicked_observed" if had_ui_action else "not_grounded"
            return "clicked_observed" if had_ui_action else "observed_only"

        if intent.canonical_key == "action.proceed_to_checkout":
            # For this prototype, checkout/sign-in/payment/address pages are
            # terminal checkout boundaries. Reaching that boundary is a
            # successful crawl outcome even if Amazon asks for auth next.
            if after.state in {STATE_CHECKOUT, "final_order_boundary"}:
                return "validated" if had_ui_action else "already_satisfied"
            if "sign-in" in combined or "signin" in combined or "/ap/signin" in (after.url or ""):
                return "blocked_signin" 
            if failure:
                return "not_grounded"
            return "clicked_observed" if had_ui_action else "not_grounded"

        if failure:
            return "clicked_observed" if had_ui_action else "not_grounded"
        return "clicked_observed" if had_ui_action else "observed_only"




def _sanitized_storage_state(auth_file: Path, dest_dir: str) -> str:
    """Return a path to a storage-state file browser-use can actually load.

    Playwright writes partitioned cookies with a ``partitionKey`` string and a
    ``_crHasCrossSiteAncestor`` flag. browser-use's CDP StorageStateWatchdog
    cannot deserialize ``partitionKey`` (it expects a CBOR map) and aborts the
    ENTIRE storage-state load, leaving the crawl browser unauthenticated — which
    silently breaks any signed-in flow such as Proceed to Checkout. We strip
    those fields into a sanitized copy and hand that to BrowserSession instead.
    """
    try:
        data = json.loads(auth_file.read_text(encoding="utf-8"))
    except Exception:
        return str(auth_file.resolve())
    cookies = data.get("cookies")
    if isinstance(cookies, list):
        for c in cookies:
            if isinstance(c, dict):
                c.pop("partitionKey", None)
                c.pop("_crHasCrossSiteAncestor", None)
    try:
        out = Path(dest_dir) / "storage_state.sanitized.json"
        out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(out)
    except Exception:
        return str(auth_file.resolve())


def _result_text_indicates_failure(text: str) -> bool:
    low = (text or "").lower()
    failure_phrases = [
        "element_not_found",
        "not found",
        "not fulfilled",
        "not completed",
        "no evidence",
        "did not find",
        "did not lead",
        "no changes",
        "no change",
        "unsuccessful",
        "failure",
        "failed",
    ]
    return any(p in low for p in failure_phrases)


def _result_text_indicates_already_satisfied(text: str) -> bool:
    low = (text or "").lower()
    phrases = [
        "already_satisfied",
        "already satisfied",
        "already visible",
        "already on",
        "no action was taken",
        "no further actions are required",
        "no further actions were necessary",
        "target state is already",
    ]
    return any(p in low for p in phrases)


def _safe_intent_id(canonical_key: str) -> str:
    return (canonical_key or "intent").replace("action.", "").replace("domain.", "").replace("capability.", "").replace("scenario.", "").replace(".", "_").upper()


def _safe_prompt_list(values: list[str] | tuple[str, ...]) -> str:
    cleaned = []
    for value in values or []:
        v = str(value).strip()
        if not v:
            continue
        # Prevent browser-use URL auto-detection from dotted internal tokens.
        v = v.replace(".", " ").replace("_", " ")
        v = v.replace("http://", "").replace("https://", "")
        cleaned.append(v)
    return ", ".join(cleaned) if cleaned else "none"


def _looks_like_internal_action_url(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        return host.startswith("action.") or host.startswith("domain.") or host.startswith("capability.") or host in {"action", "domain", "capability"}
    except Exception:
        low = url.lower()
        return "//action." in low or "//domain." in low or "//capability." in low


def _persist_artifact_bundle(task_num: int, label: str, artifacts: list[BrowserUseStepArtifact]) -> str:
    if not artifacts:
        return ""
    safe_label = "".join(ch.lower() if ch.isalnum() else "_" for ch in label)[:48].strip("_") or "task"
    out = ARTIFACTS_DIR / f"browser_use_task{task_num:03d}_{safe_label}.json"
    payload = {
        "task_num": task_num,
        "label": label,
        "artifacts": [
            {
                "step": a.step,
                "url": a.url,
                "title": a.title,
                "state": a.state,
                "action_type": a.action_type,
                "target_label": a.target_label,
                "selector": a.selector,
                "dom_excerpt": a.dom_excerpt[:3000],
                "screenshot_path": a.screenshot_path,
                "evidence": a.evidence,
            }
            for a in artifacts
        ],
    }
    try:
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(out)
    except Exception:
        return ""


def _persist_screenshot(browser_state: Any, task_num: int, step_num: int) -> str:
    shot = getattr(browser_state, "screenshot", None)
    if not shot:
        fn = getattr(browser_state, "get_screenshot", None)
        if callable(fn):
            try:
                shot = fn()
            except Exception:
                shot = None
    if not shot:
        return ""
    out = SCREENSHOTS_DIR / f"browser_use_task{task_num:03d}_step{step_num:03d}.png"
    try:
        out.write_bytes(base64.b64decode(shot))
        return str(out)
    except Exception:
        return ""


def _action_type(action: Any) -> str:
    if action is None:
        return "observe"
    name = type(action).__name__.lower()
    dumped = action.model_dump() if hasattr(action, "model_dump") else {}
    keys = " ".join(dumped.keys()).lower() if isinstance(dumped, dict) else ""
    joined = f"{name} {keys}"
    if "done" in joined:
        return "done"
    if "click" in joined:
        return "click"
    if "input" in joined or "type" in joined or "text" in keys or "value" in keys:
        return "fill"
    if "navigate" in joined or "url" in keys:
        return "navigate"
    if "go_back" in joined or "back" in joined:
        return "go_back"
    if "wait" in joined:
        return "wait"
    if "search_page" in joined or "find_text" in joined or "search" in joined or "pattern" in keys:
        return "search_page"
    if "write_file" in joined or "read_file" in joined or "replace_file" in joined:
        return "write_file"
    if "evaluate" in joined:
        return "evaluate"
    if "select" in joined or "dropdown" in joined:
        return "select"
    if "scroll" in joined:
        return "scroll"
    return "observe"


def _repeat_key(label: str) -> str:
    """A stable key for the no-repeat guard, only for identifiable actions. Empty
    for too-short or index-only labels (we can't tell those apart, so don't block).
    Coupon/promo fills are intentionally grouped so different strings do not make
    the cart crawl chase unlimited promo attempts."""
    s = (label or "").strip().lower()
    if len(s) < 3 or s.startswith("index="):
        return ""
    if any(tok in s for tok in ("coupon", "promo", "promotion", "voucher")):
        return "cart:promo_code"
    if s.startswith("text=") and any(tok in s for tok in ("coupon", "promo", "voucher")):
        return "cart:promo_code"
    return s[:80]


def _action_url(action: Any) -> str:
    """Best-effort extract a destination URL from a navigate-style action."""
    if action is None:
        return ""
    try:
        dumped = action.model_dump(exclude_none=True) if hasattr(action, "model_dump") else {}
    except Exception:
        return ""
    if not isinstance(dumped, dict):
        return ""
    for v in dumped.values():
        if isinstance(v, dict) and isinstance(v.get("url"), str):
            return v["url"]
        if isinstance(v, str) and v.startswith("http"):
            return v
    return ""


def _action_target_label(action: Any) -> str:
    if action is None:
        return ""
    for attr in ("description", "element_description", "text", "label", "value", "url"):
        val = getattr(action, attr, None)
        if isinstance(val, str) and val:
            return val[:160]
    if hasattr(action, "model_dump"):
        flat = _flatten(action.model_dump())
        for key in ("text", "value", "url", "selector", "index", "xpath"):
            val = flat.get(key)
            if val not in (None, ""):
                return f"{key}={val}"[:160]
    return type(action).__name__


def _element_label_for_action(action: Any, browser_state: Any) -> str:
    """Resolve the human label of the element an action targets, using
    browser-use's OWN DOM selector map (its indices), so the index matches what
    the action references. Returns "" for fills/navigations (no element index)."""
    if action is None or not hasattr(action, "model_dump"):
        return ""
    try:
        flat = _flatten(action.model_dump())
    except Exception:
        return ""
    idx = flat.get("index")
    if idx in (None, ""):
        return ""
    return _label_from_dom(browser_state, idx)


def _label_from_dom(browser_state: Any, index: Any) -> str:
    """Human label of the element at browser-use's element index, from its DOM."""
    try:
        idx = int(index)
    except Exception:
        return ""
    try:
        dom_state = getattr(browser_state, "dom_state", None)
        selector_map = getattr(dom_state, "selector_map", None) or {}
        node = selector_map.get(idx) if hasattr(selector_map, "get") else None
        if not node:
            return ""
        attrs = getattr(node, "attributes", None) or {}
        txt = ""
        for meth in ("get_meaningful_text_for_llm", "get_all_children_text", "get_all_text_till_next_clickable_element"):
            fn = getattr(node, meth, None)
            if callable(fn):
                try:
                    txt = fn() or ""
                except Exception:
                    txt = ""
                if txt:
                    break
        if not txt:
            txt = getattr(node, "text", "") or ""
        label = (attrs.get("aria-label") or txt or attrs.get("value")
                 or attrs.get("placeholder") or attrs.get("name") or attrs.get("id") or "")
        return " ".join(str(label).split())[:60]
    except Exception:
        return ""


def _resolve_selector(action: Any, browser_state: Any) -> str:
    if action is None:
        return ""
    if hasattr(action, "model_dump"):
        flat = _flatten(action.model_dump())
        for key in ("selector", "css_selector", "xpath"):
            val = flat.get(key)
            if val:
                return str(val)
        idx = flat.get("index")
        if idx not in (None, ""):
            sel = _selector_from_dom(browser_state, idx)
            return sel or f"index={idx}"
    return ""


def _selector_from_dom(browser_state: Any, index: Any) -> str:
    try:
        idx = int(index)
    except Exception:
        return ""
    try:
        dom_state = getattr(browser_state, "dom_state", None)
        selector_map = getattr(dom_state, "selector_map", None) or {}
        node = selector_map.get(idx) if hasattr(selector_map, "get") else None
        if not node:
            return ""
        attrs = getattr(node, "attributes", None) or {}
        if attrs.get("id"):
            return f"#{attrs['id']}"
        if attrs.get("name"):
            return f"[name='{attrs['name']}']"
        if attrs.get("aria-label"):
            return f"[aria-label='{attrs['aria-label']}']"
        tag = getattr(node, "tag_name", None) or getattr(node, "node_name", None)
        return str(tag).lower() if tag else ""
    except Exception:
        return ""


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out[str(k)] = v
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.update(_flatten(v, f"{prefix}.{i}"))
    elif prefix:
        out[prefix] = value
        out[prefix.split(".")[-1]] = value
    return out
