from src.explorer.frontier import IntentFrontier
from src.explorer.semantic_normalizer import SemanticNormalizer
from src.domain.checkout_contract import INTENTS, SOURCE_DOMAIN, STATE_CART


def ni(key):
    return SemanticNormalizer()._from_spec(INTENTS[key], SOURCE_DOMAIN, None, 0.7, 'test')


def test_frontier_prioritizes_state_local_items():
    f = IntentFrontier()
    f.push(ni('action.proceed_to_checkout'))
    f.push(ni('action.change_quantity'))
    got = f.pop_for_state(STATE_CART)
    assert got.canonical_key == 'action.change_quantity'


def test_duplicate_skipped():
    f = IntentFrontier()
    a = ni('action.go_to_cart')
    assert f.push(a)
    assert not f.push(a)
    assert f.stats.skipped_duplicate == 1


def test_completed_canonical_prunes_pending_duplicates_and_blocks_future_pushes():
    f = IntentFrontier()
    n = SemanticNormalizer()
    first = n._from_spec(INTENTS['action.go_to_cart'], SOURCE_DOMAIN, None, 0.7, 'first')
    second = n._from_spec(INTENTS['action.go_to_cart'], SOURCE_DOMAIN, None, 0.7, 'second')
    # Force a distinct concrete identity to simulate rediscovery from a different source/element.
    second.selector_candidates = ['#some-other-cart-link']
    assert f.push(first)
    assert f.push(second)
    f.mark_completed(first)
    assert f.is_completed('action.go_to_cart')
    assert not f.pending_for_state(first.expected_state)
    third = n._from_spec(INTENTS['action.go_to_cart'], SOURCE_DOMAIN, None, 0.7, 'third')
    assert not f.push(third)
    assert f.stats.skipped_completed == 1


def test_pop_ignores_stale_completed_items():
    f = IntentFrontier()
    n = SemanticNormalizer()
    done = n._from_spec(INTENTS['action.go_to_cart'], SOURCE_DOMAIN, None, 0.7, 'done')
    f.stack.append(done)  # simulate an old queued item from before completion pruning existed
    f.seen.add(done.identity)
    f.completed_keys.add('action.go_to_cart')
    assert f.pop_for_state(done.expected_state) is None
    assert f.stats.skipped_stale_on_pop == 1
