from src.explorer.semantic_normalizer import SemanticNormalizer
from src.explorer.page_observer import UIElement


def score(key, text='', selector=None, state='shopping_cart'):
    from src.domain.checkout_contract import INTENTS
    n = SemanticNormalizer()
    el = UIElement(0, 'button', text, selector, id=(selector or '').replace('#','') if selector and selector.startswith('#') else None, clickable=True)
    return n.score_element(INTENTS[key], el, state)[0]


def test_nav_logo_never_matches_delete_quantity_promo():
    assert score('action.delete_item', selector='#nav-logo-sprites') == 0
    assert score('domain.quantity_control', selector='#nav-logo-sprites') == 0
    assert score('capability.promo_code', selector='#nav-logo-sprites') == 0


def test_nav_cart_only_go_to_cart():
    assert score('action.go_to_cart', selector='#nav-cart') > 0.5
    assert score('action.add_to_cart', selector='#nav-cart') == 0


def test_semantic_wording_maps_to_quantity_and_delete():
    assert score('domain.quantity_control', text='Qty: 1') > 0.5
    assert score('action.delete_item', text='Remove from cart') > 0.5


def test_generic_selectors_are_not_executable():
    from src.domain.checkout_contract import INTENTS
    n = SemanticNormalizer()
    el = UIElement(0, 'input', 'Proceed to Checkout', 'input', name=None, clickable=True, visible=True, enabled=True, interactable=True, selector_quality='generic')
    intent = n._from_spec(INTENTS['action.proceed_to_checkout'], 'crawler_observed', el, 0.9, 0.9, n.selector_quality_for(el, INTENTS['action.proceed_to_checkout']), 'generic')
    assert not intent.executable


def test_stable_selector_can_be_executable():
    from src.domain.checkout_contract import INTENTS
    n = SemanticNormalizer()
    el = UIElement(0, 'input', '', "input[name='proceedToRetailCheckout']", name='proceedToRetailCheckout', clickable=True, visible=True, enabled=True, interactable=True, selector_quality='stable')
    sem, qual, _ = n.score_element(INTENTS['action.proceed_to_checkout'], el, 'shopping_cart')
    intent = n._from_spec(INTENTS['action.proceed_to_checkout'], 'crawler_observed', el, 0.9, sem, qual, 'stable')
    assert intent.executable
