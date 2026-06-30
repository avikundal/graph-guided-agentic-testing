"""Tests for dynamic, page-driven action discovery.

These lock in the two things that matter most: the discovery generalizes beyond
the fixed catalogue (a product's own size/colour/variant controls become
executable intents), and the risk classification is safety-first (a dynamically
discovered final-purchase control is forced to FORBIDDEN and never clickable).
"""
from src.domain.checkout_contract import (
    RISK_DESTRUCTIVE_CLICK,
    RISK_FORBIDDEN_CLICK,
    RISK_MUTATING_CLICK,
    RISK_OBSERVE_ONLY,
    STATE_CART,
    STATE_PRODUCT,
)
from src.explorer.dynamic_discovery import discover_dynamic_intents
from src.explorer.page_observer import PageObservation, UIElement


def _el(index, tag, text, selector, **kw):
    base = dict(
        visible=True, enabled=True, clickable=True, interactable=True,
        selector_quality="stable",
    )
    base.update(kw)
    return UIElement(index=index, tag=tag, text=text, selector=selector, **base)


def _obs(elements, state=STATE_PRODUCT):
    return PageObservation(
        url="https://www.amazon.in/dp/X", title="t", state=state,
        state_scores={}, state_evidence={}, text="", elements=elements,
    )


def _by_label(intents):
    return {i.human_label.lower(): i for i in intents}


def test_discovers_product_variant_options_not_in_catalogue():
    # A size dropdown and a colour swatch — neither is in the fixed contract.
    els = [
        _el(1, "select", "Choose a size", "select#size", aria_label="Size"),
        _el(2, "input", "Blue", "input#swatch-blue", type="radio", role="radio"),
    ]
    intents = discover_dynamic_intents(_obs(els))
    risks = {i.risk for i in intents}
    assert intents, "should discover at least the variant controls"
    assert risks == {RISK_MUTATING_CLICK}
    assert all(i.click_allowed for i in intents)
    assert all(i.canonical_key.startswith("dynamic.") for i in intents)


def test_forbidden_is_classified_safety_first_and_never_clickable():
    els = [_el(1, "input", "Place your order", "input#placeOrder", type="submit")]
    intents = discover_dynamic_intents(_obs(els, state=STATE_CART))
    assert len(intents) == 1
    assert intents[0].risk == RISK_FORBIDDEN_CLICK
    assert intents[0].click_allowed is False  # safety: discovered but never executed


def test_destructive_discovered_but_gated():
    els = [_el(1, "button", "Remove", "button[name=remove]", aria_label="Delete item")]
    intents = discover_dynamic_intents(_obs(els, state=STATE_CART))
    assert len(intents) == 1
    assert intents[0].risk == RISK_DESTRUCTIVE_CLICK
    # click_allowed True so the frontier can offer it, but --allow-destructive
    # still decides whether it actually runs (handled downstream).
    assert intents[0].click_allowed is True


def test_skips_catalogue_owned_and_navigation_noise():
    els = [
        _el(1, "input", "Add to Cart", "#add-to-cart-button"),          # catalogue owns it
        _el(2, "a", "Proceed to checkout", "input[name=proceed]"),       # catalogue owns it
        _el(3, "a", "See all reviews", "a#reviews"),                     # irrelevant noise
        _el(4, "a", "Sign in", "a#nav-signin", in_nav_or_header=True),   # nav chrome
        _el(5, "select", "Choose size", "select#size"),                 # the one real find
    ]
    labels = _by_label(discover_dynamic_intents(_obs(els)))
    assert "choose size" in labels
    assert "add to cart" not in labels
    assert "proceed to checkout" not in labels
    assert "see all reviews" not in labels
    assert "sign in" not in labels


def test_promo_input_is_observe_only_not_blind_filled():
    els = [_el(1, "input", "", "input#coupon", type="text", aria_label="Enter promo code")]
    intents = discover_dynamic_intents(_obs(els, state=STATE_CART))
    assert len(intents) == 1
    assert intents[0].risk == RISK_OBSERVE_ONLY
    assert intents[0].click_allowed is False


def test_respects_max_intents_cap():
    els = [_el(i, "select", f"Option {i}", f"select#o{i}", aria_label=f"Option {i}") for i in range(40)]
    intents = discover_dynamic_intents(_obs(els), max_intents=10)
    assert len(intents) == 10


def test_skips_recommendation_tiles_and_cross_sells():
    # The real failure: cart-page recommendation tiles whose product names contain
    # option keywords ("colour"/"flavour") were mistaken for variant controls and
    # the agent wandered onto other products. Controls for the current item stay.
    els = [
        _el(1, "a", "Streax Permanent Hair Colour, 100% Grey coverage", "a#rec1",
            href="https://www.amazon.in/dp/B0XYZ"),                                  # other product link
        _el(2, "a", "Purepet Dog Food 20kg | Chicken & Vegetable Flavour", "a#rec2",
            href="/dp/B0ABC"),                                                       # other product link
        _el(3, "button", "Buy again - Purepet Dog Food", "button#ba"),              # cross-sell phrase
        _el(4, "button", "Save for later Allen Solly Polo", "button#sfl",
            aria_label="Save for later Allen Solly Polo"),                           # real cart control
        _el(5, "input", "Coral", "input#sw", type="radio", role="radio", aria_label="Coral"),  # real option
    ]
    labels = _by_label(discover_dynamic_intents(_obs(els, state=STATE_CART)))
    assert any(l.startswith("save for later") for l in labels)
    assert "coral" in labels
    assert all("hair colour" not in l and "dog food" not in l for l in labels)
    assert all("buy again" not in l for l in labels)


def test_skips_internal_widget_scaffolding():
    # The real Amazon "twister" widget noise that flooded an earlier run: live
    # region announcers and internal ids must NOT become discovered actions.
    els = [
        _el(1, "a", "a-autoid-49-announce", "a#a-autoid-49-announce", aria_label="a-autoid-49-announce"),
        _el(2, "span", "inline-twister-dim-title-color_name", "span#inline-twister"),
        _el(3, "div", "color_name_0", "div#color_name_0"),
        _el(4, "button", "0", "button#opt0"),                       # stray glyph, no real label
        _el(5, "input", "Coral", "input#swatch", type="radio", role="radio", aria_label="Coral"),  # the real one
    ]
    labels = _by_label(discover_dynamic_intents(_obs(els)))
    assert "coral" in labels                       # the genuine colour option survives
    assert all("autoid" not in l and "twister" not in l and "color_name" not in l for l in labels)
    assert "0" not in labels
