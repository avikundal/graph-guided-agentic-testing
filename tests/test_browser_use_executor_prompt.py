from src.explorer.browser_use_executor import _repeat_key, _safe_intent_id, _safe_prompt_list, _looks_like_internal_action_url, BrowserUseIntentExecutor
from src.explorer.semantic_normalizer import SemanticNormalizer
from src.domain.checkout_contract import INTENTS, SOURCE_DOMAIN


def test_safe_intent_id_removes_dotted_canonical_key():
    assert _safe_intent_id('action.proceed_to_checkout') == 'PROCEED_TO_CHECKOUT'
    assert _safe_intent_id('domain.final_order_boundary') == 'FINAL_ORDER_BOUNDARY'


def test_safe_prompt_list_removes_dots_that_browser_use_treats_as_urls():
    text = _safe_prompt_list(['submit.add-to-cart', 'proceedtoretailcheckout'])
    assert 'submit.add-to-cart' not in text
    assert 'submit add-to-cart' in text
    assert 'proceedtoretailcheckout' in text


def test_internal_action_url_guard():
    assert _looks_like_internal_action_url('https://action.proceed/')
    assert _looks_like_internal_action_url('https://domain.final/')
    assert not _looks_like_internal_action_url('https://www.amazon.com/gp/cart/view.html')


def test_coupon_values_share_one_repeat_key():
    assert _repeat_key("text=VALIDCOUPON123") == "cart:promo_code"
    assert _repeat_key("text=INVALIDCOUPON123") == "cart:promo_code"
    assert _repeat_key("Apply coupon") == "cart:promo_code"
    assert _repeat_key("text=10") == "text=10"


def test_intent_task_does_not_include_dotted_canonical_key_or_fake_url_seed():
    normalizer = SemanticNormalizer()
    spec = INTENTS['action.proceed_to_checkout']
    intent = normalizer._from_spec(spec, SOURCE_DOMAIN, None, 0.8, 0.8, 0.0, 'test')
    executor = BrowserUseIntentExecutor(headless=True)
    prompt = executor._intent_task(intent).lower()
    assert 'action.proceed' not in prompt
    assert 'action.proceed_to_checkout' not in prompt
    assert 'https://action' not in prompt
    assert 'proceed to checkout' in prompt

from src.explorer.browser_use_executor import BrowserUseStepArtifact
from src.explorer.page_observer import PageObservation


def _obs(state='shopping_cart', text='', url='https://www.amazon.com/gp/cart/view.html'):
    return PageObservation(
        url=url,
        title='',
        state=state,
        state_scores={},
        state_evidence={},
        text=text,
        elements=[],
        detected_concepts=set(),
        forbidden_action_detected=False,
        forbidden_boundary_detected=False,
    )


def test_phase2_prompt_constrains_browser_use_to_one_ui_action():
    normalizer = SemanticNormalizer()
    intent = normalizer._from_spec(INTENTS['action.proceed_to_checkout'], SOURCE_DOMAIN, None, 0.8, 0.8, 0.0, 'test')
    executor = BrowserUseIntentExecutor(headless=True)
    prompt = executor._intent_task(intent).lower()
    assert 'execute at most one ui-changing action' in prompt
    assert 'you are the executor, not the planner' in prompt
    assert 'do not click again' in prompt
    assert 'negative targets' in prompt
    assert 'add to cart' in prompt  # explicit negative target for checkout


def test_phase2_status_downgrades_browser_use_failure_text_for_quantity():
    normalizer = SemanticNormalizer()
    intent = normalizer._from_spec(INTENTS['action.change_quantity'], SOURCE_DOMAIN, None, 0.8, 0.8, 0.0, 'test')
    executor = BrowserUseIntentExecutor(headless=True)
    after = _obs(text="Attempted to change quantity but no changes in quantity or subtotal were observed.")
    status = executor._status_for_result(intent, None, after, 'click', ['subtotal visible'], '')
    assert status == 'clicked_observed'


def test_phase2_status_blocks_signin_redirect_for_checkout():
    normalizer = SemanticNormalizer()
    intent = normalizer._from_spec(INTENTS['action.proceed_to_checkout'], SOURCE_DOMAIN, None, 0.8, 0.8, 0.0, 'test')
    executor = BrowserUseIntentExecutor(headless=True)
    after = _obs(state='unknown', text='Redirected to sign-in page instead of secure checkout.', url='https://www.amazon.com/ap/signin')
    status = executor._status_for_result(intent, None, after, 'click', [], '')
    assert status == 'blocked_signin'


def test_phase2_contract_flags_multiple_clicks_as_wandering():
    normalizer = SemanticNormalizer()
    intent = normalizer._from_spec(INTENTS['action.proceed_to_checkout'], SOURCE_DOMAIN, None, 0.8, 0.8, 0.0, 'test')
    executor = BrowserUseIntentExecutor(headless=True)
    executor._active_intent = intent
    executor._track_phase2_contract(BrowserUseStepArtifact(1, '', '', 'shopping_cart', 'click', 'Proceed to Checkout', "[name='proceedToRetailCheckout']", ''))
    executor._track_phase2_contract(BrowserUseStepArtifact(2, '', '', 'unknown', 'click', 'Amazon logo', '#nav-logo', ''))
    assert any('multiple_ui_actions' in w for w in executor._task_warnings)
    assert any('wrong_target' in w for w in executor._task_warnings)


def test_phase3_go_to_cart_already_satisfied_is_not_validated_click():
    normalizer = SemanticNormalizer()
    intent = normalizer._from_spec(INTENTS['action.go_to_cart'], SOURCE_DOMAIN, None, 0.8, 0.8, 0.0, 'test')
    executor = BrowserUseIntentExecutor(headless=True)
    after = _obs(state='shopping_cart', text='The shopping cart page is already visible. No action was taken as the intent was satisfied.')
    status = executor._status_for_result(intent, None, after, 'done', ['after_state=shopping_cart'], '')
    assert status == 'already_satisfied'


def test_phase3_checkout_failure_text_not_counted_as_clicked_observed_even_if_click_attempted():
    normalizer = SemanticNormalizer()
    intent = normalizer._from_spec(INTENTS['action.proceed_to_checkout'], SOURCE_DOMAIN, None, 0.8, 0.8, 0.0, 'test')
    executor = BrowserUseIntentExecutor(headless=True)
    after = _obs(state='shopping_cart', text="ELEMENT_NOT_FOUND: The Proceed to Checkout button was not visible on the cart page.")
    status = executor._status_for_result(intent, None, after, 'click', [], '')
    assert status == 'not_grounded'
