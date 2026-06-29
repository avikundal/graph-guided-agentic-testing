from src.explorer.page_observer import PageObserver
from src.domain.checkout_contract import STATE_CART, STATE_CHECKOUT, STATE_PRODUCT, STATE_FINAL


def test_state_detection():
    o = PageObserver()
    assert o.detect_state('https://www.amazon.com/dp/0307887898', 'Add to Cart') == STATE_PRODUCT
    assert o.detect_state('https://www.amazon.com/gp/cart/view.html', 'Shopping Cart Subtotal') == STATE_CART
    assert o.detect_state('https://www.amazon.com/checkout', 'Secure Checkout') == STATE_CHECKOUT
    assert o.detect_state('https://www.amazon.com/checkout', 'Place your order') == STATE_FINAL


def test_buy_now_on_product_page_is_not_final_boundary():
    o = PageObserver()
    state = o.detect_state('https://www.amazon.com/dp/0307887898', 'Product title Add to Cart Buy Now')
    assert state == STATE_PRODUCT
