"""Tests for the Reason pillar: graph-inferred 'missed' scenarios.

The graph path is exercised live in scripts; here we lock the deterministic
fallback (and the rule data) that mirror the Cypher inference, so the semantics
stay correct even without Neo4j.
"""

from src.domain.checkout_contract import INFERENCE_RULES, EXPECTED_CONCEPTS
from src.explorer.graph_guided_explorer import infer_missed_in_memory


def _keys(rows):
    return {r["key"] for r in rows}


def test_quantity_and_delete_inferred_when_observed_but_not_validated():
    observed = {"domain.cart_item", "domain.quantity_control", "domain.subtotal", "action.delete_item"}
    validated = {"action.add_to_cart"}  # quantity/delete never validated
    keys = _keys(infer_missed_in_memory(observed, validated, INFERENCE_RULES))
    assert "scenario.quantity_updates_subtotal" in keys
    assert "scenario.delete_updates_subtotal" in keys


def test_scenario_not_inferred_when_prerequisite_never_observed():
    # save_for_later was never observed -> its scenario must NOT be inferred.
    observed = {"domain.cart_item", "domain.subtotal"}
    keys = _keys(infer_missed_in_memory(observed, set(), INFERENCE_RULES))
    assert "scenario.save_for_later_removes_active_item" not in keys


def test_scenario_drops_once_pivot_is_validated():
    observed = {"domain.cart_item", "domain.quantity_control", "domain.subtotal"}
    # Now the agent DID validate the quantity change -> no longer "missed".
    validated = {"action.change_quantity"}
    keys = _keys(infer_missed_in_memory(observed, validated, INFERENCE_RULES))
    assert "scenario.quantity_updates_subtotal" not in keys


def test_checkout_boundary_scenarios_have_no_pivot():
    observed = {"domain.checkout_boundary"}
    keys = _keys(infer_missed_in_memory(observed, set(), INFERENCE_RULES))
    assert "scenario.checkout_requires_address_payment" in keys
    assert "scenario.final_order_boundary_protected" in keys


def test_expected_concepts_cover_the_contract():
    # Absence modeling depends on every contract concept being seedable.
    assert "action.add_to_cart" in EXPECTED_CONCEPTS
    assert "domain.final_order_boundary" in EXPECTED_CONCEPTS


def test_inferred_scenarios_map_to_executable_cart_pivots():
    # The loop-closing feedback depends on each cart-local missed scenario having
    # a real, cart-state action pivot the crawler can actually run.
    from src.domain.checkout_contract import INTENTS, STATE_CART
    from src.explorer.graph_guided_explorer import _RULE_BY_KEY

    for key in ["scenario.quantity_updates_subtotal", "scenario.delete_updates_subtotal", "scenario.save_for_later_removes_active_item"]:
        pivot = _RULE_BY_KEY[key]["pivot"]
        assert pivot in INTENTS, f"{key} pivot missing from contract"
        assert STATE_CART in INTENTS[pivot].expected_states, f"{pivot} not valid in cart state"

    # Boundary scenarios intentionally have no actionable pivot.
    assert _RULE_BY_KEY["scenario.final_order_boundary_protected"]["pivot"] is None
