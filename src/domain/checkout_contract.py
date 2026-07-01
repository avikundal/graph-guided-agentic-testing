from __future__ import annotations

from dataclasses import dataclass


STATE_PRODUCT = "product_detail"
STATE_CART_CONFIRMATION = "cart_confirmation"
STATE_CART = "shopping_cart"
STATE_CHECKOUT = "checkout"
STATE_FINAL = "final_order_boundary"
STATE_UNKNOWN = "unknown"

RISK_SAFE_CLICK = "safe_click"
RISK_MUTATING_CLICK = "mutating_click"
RISK_DESTRUCTIVE_CLICK = "destructive_click"
RISK_FORBIDDEN_CLICK = "forbidden_click"
RISK_OBSERVE_ONLY = "observe_only"

SOURCE_CRAWLER = "crawler_observed"
SOURCE_GRAPH = "graph_inferred"
SOURCE_LLM = "llm_neighbor"
SOURCE_DOMAIN = "domain_seed"

# Terms that should never be clicked by the explorer. `buy now` is a forbidden
# action for this prototype, but it is NOT enough to classify the whole page as
# final_order_boundary because Amazon product pages often show Buy Now.
FORBIDDEN_TERMS = [
    "place your order",
    "place order",
    "pay now",
    "confirm purchase",
    "complete purchase",
    "submit order",
    "buy now",
]

# Terms that mean a true final purchase boundary. This excludes Buy Now because
# product pages expose it as an entry point rather than final order placement.
FINAL_PURCHASE_TERMS = [
    "place your order",
    "place order",
    "pay now",
    "confirm purchase",
    "complete purchase",
    "submit order",
]


@dataclass(frozen=True)
class IntentSpec:
    canonical_key: str
    human_label: str
    intent_type: str
    expected_states: tuple[str, ...]
    aliases: tuple[str, ...]
    selector_hints: tuple[str, ...] = ()
    risk: str = RISK_OBSERVE_ONLY
    success_criteria: tuple[str, ...] = ()
    priority: float = 0.5
    click_allowed_by_default: bool = False
    deeper_transition: bool = False


INTENTS: dict[str, IntentSpec] = {
    "action.add_to_cart": IntentSpec(
        "action.add_to_cart", "Add to Cart", "action",
        (STATE_PRODUCT,),
        ("add to cart", "add-to-cart", "submit.add-to-cart"),
        ("#add-to-cart-button", "[name='submit.add-to-cart']"),
        RISK_SAFE_CLICK,
        ("cart confirmation visible", "cart item/subtotal visible"),
        1.00,
        True,
    ),
    "action.go_to_cart": IntentSpec(
        "action.go_to_cart", "Go to Cart", "action",
        (STATE_CART_CONFIRMATION, STATE_PRODUCT, STATE_CART),
        ("cart", "go to cart", "shopping cart", "basket"),
        ("#nav-cart", "a[href*='cart']"),
        RISK_SAFE_CLICK,
        ("shopping cart reached", "cart subtotal visible"),
        0.95,
        True,
        True,
    ),
    "action.proceed_to_checkout": IntentSpec(
        "action.proceed_to_checkout", "Proceed to Checkout", "action",
        (STATE_CART, STATE_CART_CONFIRMATION),
        ("proceed to checkout", "checkout", "proceedtoretailcheckout"),
        ("[name='proceedToRetailCheckout']", "input[name='proceedToRetailCheckout']"),
        RISK_SAFE_CLICK,
        ("secure checkout visible", "checkout url"),
        0.20,
        True,
        True,
    ),
    "domain.quantity_control": IntentSpec(
        "domain.quantity_control", "Quantity Control", "observation",
        (STATE_CART, STATE_CART_CONFIRMATION),
        ("quantity", "qty", "a-dropdown-prompt", "quantity dropdown", "update quantity"),
        ("select[name='quantity']", "span.a-dropdown-prompt", "[aria-label*='Quantity']"),
        RISK_OBSERVE_ONLY,
        ("quantity control visible",),
        0.88,
        False,
    ),
    "action.change_quantity": IntentSpec(
        "action.change_quantity", "Change Quantity", "action",
        (STATE_CART,),
        ("change quantity", "increase quantity", "decrease quantity", "qty", "quantity"),
        ("select[name='quantity']", "[aria-label*='Quantity']", "input[name='quantityBox']"),
        RISK_MUTATING_CLICK,
        ("quantity changed", "subtotal changed"),
        0.86,
        True,
    ),
    "action.delete_item": IntentSpec(
        "action.delete_item", "Delete Item", "action",
        (STATE_CART,),
        ("delete", "remove", "remove from cart", "trash"),
        ("input[value='Delete']", "[data-action='delete']", "[aria-label*='Delete']", "[aria-label*='Remove']"),
        RISK_DESTRUCTIVE_CLICK,
        ("cart item removed", "subtotal changed"),
        0.80,
        False,
    ),
    "action.save_for_later": IntentSpec(
        "action.save_for_later", "Save for Later", "action",
        (STATE_CART,),
        ("save for later", "save item for later", "move to saved"),
        ("input[value='Save for later']", "[aria-label*='Save for later']"),
        RISK_MUTATING_CLICK,
        ("item moved out of active cart",),
        0.78,
        False,
    ),
    "domain.subtotal": IntentSpec(
        "domain.subtotal", "Subtotal", "observation",
        (STATE_CART, STATE_CART_CONFIRMATION),
        ("subtotal", "cart total", "order summary"),
        (),
        RISK_OBSERVE_ONLY,
        ("subtotal visible",),
        0.75,
        False,
    ),
    "domain.cart_item": IntentSpec(
        "domain.cart_item", "Cart Item", "observation",
        (STATE_CART, STATE_CART_CONFIRMATION),
        ("cart item", "item in cart", "shopping cart"),
        (),
        RISK_OBSERVE_ONLY,
        ("cart item visible",),
        0.74,
        False,
    ),
    "domain.inventory_state": IntentSpec(
        "domain.inventory_state", "Inventory State", "observation",
        (STATE_PRODUCT, STATE_CART),
        ("in stock", "out of stock", "currently unavailable", "availability"),
        (),
        RISK_OBSERVE_ONLY,
        ("inventory/availability visible",),
        0.60,
        False,
    ),
    "capability.promo_code": IntentSpec(
        "capability.promo_code", "Promo / Gift Code", "observation",
        (STATE_CART, STATE_CHECKOUT),
        ("promo", "coupon", "gift card", "promotion code", "claim code"),
        ("input[name*='claim']", "input[name*='promo']", "input[placeholder*='code']"),
        RISK_OBSERVE_ONLY,
        ("promo or gift code field visible",),
        0.45,
        False,
    ),
    "domain.checkout_boundary": IntentSpec(
        "domain.checkout_boundary", "Checkout Boundary", "observation",
        (STATE_CHECKOUT,),
        ("secure checkout", "checkout", "address", "payment", "order review"),
        (),
        RISK_OBSERVE_ONLY,
        ("checkout reached",),
        0.70,
        False,
    ),
    "domain.final_order_boundary": IntentSpec(
        "domain.final_order_boundary", "Final Order Boundary", "observation",
        (STATE_CHECKOUT, STATE_FINAL),
        ("place order", "place your order", "pay now", "confirm purchase", "submit order"),
        (),
        RISK_FORBIDDEN_CLICK,
        ("final purchase boundary detected and not clicked",),
        0.99,
        False,
    ),
}


# Graph reasoning rules expressed as DATA, not code. Each rule names the
# prerequisite Concepts that must exist in the graph and the "pivot" action
# Concept whose validation would PROVE the behaviour. The graph infers a missed
# scenario when every prerequisite exists but the pivot was never validated —
# i.e. something the crawler stumbled near but did not actually exercise.
# Adding a new inferred scenario is a data edit here, not a code change.
INFERENCE_RULES: list[dict] = [
    {
        "key": "scenario.quantity_updates_subtotal",
        "title": "Changing quantity should recalculate subtotal",
        "requires": ["domain.cart_item", "domain.quantity_control", "domain.subtotal"],
        "pivot": "action.change_quantity",
        "status": "INFERRED_MISSED",
    },
    {
        "key": "scenario.delete_updates_subtotal",
        "title": "Deleting an item should update subtotal",
        "requires": ["domain.cart_item", "action.delete_item", "domain.subtotal"],
        "pivot": "action.delete_item",
        "status": "INFERRED_MISSED",
    },
    {
        "key": "scenario.save_for_later_removes_active_item",
        "title": "Save for later should move item out of active cart",
        "requires": ["domain.cart_item", "action.save_for_later"],
        "pivot": "action.save_for_later",
        "status": "INFERRED_MISSED",
    },
    {
        "key": "scenario.checkout_requires_address_payment",
        "title": "Address and payment are expected deeper in checkout",
        "requires": ["domain.checkout_boundary"],
        "pivot": None,
        "status": "BLOCKED_OR_NOT_REACHED",
    },
    {
        "key": "scenario.final_order_boundary_protected",
        "title": "Final order boundary must be detected and never crossed",
        "requires": ["domain.checkout_boundary"],
        "pivot": None,
        "status": "SAFETY_BOUNDARY",
    },
]

CAUSAL_EXPECTATIONS: list[dict] = [
    {
        "key": "cause.quantity_updates_subtotal",
        "title": "Changing quantity should update subtotal or cart totals",
        "cause": "action.change_quantity",
        "effect": "domain.subtotal",
        "state": STATE_CART,
    },
    {
        "key": "cause.delete_updates_cart_item",
        "title": "Deleting an item should update cart contents",
        "cause": "action.delete_item",
        "effect": "domain.cart_item",
        "state": STATE_CART,
    },
    {
        "key": "cause.save_for_later_updates_cart_item",
        "title": "Saving for later should move the item out of the active cart",
        "cause": "action.save_for_later",
        "effect": "domain.cart_item",
        "state": STATE_CART,
    },
    {
        "key": "cause.promo_code_updates_total_or_error",
        "title": "Applying a promo code should change totals or show a result",
        "cause": "capability.promo_code",
        "effect": "domain.subtotal",
        "state": STATE_CART,
    },
    {
        "key": "cause.checkout_reaches_boundary",
        "title": "Proceeding to checkout should reach the checkout boundary",
        "cause": "action.proceed_to_checkout",
        "effect": "domain.checkout_boundary",
        "state": STATE_CART,
    },
]

# The full feature contract — every Concept that SHOULD exist for this feature.
# Seeding these as expected=true lets absence ("what should exist but doesn't")
# be a queryable graph property rather than a Python set-difference.
EXPECTED_CONCEPTS: list[str] = list(INTENTS.keys())


def is_forbidden_text(text: str) -> bool:
    low = (text or "").lower()
    return any(term in low for term in FORBIDDEN_TERMS)


def has_final_purchase_text(text: str) -> bool:
    low = (text or "").lower()
    return any(term in low for term in FINAL_PURCHASE_TERMS)
