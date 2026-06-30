"""Deny-list safety veto tests.

The veto is the one hard guarantee in an otherwise default-allow system: the
agent may try anything it discovers, EXCEPT final payment and off-product
navigation. These tests lock those two blocks down and prove that ordinary,
allowed actions (add to cart, change quantity, proceed to checkout, same-product
navigation) are NOT blocked — an over-eager veto would defeat discovery.
"""
from src.explorer.safety_guard import asin_from_url, host_of, veto_reason

PROD_ASIN = "B06Y2DV85R"
BASE_HOST = "www.amazon.in"


def _veto(target="", url="", action_type="click"):
    return veto_reason(
        target_label=target, action_url=url, action_type=action_type,
        product_asin=PROD_ASIN, base_host=BASE_HOST,
    )


# ----------------------------- payment (hard line) -----------------------------

def test_blocks_final_payment_by_button_text():
    assert _veto(target="Place your order")
    assert _veto(target="Pay now")
    assert _veto(target="Buy now")
    assert _veto(target="Confirm purchase")
    assert _veto(target="Submit order")


def test_blocks_payment_by_order_url():
    assert _veto(action_type="navigate", url="https://www.amazon.in/gp/buy/spc/handlers/display.html")
    assert _veto(action_type="navigate", url="https://www.amazon.in/checkout/payment")


# --------------------------- off-product navigation ----------------------------

def test_blocks_navigation_to_a_different_product():
    r = _veto(action_type="navigate", url="https://www.amazon.in/dp/B0DIFFERENT")
    assert r and "off_product" in r


def test_blocks_navigation_to_external_site():
    r = _veto(action_type="navigate", url="https://www.flipkart.com/some-product")
    assert r and "off_product" in r


# ------------------------- allowed actions (must pass) -------------------------

def test_allows_normal_cart_actions():
    assert _veto(target="Add to cart") is None
    assert _veto(target="Proceed to checkout") is None       # NOT final payment
    assert _veto(target="Delete item") is None
    assert _veto(target="Save for later") is None
    assert _veto(target="Increase quantity") is None
    assert _veto(target="Apply coupon") is None


def test_allows_same_product_and_cart_navigation():
    assert _veto(action_type="navigate", url=f"https://www.amazon.in/dp/{PROD_ASIN}") is None
    assert _veto(action_type="navigate", url="https://www.amazon.in/gp/cart/view.html") is None
    assert _veto(action_type="navigate", url="https://www.amazon.in/checkout/entry/cart") is None


def test_clicks_to_other_products_are_not_url_vetoed_pre_execution():
    # A click doesn't carry a destination URL, so off-product clicks are handled
    # by prompt + post-hoc recovery, not this pre-execution veto. It must NOT
    # false-positive (which would block legitimate discovery clicks).
    assert _veto(target="Some product tile", url="", action_type="click") is None


# --------------------------------- helpers ------------------------------------

def test_url_parsers():
    assert asin_from_url("https://www.amazon.in/dp/B06Y2DV85R?th=1") == "B06Y2DV85R"
    assert asin_from_url("https://www.amazon.in/gp/product/B06Y2DV85R") == "B06Y2DV85R"
    assert asin_from_url("https://www.amazon.in/gp/cart/view.html") == ""
    assert host_of("https://www.amazon.in/dp/X") == "www.amazon.in"


def test_blocks_session_destroying_actions():
    assert _veto(target="Sign out")
    assert _veto(target="Switch accounts")
    assert _veto(target="Add to cart") is None   # still allowed


def test_blocks_cart_action_on_a_different_product():
    from src.explorer.safety_guard import product_tokens, is_other_product_label
    tt = product_tokens("Allen Solly Men's Casual Polo Shirt")
    # wrong product (recommendation/cross-sell) -> blocked
    assert is_other_product_label("Delete URBAN FOREST Theo Sand Leather Wallet, Diamond", tt)
    assert is_other_product_label("Increase quantity by one Van Heusen Men's Solid Polo", tt)
    # the item under test -> allowed
    assert not is_other_product_label("Delete Allen Solly Men's Casual Polo Shirt (AMKP)", tt)
    # generic labels with no product name -> allowed (not judged)
    assert not is_other_product_label("Add to cart", tt)
    assert not is_other_product_label("Proceed to checkout", tt)
