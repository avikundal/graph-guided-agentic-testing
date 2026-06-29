"""Regression tests for safety wiring and product-provenance generalization.

These cover the issues surfaced by live runs:
  - an LLM/graph suggestion must never be able to downgrade the canonical risk
    of an intent (e.g. relabel a destructive/checkout action as "safe_click");
  - product/cart identity is derived generically (ASIN + product-name token
    overlap), with no hardcoded product title.
"""

from src.explorer.semantic_normalizer import SemanticNormalizer
from src.explorer.graph_guided_explorer import (
    _asin_from_url,
    _asin_in_observation,
    _cart_item_count,
    _cart_subtotal,
    _cart_url_for,
    _clean_name,
    _title_near_asin,
)


class _Obs:
    def __init__(self, text, elements=None):
        self.text = text
        self.elements = elements or []


# ----------------------------- safety -----------------------------

def test_llm_suggestion_cannot_downgrade_risk():
    n = SemanticNormalizer()
    # Suggestion claims a destructive action is a safe click.
    ni = n.normalize_suggestion(
        {"canonical_key": "action.delete_item", "title": "delete remove from cart", "risk": "safe_click"}
    )
    assert ni is not None
    assert ni.risk == "destructive_click"  # canonical contract wins


def test_llm_suggestion_priority_still_respected():
    n = SemanticNormalizer()
    ni = n.normalize_suggestion(
        {"canonical_key": "action.change_quantity", "title": "change quantity qty", "priority": 0.91}
    )
    assert ni is not None
    assert ni.priority == 0.91


# --------------------------- provenance ---------------------------

def test_asin_extracted_from_various_url_forms():
    assert _asin_from_url("https://www.amazon.com/dp/0307887898") == "0307887898"
    assert _asin_from_url("https://www.amazon.com/gp/product/0307887898/ref=x") == "0307887898"
    assert _asin_from_url("https://www.amazon.com/some/category") == ""


def test_checkout_validates_through_benign_interstitial():
    from src.explorer.graph_guided_explorer import _checkout_reached_ok
    # amazon.in inserts a "Continue to checkout" carousel before secure checkout;
    # reaching the checkout state should validate despite the extra click.
    assert _checkout_reached_ok("checkout", "https://www.amazon.in/checkout/entry/cart", "agent_wandered:multiple_ui_actions")
    # ...but a sign-in redirect must NOT validate.
    # ...and a sign-in redirect is also an acceptable terminal checkout/auth boundary.
    assert _checkout_reached_ok("checkout", "https://www.amazon.com/ap/signin?...", "")
    # ...and a wrong-target wander (clicked cart/logo) must NOT validate.
    assert not _checkout_reached_ok("checkout", "https://www.amazon.com/checkout", "wrong_target_for_checkout:cart")
    # ...and not reaching checkout at all must NOT validate.
    assert not _checkout_reached_ok("shopping_cart", "https://www.amazon.com/gp/cart/view.html", "")


def test_cart_url_follows_product_domain():
    # The cart must be on the SAME marketplace as the product, or the item is
    # added on one Amazon domain and the cart read on another (empty) one.
    assert _cart_url_for("https://www.amazon.in/dp/1847941834") == "https://www.amazon.in/gp/cart/view.html"
    assert _cart_url_for("https://www.amazon.com/dp/0307887898") == "https://www.amazon.com/gp/cart/view.html"
    assert _cart_url_for("https://www.amazon.co.uk/dp/X") == "https://www.amazon.co.uk/gp/cart/view.html"
    assert _cart_url_for("not-a-url") == "https://www.amazon.com/gp/cart/view.html"


def test_cart_item_count_from_nav_label():
    assert _cart_item_count(_Obs("[5]<a aria-label=2 items in cart id=nav-cart />")) == 2
    assert _cart_item_count(_Obs("[5]<a aria-label=0 items in cart id=nav-cart />")) == 0
    assert _cart_item_count(_Obs("no count here")) is None


def test_title_near_asin_uses_productTitle_anchor_when_no_asin_match():
    text = "[1]<a id=nav-logo-sprites />\n[9]<span id=productTitle />\n\tThe Lean Startup: Continuous Innovation\n[10]<div />"
    assert _title_near_asin(_Obs(text), "9999999999") == "The Lean Startup: Continuous Innovation"


def test_clean_name_unescapes_entities():
    assert _clean_name("The Lean Startup: How Today&#39;s Entrepreneurs") == "The Lean Startup: How Today's Entrepreneurs"


# A longer recommendation alt must NOT be picked over our item's own title.
_REC_PAGE = (
    "[10]<a href=/dp/0307887898 />\n"
    "\t[11]<img alt=The Lean Startup: How Today Entrepreneurs Use Continuous Innovation />\n"
    "[900]<a href=/dp/0060517123 />\n"
    "\t[901]<img alt=Crossing the Chasm 3rd Edition The Updated Version of the Insightful Guide on Bringing Cutting-Edge Products to the Mainstream Market />\n"
)


def test_title_near_asin_ignores_longer_recommendation():
    # Regression for the false positive where the longest alt on the page
    # ("Crossing the Chasm") was matched instead of our ASIN's product.
    title = _title_near_asin(_Obs(_REC_PAGE), "0307887898")
    assert "Lean Startup" in title
    assert "Crossing the Chasm" not in title


def test_cart_subtotal_extracts_money_not_item_count():
    # The "(N items)" must never be parsed as the subtotal amount.
    assert _cart_subtotal(_Obs("Subtotal (2 items): INR 2,467.73")) == "2467.73"
    assert _cart_subtotal(_Obs("Subtotal (1 item): INR 1,233.86")) == "1233.86"
    assert _cart_subtotal(_Obs("subtotal: $13.08")) == "13.08"
    assert _cart_subtotal(_Obs("no money here")) is None


def test_quantity_change_is_detectable_by_subtotal_delta():
    # This is the signal that validates Change Quantity independent of browser-use.
    before = _cart_subtotal(_Obs("Subtotal (1 item): INR 1,233.86"))
    after = _cart_subtotal(_Obs("Subtotal (2 items): INR 2,467.73"))
    assert before and after and before != after


def test_asin_present_or_absent_in_observation():
    assert _asin_in_observation(_Obs(_REC_PAGE), "0307887898")
    assert not _asin_in_observation(_Obs("nothing relevant here"), "0307887898")
    assert not _asin_in_observation(_Obs(_REC_PAGE), "")  # no asin known -> never verify
