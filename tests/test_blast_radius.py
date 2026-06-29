"""Tests for the PR blast-radius stretch (contract-only, no graph needed)."""

from src.graph.blast_radius import (
    concepts_for_selectors,
    scan_diff_for_anchors,
    static_blast_radius,
)


def test_selector_maps_to_concept():
    assert "action.add_to_cart" in concepts_for_selectors(["#add-to-cart-button"])
    assert "action.proceed_to_checkout" in concepts_for_selectors(["input[name='proceedToRetailCheckout']"])


def test_subtotal_change_hits_quantity_and_delete_scenarios():
    radius = static_blast_radius(["domain.subtotal"], [])
    keys = {s["key"] for s in radius["impacted_inferred_scenarios"]}
    assert "scenario.quantity_updates_subtotal" in keys
    assert "scenario.delete_updates_subtotal" in keys


def test_add_to_cart_selector_blast_radius_lists_intent():
    radius = static_blast_radius([], ["#add-to-cart-button"])
    assert "action.add_to_cart" in radius["impacted_concepts"]
    labels = {i["canonical_key"] for i in radius["impacted_intents"]}
    assert "action.add_to_cart" in labels


def test_pivot_change_flags_its_scenario():
    radius = static_blast_radius(["action.change_quantity"], [])
    keys = {s["key"] for s in radius["impacted_inferred_scenarios"]}
    assert "scenario.quantity_updates_subtotal" in keys


def test_scan_diff_finds_known_anchors():
    diff = """
    --- a/cart.js
    +++ b/cart.js
    -  el = document.querySelector("#add-to-cart-button");
    +  el = document.querySelector("#add-to-cart-button-v2");
    // touches action.proceed_to_checkout flow
    """
    concepts, selectors = scan_diff_for_anchors(diff)
    assert "action.proceed_to_checkout" in concepts
    assert "#add-to-cart-button" in selectors
