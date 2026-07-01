"""Deny-list safety veto for an autonomous browser agent.

Design (agreed): the agent is free to discover and try ANY action — that is the
whole point of using a graph to surface scenarios nobody pre-conceived. An
allow-list would block every newly-discovered intent and defeat that purpose. So
safety is a *deny-list*: default-allow, and block only a short list of known-bad
actions before they execute.

The veto is deliberately short, but the cart page gets one extra boundary: only
cart controls are actionable there. Recommendation rails can create effectively
infinite labels, so cart-page product tiles/sponsored links are blocked
before they can burn tokens or add unrelated items.

The veto runs in the browser-use step callback, which fires after the LLM picks
an action but BEFORE it executes, so raising ``ForbiddenActionVeto`` prevents the
action from ever running.
"""
from __future__ import annotations

import re

from ..domain.checkout_contract import FORBIDDEN_TERMS, STATE_CART


class ForbiddenActionVeto(Exception):
    """Raised in the step callback to stop a denied action before it executes."""


# 1) Final-payment button text (irreversible). Reuse the canonical forbidden
#    terms so there is a single source of truth: place order, pay now, buy now,
#    confirm/complete purchase, submit order.
_PAYMENT_TERMS = tuple(FORBIDDEN_TERMS)

# 1b) Order-placement / payment endpoints — the second lock on the money line.
_ORDER_URL_PATTERNS = (
    "/gp/buy/spc",          # Amazon single-page-checkout place-order handlers
    "/gp/buy/payselect",
    "/gp/buy/shipoptionselect",
    "/gp/buy/thankyou",
    "place-order", "placeorder", "place_your_order",
    "/checkout/p/", "/checkout/payment", "/payments/",
)

# Session-destroying account actions. Not payment, but they log the run out and
# derail everything — a known-bad action worth a deny-list entry.
_SESSION_TERMS = ("sign out", "signout", "log out", "logout", "switch account", "switch accounts")
_ACCOUNT_LIST_TERMS = ("wish list", "wishlist", "add to wish", "add to list")

_CART_CONTROL_TERMS = (
    "quantity", "increase", "decrease", "delete", "remove", "save for later",
    "move to cart", "coupon", "promo", "gift", "apply", "proceed", "checkout",
    "go to cart", "view cart", "open cart",
    # NOTE: ratings/reviews/stars are deliberately NOT cart controls. They are
    # observed passively; clicking them navigates away into review pages (unknown
    # state) and burns steps, so on the cart page such clicks are vetoed.
)

_CART_JUNK_TERMS = (
    "sponsored", "recommended", "recommendation", "customers also", "similar item",
    "related item", "frequently bought", "buy again", "carousel", "see more", "view item",
)

# Navigation-style actions whose destination URL we can inspect before it runs.
_NAV_ACTIONS = {"navigate", "go_to_url", "open_tab", "new_tab"}

_ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})", re.I)
_HOST_RE = re.compile(r"^https?://([^/]+)", re.I)

# Cart/action words stripped before comparing a label's PRODUCT tokens, so we
# compare the product name, not the action verb.
_LABEL_STOPWORDS = {
    "quantity", "increase", "decrease", "delete", "remove", "save", "later", "move",
    "cart", "item", "items", "list", "wish", "gift", "updating", "update", "added",
    "proceed", "checkout", "change", "button", "option", "options", "price", "total",
    "subtotal", "stock", "this", "that", "with", "from", "your", "into", "back", "shopping",
}


def product_tokens(title: str) -> frozenset:
    """The BRAND tokens of the item under test — the first couple of significant
    words, which distinguish one product from another (two polos share 'polo' but
    not the brand). Used to tell the item under test from a recommendation."""
    sig = [t for t in re.findall(r"[a-z]{4,}", (title or "").lower()) if t not in _LABEL_STOPWORDS]
    return frozenset(sig[:2])


def is_other_product_label(label: str, brand_tokens) -> bool:
    """True if a cart-line action label clearly names a DIFFERENT product than the
    one under test (a recommendation/cross-sell the agent wandered onto): it carries
    a product name but shares none of the item-under-test's brand tokens."""
    if not brand_tokens or len(label) < 25:
        return False
    toks = {t for t in re.findall(r"[a-z]{4,}", label.lower())} - _LABEL_STOPWORDS
    if len(toks) < 2:  # not enough product-name content to judge
        return False
    return not (toks & set(brand_tokens))


def is_cart_relevant_action(label: str) -> bool:
    """Cart crawl is bounded: only controls that mutate/validate this cart count.

    Amazon cart pages include endless recommendation product labels. Treating all
    visible labels as "new actions" makes no-repeat chase junk forever.
    """
    text = (label or "").lower()
    return any(t in text for t in _CART_CONTROL_TERMS)


def is_cart_junk_action(label: str) -> bool:
    text = (label or "").lower()
    if any(t in text for t in _CART_JUNK_TERMS):
        return True
    if ("add to cart" in text or "add to basket" in text) and any(t in text for t in ("sponsored", "recommended", "stars", "rating", "review")):
        return True
    return False


def asin_from_url(url: str) -> str:
    m = _ASIN_RE.search(url or "")
    return m.group(1).upper() if m else ""


def host_of(url: str) -> str:
    m = _HOST_RE.match(url or "")
    return m.group(1).lower() if m else ""


def veto_reason(
    *,
    target_label: str,
    action_url: str,
    action_type: str,
    product_asin: str,
    base_host: str,
    product_title_tokens=frozenset(),
    page_state: str = "",
) -> str | None:
    """Return a short reason string if this action must be blocked, else None."""
    text = (target_label or "").lower()
    url = (action_url or "").lower()

    # 1) Final payment — text OR order-placement URL. Never crossed.
    if any(t in text for t in _PAYMENT_TERMS):
        return f"payment:text:{text[:40]}"
    if any(p in url for p in _ORDER_URL_PATTERNS):
        return f"payment:url:{url[:60]}"

    # 1c) Session-destroying account actions (sign out / switch account).
    if any(t in text for t in _SESSION_TERMS):
        return f"session:{text[:30]}"
    # Wishlist / account-list actions are not cart save-for-later. They often
    # trigger sign-in and derail the checkout/cart run.
    if action_type in {"click", "select", "fill"} and any(t in text for t in _ACCOUNT_LIST_TERMS):
        return f"account_list:{text[:40]}"

    # 2a) Off-product CART action — the agent wandered onto a recommendation /
    #     cross-sell for a DIFFERENT product. Blocking this is the user's own
    #     boundary ("only the product under test").
    if action_type in {"click", "select", "fill"} and is_other_product_label(text, product_title_tokens):
        return "off_product:other_item"

    # 2b) Adding ANOTHER product from the CART page (recommendation / cross-sell,
    #     same brand or not). On the product page 'add to cart' is the item under
    #     test; on the cart page it is always a different item being added.
    if action_type in {"click", "select", "fill"} and page_state == STATE_CART and (
        "add to cart" in text or "add to basket" in text
    ):
        return "off_product:cart_recommendation_add"

    # 2c) Cart-page action surface bound. Raw cart pages include infinite
    # recommendation/tile/review labels; these are not cart controls.
    if action_type in {"click", "select", "fill"} and page_state == STATE_CART:
        if is_cart_junk_action(text) or not is_cart_relevant_action(text):
            return "cart_scope:irrelevant_action"

    # 2) Off-product navigation (navigation-style actions whose URL we can read).
    if action_type in _NAV_ACTIONS and url.startswith("http"):
        host = host_of(url)
        if base_host and host and host != base_host:
            return f"off_product:external:{host}"
        other = asin_from_url(url)
        if other and product_asin and other != product_asin:
            return f"off_product:other_asin:{other}"
    return None
