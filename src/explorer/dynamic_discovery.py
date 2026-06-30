"""Dynamic, page-driven action discovery.

The fixed checkout contract (``INTENTS``) gives a reliable spine — Add to Cart,
Go to Cart, Change Quantity, Proceed to Checkout — but it cannot generalize: a
shirt has size/colour swatches, a laptop has configuration options, a book has
formats, a cart line has save-for-later and gift options. None of those live in
a hand-written catalogue, and they differ per product.

So instead of asking "which of my known actions are on this page?", this module
asks the opposite: "what actionable, checkout-relevant controls does THIS page
actually expose?" — and turns each one into an executable intent.

The discovery is dynamic, but the *risk* of each discovered action is classified
deterministically and safety-first: a control that looks like final payment is
forced to FORBIDDEN no matter what, destructive controls stay gated, and only the
genuinely safe/mutating ones become clickable. The LLM (or page) decides what
exists; deterministic code decides what is allowed to run. Every discovered intent
still flows through the same safety gate, executor and validator as the catalogue
ones — this layer only widens *discovery*, never the safety envelope.
"""
from __future__ import annotations

import html
import re

from ..domain.checkout_contract import (
    RISK_DESTRUCTIVE_CLICK,
    RISK_FORBIDDEN_CLICK,
    RISK_MUTATING_CLICK,
    RISK_OBSERVE_ONLY,
    RISK_SAFE_CLICK,
    SOURCE_CRAWLER,
    is_forbidden_text,
)
from .page_observer import PageObservation, UIElement
from .semantic_normalizer import NormalizedIntent

# Controls the catalogue already owns with tuned selectors / special prompts.
# Dynamic discovery is purely additive: it must not fight the reliable spine, and
# it must not re-propose forbidden purchase actions (the page-level boundary
# detector already records those).
_CATALOGUE_OWNED = (
    "add to cart", "add to basket", "buy now", "buy it now",
    "proceed to checkout", "proceed to buy", "proceed to retail checkout",
    "place order", "place your order", "pay now", "go to cart", "view cart",
    "subtotal", "sign in", "sign-in",
)

# Long-tail actions the catalogue does NOT cover. Keyword → risk class.
_DESTRUCTIVE_WORDS = ("delete", "remove", "clear cart", "empty cart")
_MUTATING_WORDS = (
    # product configuration / variants
    "size", "color", "colour", "style", "variant", "option", "choose", "select",
    "pattern", "edition", "format", "capacity", "storage", "model", "configuration",
    "configure", "plan", "length", "fit", "material", "flavour", "flavor",
    # quantity
    "quantity", "qty", "increase", "decrease",
    # cart-line actions
    "save for later", "move to cart", "move to list", "add to list",
    "gift option", "gift wrap", "gift receipt", "add gift",
    # promotions / offers — now exercised, not just observed
    "offer", "coupon", "promo", "voucher", "apply", "bank offer", "see all offers",
)
_SAFE_NAV_WORDS = ("continue to checkout", "continue", "go to checkout")
# Inputs whose value would be a coupon/code. Discovered but kept observe-only,
# because typing a real code blindly is a half-baked test; promo flows are a
# follow-up that needs a seeded value.
_CODE_INPUT_WORDS = ("promo", "coupon", "voucher", "gift card", "discount code", "code", "offer")

_GENERIC_SUCCESS = [
    "page or cart state visibly updated after the action",
    "selection/option applied or cart line changed",
]
_OPTION_TAGS = {"select"}
_OPTION_ROLES = {"radio", "listbox", "combobox", "menuitemradio", "option", "switch"}

# A control that operates on the CURRENT product/cart tends to start with an
# action verb. A recommendation/cross-sell tile is a product name (often with a
# "|" spec separator) linking to another product. We keep the former, drop the
# latter — otherwise "Streax Hair Colour" or "Dog Food ... Flavour" get mistaken
# for variant options because their names contain option keywords.
_ACTION_PREFIXES = (
    "save for later", "save for", "move to cart", "move to", "add to list",
    "add to wish", "delete", "remove", "increase quantity", "decrease quantity",
    "increase", "decrease", "change quantity", "select", "choose", "apply",
    "add gift", "gift option", "gift wrap", "gift receipt",
)
# Links carrying these are navigation to another product / listing, not a control.
_PRODUCT_LINK_HINTS = ("/dp/", "/gp/product/", "/gp/aw/d/", "/b/", "/s?", "/stores/", "/shop/")
# Phrases that mark a recommendation / cross-sell rather than a current-item control.
_SKIP_PHRASES = ("buy again", "buy it again", "sponsored", "customers also",
                 "see all", "see more", "view more", "compare with", "related to")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s[:40] or "control"


def _decode(s: str) -> str:
    # Amazon aria-labels are sometimes double-escaped (&amp;#39;), so unescape twice.
    return html.unescape(html.unescape(s or "")).strip()


# Cart-line controls carry the whole product title in their aria-label
# ("Delete Allen Solly Men's Polo (8907...)"). Collapse to the clean action verb
# so the report reads "Delete item", not a 60-char product code string.
_CLEAN_PREFIX = (
    ("decrease quantity", "Decrease quantity"),
    ("increase quantity", "Increase quantity"),
    ("change quantity", "Change quantity"),
    ("save for later", "Save for later"),
    ("move to cart", "Move to cart"),
    ("add to list", "Add to list"),
    ("add to wish", "Add to wish list"),
    ("delete", "Delete item"),
    ("remove", "Remove item"),
)


def _clean_label(label: str) -> str:
    s = _decode(label)
    low = s.lower()
    for prefix, clean in _CLEAN_PREFIX:
        if low.startswith(prefix):
            return clean
    return re.sub(r"\s+", " ", s)[:48]


# Tokens that mark a string as an internal DOM identifier / widget scaffolding
# rather than a human-meaningful control label. Amazon's variant ("twister")
# widgets expose dozens of these (a-autoid-N-announce, inline-twister-*,
# color_name_0) — they are NOT separate tests and must not be discovered.
_NOISE_TOKENS = (
    "autoid", "announce", "twister", "sprite", "a-button-inner", "a-popover",
    "a-declarative", "dim-title", "expanded-dimension", "_name_", "data-csa",
    "a-offscreen", "a-hidden",
)


def _looks_like_internal_id(label: str) -> bool:
    """True when a label is DOM scaffolding, not something a user would read."""
    low = label.lower()
    if any(tok in low for tok in _NOISE_TOKENS):
        return True
    # Must contain at least one letter and be more than a stray digit/glyph.
    if len(label.strip()) < 2 or not re.search(r"[a-zA-Z]", label):
        return True
    # A hyphen/underscore slug with no spaces (e.g. "color_name_0",
    # "inline-twister-dim") is an id, not a label. Real labels read as words.
    if " " not in label and re.fullmatch(r"[a-z0-9]+([-_][a-z0-9]+)+", low):
        return True
    return False


def _label_for(el: UIElement) -> str:
    # Prefer human-readable accessible text; skip any candidate that is actually
    # an internal identifier. id/name are deliberately NOT used as labels.
    for cand in (el.aria_label, el.text, el.value):
        c = re.sub(r"\s+", " ", _decode(cand))
        if c and not c.startswith("<") and not _looks_like_internal_id(c):
            return c[:60]
    return ""


def _aliases_for(el: UIElement, label: str) -> list[str]:
    out: list[str] = []
    for cand in (label, el.text, el.aria_label, el.value, el.name):
        c = _decode(cand).lower()
        if c and c not in out and not c.startswith("<"):
            out.append(c[:40])
    return out[:8]


def _is_option_control(el: UIElement) -> bool:
    """A form control that selects a product variant/option, structurally."""
    if (el.tag or "").lower() in _OPTION_TAGS:
        return True
    if (el.role or "").lower() in _OPTION_ROLES:
        return True
    if (el.type or "").lower() in {"radio"}:
        return True
    return False


def _is_navigation_to_other_product(el: UIElement) -> bool:
    """True for links/tiles that take you to a different product or listing."""
    href = (getattr(el, "href", None) or "").lower()
    if (el.tag or "").lower() == "a" and any(h in href for h in _PRODUCT_LINK_HINTS):
        return True
    return False


def _is_current_item_control(el: UIElement, label: str) -> bool:
    """Keep controls that operate on THIS product/cart; drop product tiles.

    A genuine control either is a structural option control, or reads as an action
    ("Save for later", "Increase quantity", "Coral", "XL"). A recommendation tile
    reads as a product title — long, often with a "|" spec separator.
    """
    low = label.lower()
    if "|" in label:
        return False
    if _is_option_control(el):
        return True
    if any(low.startswith(p) for p in _ACTION_PREFIXES):
        return True
    # Short, control-like labels (a colour name, a size) are fine; long strings
    # are almost always product titles, not controls.
    return len(label) <= 32


def _classify(el: UIElement, haystack: str) -> tuple[str, str] | None:
    """Return (risk, reason) for a candidate control, or None to skip it.

    Safety-first and deterministic: the forbidden check wins over everything, so a
    dynamically discovered "Place Order" can never be classified as clickable.
    """
    # 1) Hard safety: anything that reads like final payment is forbidden, always.
    if is_forbidden_text(haystack):
        return RISK_FORBIDDEN_CLICK, "matched final-purchase boundary text"

    # 2) Skip the controls the tuned catalogue already owns.
    if any(term in haystack for term in _CATALOGUE_OWNED):
        return None

    # 3) Destructive (delete/remove) — discovered, but gated by --allow-destructive.
    if any(w in haystack for w in _DESTRUCTIVE_WORDS):
        return RISK_DESTRUCTIVE_CLICK, "destructive cart control"

    # 4) Promo / coupon / offer controls are now exercised as mutating actions
    #    (expand / apply). A bare text input stays observe-only because blind
    #    filling needs a seeded code; the apply/expand button is what we click.
    if any(w in haystack for w in _CODE_INPUT_WORDS):
        if (el.tag or "").lower() == "input" and (el.type or "text").lower() in {"text", "", "search"}:
            return RISK_OBSERVE_ONLY, "promo/code text input (needs a seeded value to fill)"
        return RISK_MUTATING_CLICK, "promo/coupon/offer control"

    # 5) Product options / variants / quantity / save-for-later — mutating clicks.
    if _is_option_control(el):
        return RISK_MUTATING_CLICK, "structural product-option control"
    if any(w in haystack for w in _MUTATING_WORDS):
        return RISK_MUTATING_CLICK, "matched product-option / cart-mutation keyword"

    # 6) Benign in-flow navigation (e.g. "Continue to checkout" interstitial).
    if any(w in haystack for w in _SAFE_NAV_WORDS):
        return RISK_SAFE_CLICK, "in-flow checkout navigation"

    # 7) Anything else is not a checkout-relevant action — skip it (nav, footer,
    #    reviews, recommendations, account links, etc.).
    return None


def discover_dynamic_intents(
    obs: PageObservation,
    *,
    source: str = SOURCE_CRAWLER,
    max_intents: int = 10,
) -> list[NormalizedIntent]:
    """Turn the actually-present interactable controls into executable intents.

    No fixed catalogue: whatever this product exposes becomes a candidate, with a
    deterministic, safety-first risk class. The frontier's gates and memory still
    decide whether each one is clicked, observed, or never touched.
    """
    out: list[NormalizedIntent] = []
    seen_ident: set[str] = set()
    for el in obs.elements:
        if not el.visible:
            continue
        # Nav/header chrome is not part of configuring or buying this product.
        if getattr(el, "in_nav_or_header", False):
            continue
        # Must be something a user can actually operate.
        is_form_control = _is_option_control(el) or (el.tag or "").lower() in {"input", "button", "a", "select"}
        if not (el.clickable or el.interactable or is_form_control):
            continue
        label = _label_for(el)
        if not label:
            continue
        # Don't follow recommendation / cross-sell tiles to other products, and
        # don't mistake a product title (which may contain "colour"/"flavour"/
        # "size") for a variant control of the current item.
        if _is_navigation_to_other_product(el):
            continue
        if any(p in label.lower() for p in _SKIP_PHRASES):
            continue
        if not _is_current_item_control(el, label):
            continue
        haystack = el.haystack

        classified = _classify(el, haystack)
        if classified is None:
            continue
        risk, reason = classified

        clean_label = _clean_label(label)
        canonical_key = f"dynamic.{_slug(clean_label)}"
        clickable_risk = risk in {RISK_SAFE_CLICK, RISK_MUTATING_CLICK, RISK_DESTRUCTIVE_CLICK}
        selectors = [el.selector] if el.selector else []
        ni = NormalizedIntent(
            canonical_key=canonical_key,
            human_label=clean_label if len(clean_label) > 2 else f"Option: {clean_label}",
            expected_state=obs.state,
            source=source,
            risk=risk,
            # Options/variants should be explored before the deeper checkout
            # transition but after cheap observe-only reads.
            priority=0.55 if risk == RISK_MUTATING_CLICK else (0.50 if risk == RISK_SAFE_CLICK else 0.45),
            ui_element=el,
            selector_candidates=selectors,
            semantic_target=label,
            aliases=_aliases_for(el, label),
            success_criteria=list(_GENERIC_SUCCESS),
            confidence=0.70,
            semantic_score=0.70,
            selector_quality_score=0.80 if el.can_execute else 0.0,
            reason=f"dynamic discovery: {reason}",
            click_allowed=clickable_risk,
            executable=bool(clickable_risk and el.can_execute),
        )
        if ni.identity in seen_ident:
            continue
        seen_ident.add(ni.identity)
        out.append(ni)
        if len(out) >= max_intents:
            break
    return out
