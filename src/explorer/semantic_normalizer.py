from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..domain.checkout_contract import (
    INTENTS,
    IntentSpec,
    RISK_FORBIDDEN_CLICK,
    RISK_OBSERVE_ONLY,
)
from .page_observer import GENERIC_TAG_SELECTORS, PageObservation, UIElement


@dataclass
class NormalizedIntent:
    canonical_key: str
    human_label: str
    expected_state: str
    source: str
    risk: str
    priority: float
    ui_element: UIElement | None = None
    selector_candidates: list[str] = field(default_factory=list)
    semantic_target: str = ""
    aliases: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    confidence: float = 0.0
    semantic_score: float = 0.0
    selector_quality_score: float = 0.0
    reason: str = ""
    click_allowed: bool = False
    requires_replay: bool = False
    executable: bool = False

    @property
    def target_signature(self) -> str:
        if self.ui_element:
            e = self.ui_element
            return e.selector or e.id or e.name or e.aria_label or e.value or e.text[:40] or "observed"
        if self.selector_candidates:
            return self.selector_candidates[0]
        return "concept"

    @property
    def identity(self) -> str:
        # Source is deliberately excluded so crawler/LLM/graph duplicate ideas collapse.
        return f"{self.expected_state}:{self.canonical_key}:{self.target_signature}"


class SemanticNormalizer:
    """Maps raw UI elements and graph/LLM suggestions into canonical intents.

    It separates semantic confidence from selector quality. A click can only be
    executable when both semantic and selector/interactability gates pass.
    """

    def normalize_observation(self, obs: PageObservation, *, source: str = "crawler_observed") -> list[NormalizedIntent]:
        intents: list[NormalizedIntent] = []
        for el in obs.elements:
            for spec in INTENTS.values():
                # Hard state gate before grounding: wrong-state candidates can be
                # useful in debug logs, but they should not enter the executable
                # main observed-affordance accounting.
                if obs.state not in spec.expected_states:
                    continue
                semantic, selector_quality, reason = self.score_element(spec, el, obs.state)
                confidence = round(min(0.99, semantic * 0.72 + selector_quality * 0.28), 2)
                threshold = 0.48 if spec.intent_type == "observation" else 0.62
                if confidence >= threshold:
                    ni = self._from_spec(spec, source, el, confidence, semantic, selector_quality, reason)
                    # If an intent can exist in multiple states, the current
                    # verified state is the expected execution state for this
                    # observed affordance. This prevents misleading entries like
                    # Go to Cart expected_state=cart_confirmation while seen on
                    # shopping_cart.
                    ni.expected_state = obs.state
                    intents.append(ni)
        # Text/state concepts can be graph observations, not clickable affordances.
        for key in obs.detected_concepts:
            spec = INTENTS.get(key)
            if spec and spec.intent_type == "observation" and obs.state in spec.expected_states:
                ni = self._from_spec(spec, source, None, 0.70, 0.70, 0.0, "detected from page text / state")
                ni.expected_state = obs.state
                intents.append(ni)
        return self.dedupe(intents)

    def normalize_suggestion(self, suggestion: dict, *, source: str = "llm_neighbor") -> NormalizedIntent | None:
        text = " ".join(str(suggestion.get(k, "")) for k in ["canonical_key", "title", "label", "description", "expected_evidence"])
        aliases = suggestion.get("aliases") or []
        text += " " + " ".join(map(str, aliases))
        best_spec = None
        best = 0.0
        for spec in INTENTS.values():
            s = self.score_text(spec, text)
            if s > best:
                best = s
                best_spec = spec
        if not best_spec or best < 0.35:
            return None
        ni = self._from_spec(best_spec, source, None, min(0.85, best), best, 0.0, f"semantic suggestion match score={best:.2f}")
        # SAFETY: the canonical risk from the IntentSpec is authoritative and must
        # never be downgraded by an LLM/graph suggestion. Allowing the suggestion's
        # `risk` to win let the model relabel e.g. Proceed to Checkout as
        # "mutating_click" or a destructive action as "safe_click". We deliberately
        # ignore suggestion-provided risk and keep best_spec.risk.
        if suggestion.get("priority") is not None:
            ni.priority = float(suggestion["priority"])
        return ni

    def score_element(self, spec: IntentSpec, el: UIElement, current_state: str) -> tuple[float, float, str]:
        h = el.haystack
        # Hard disallow.
        if "nav-logo-sprites" in h and spec.canonical_key not in {"action.home", "action.logo"}:
            return 0.0, 0.0, "nav logo cannot ground this intent"
        if "nav-cart" in h and spec.canonical_key not in {"action.go_to_cart"}:
            return 0.0, 0.0, "nav cart can only ground go_to_cart"
        if spec.canonical_key == "action.add_to_cart" and "nav-cart" in h:
            return 0.0, 0.0, "go-to-cart is not add-to-cart"
        if spec.canonical_key == "action.add_to_cart" and self._is_bad_add_to_cart_candidate(el):
            return 0.20, 0.0, "add-to-cart candidate penalized: nav/header/assistant/offscreen/non-interactable"
        if spec.risk == RISK_FORBIDDEN_CLICK and not any(a in h for a in spec.aliases):
            return 0.0, 0.0, "forbidden boundary not present"

        semantic = 0.0
        reasons: list[str] = []
        if el.selector and any(self._selector_match(el.selector, hint) for hint in spec.selector_hints):
            semantic += 0.45
            reasons.append("selector hint")
        if any(alias.lower() in h for alias in spec.aliases):
            semantic += 0.42
            reasons.append("alias/text")
        if el.name and any(alias.lower().replace(" ", "") in el.name.lower().replace("_", "") for alias in spec.aliases):
            semantic += 0.20
            reasons.append("name attr")
        if el.id and any(alias.lower().replace(" ", "-") in el.id.lower() for alias in spec.aliases):
            semantic += 0.20
            reasons.append("id attr")
        if el.aria_label and any(alias.lower() in el.aria_label.lower() for alias in spec.aliases):
            semantic += 0.25
            reasons.append("aria label")
        if semantic == 0 and el.text:
            fuzzy = max((SequenceMatcher(None, el.text.lower(), a.lower()).ratio() for a in spec.aliases), default=0.0)
            if fuzzy >= 0.72:
                semantic += 0.24
                reasons.append(f"fuzzy text {fuzzy:.2f}")
        if current_state in spec.expected_states:
            semantic += 0.12
            reasons.append("state")
        else:
            semantic -= 0.35
            reasons.append(f"wrong-state:{current_state}")
        if not el.visible:
            semantic -= 0.25
            reasons.append("hidden")
        if spec.intent_type == "action" and not el.clickable:
            semantic -= 0.15
            reasons.append("not-clickable")

        selector_quality = self.selector_quality_for(el, spec)
        if spec.intent_type == "action" and selector_quality == 0:
            reasons.append("not-executable-selector")
        if spec.intent_type == "observation" and el.visible:
            selector_quality = max(selector_quality, 0.25)
        return max(0.0, min(0.99, round(semantic, 2))), selector_quality, ", ".join(reasons)

    def selector_quality_for(self, el: UIElement, spec: IntentSpec) -> float:
        if not el.selector:
            return 0.0
        sel = el.selector.strip()
        low = sel.lower()
        if low in GENERIC_TAG_SELECTORS:
            return 0.0
        if not el.visible:
            return 0.0
        if spec.intent_type == "action" and not el.can_execute:
            return 0.0

        # Add-to-cart requires stricter ranking because Amazon exposes multiple
        # semantically similar but non-actionable/nav-assistant elements. This is
        # selector-quality logic, not a scripted scenario: exact contract hints and
        # interactable product form controls beat nav/header affordances.
        if spec.canonical_key == "action.add_to_cart":
            if self._is_bad_add_to_cart_candidate(el):
                return 0.0
            if low in {"#add-to-cart-button", "input#add-to-cart-button"}:
                return 1.0
            if "submit.add-to-cart" in low or "add-to-cart-button" in low:
                return 0.98
            if any(self._selector_match(sel, hint) for hint in spec.selector_hints):
                return 0.95

        if any(self._selector_match(sel, hint) for hint in spec.selector_hints):
            return 0.90
        if el.selector_quality == "stable":
            return 0.90
        if el.selector_quality == "anchored":
            return 0.78
        if el.selector_quality == "positional":
            return 0.35
        return 0.0

    def score_text(self, spec: IntentSpec, text: str) -> float:
        t = (text or "").lower()
        score = 0.0
        if spec.canonical_key.lower() in t:
            score += 0.60
        for alias in spec.aliases:
            if alias.lower() in t:
                score += 0.35
                break
        fuzzy = max((SequenceMatcher(None, t[:120], a.lower()).ratio() for a in spec.aliases), default=0.0)
        if fuzzy > 0.45:
            score += 0.15
        return min(score, 0.99)

    def _from_spec(self, spec: IntentSpec, source: str, el: UIElement | None, confidence: float, semantic_score: float | str = 0.0, selector_quality_score: float = 0.0, reason: str = "") -> NormalizedIntent:
        # Backward-compatible signature for older tests: _from_spec(spec, source, el, confidence, reason)
        if isinstance(semantic_score, str) and not reason:
            reason = semantic_score
            semantic_score = confidence
            selector_quality_score = 0.0
        selectors: list[str] = []
        # For Add to Cart, try the strongest contract selectors first even if a
        # weaker semantic candidate was also observed. This lets execution retry
        # the real product button before weak nav/helper affordances.
        if spec.canonical_key == "action.add_to_cart":
            preferred = ["#add-to-cart-button", "[name='submit.add-to-cart']", "input#add-to-cart-button", "input[name='submit.add-to-cart']"]
            for s in preferred:
                if s not in selectors:
                    selectors.append(s)
        if el and el.selector and selector_quality_score > 0:
            if el.selector not in selectors:
                selectors.append(el.selector)
        for s in spec.selector_hints:
            if s not in selectors:
                selectors.append(s)
        executable = bool(el and el.can_execute and selector_quality_score >= 0.70 and semantic_score >= 0.60 and spec.click_allowed_by_default)
        # Suggestions without current UI are never directly executable until re-grounded.
        if el is None:
            executable = False
        return NormalizedIntent(
            canonical_key=spec.canonical_key,
            human_label=spec.human_label,
            expected_state=spec.expected_states[0] if spec.expected_states else "unknown",
            source=source,
            risk=spec.risk,
            priority=spec.priority + (confidence / 10.0),
            ui_element=el,
            selector_candidates=selectors,
            semantic_target=spec.human_label,
            aliases=list(spec.aliases),
            success_criteria=list(spec.success_criteria),
            confidence=confidence,
            semantic_score=round(semantic_score, 2),
            selector_quality_score=round(selector_quality_score, 2),
            reason=reason,
            click_allowed=spec.click_allowed_by_default,
            executable=executable,
        )

    def dedupe(self, intents: list[NormalizedIntent]) -> list[NormalizedIntent]:
        by_key: dict[str, NormalizedIntent] = {}
        for i in intents:
            # Keep distinct observed selectors for same canonical action if they are actually different stable targets.
            key = i.identity if i.ui_element else f"{i.expected_state}:{i.canonical_key}:concept"
            if key not in by_key or i.confidence > by_key[key].confidence:
                by_key[key] = i
        return list(by_key.values())

    def _is_bad_add_to_cart_candidate(self, el: UIElement) -> bool:
        h = el.haystack
        sel = (el.selector or "").lower()
        # Non-interactable nav assistant / header elements should never win over
        # the real product add-to-cart button.
        if "nav-assist" in h or "nav-assist" in sel:
            return True
        if getattr(el, "in_nav_or_header", False) and "add-to-cart-button" not in sel:
            return True
        if getattr(el, "tabindex", None) == "-1":
            return True
        if not el.visible or not el.enabled or not el.interactable:
            return True
        return False

    def _selector_match(self, selector: str, hint: str) -> bool:
        s = selector.lower()
        h = hint.lower()
        return h == s or h in s or s in h
