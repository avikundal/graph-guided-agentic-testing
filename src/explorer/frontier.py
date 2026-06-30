from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..domain.checkout_contract import (
    RISK_DESTRUCTIVE_CLICK,
    RISK_FORBIDDEN_CLICK,
    RISK_MUTATING_CLICK,
    RISK_OBSERVE_ONLY,
    STATE_CART,
    STATE_PRODUCT,
)
from .semantic_normalizer import NormalizedIntent

# The action that moves the explorer OUT of a state. Local affordances in a state
# (product options/variants, cart mutations) are explored first; the exit
# transition only fires once the local frontier is handled. This is what lets a
# product's size/colour options run before Add to Cart, and cart actions run
# before Proceed to Checkout — deep exploration before moving on.
_EXIT_TRANSITIONS: dict[str, frozenset[str]] = {
    STATE_PRODUCT: frozenset({"action.add_to_cart", "action.go_to_cart"}),
    STATE_CART: frozenset({"action.proceed_to_checkout"}),
}
_LOCAL_RISKS = {RISK_OBSERVE_ONLY, RISK_MUTATING_CLICK, RISK_DESTRUCTIVE_CLICK}

IntentStatus = Literal["NEW", "EXECUTING", "SUCCESS", "FAILED", "BLOCKED", "SKIPPED"]


@dataclass
class IntentMemoryRecord:
    """Run-scoped memory for a normalized frontier intent.

    `identity` tracks one concrete target, while `canonical_key` lets the
    explorer remember that an action such as Add to Cart or Go to Cart has
    already succeeded even if it is rediscovered later with a different UI
    element or source.
    """

    identity: str
    canonical_key: str
    expected_state: str
    human_label: str
    status: IntentStatus = "NEW"
    attempts: int = 0
    source: str = ""
    last_reason: str = ""


@dataclass
class FrontierStats:
    added: int = 0
    popped: int = 0
    executed: int = 0
    observed_only: int = 0
    blocked_forbidden: int = 0
    postponed_wrong_state: int = 0
    requires_replay: int = 0
    skipped_duplicate: int = 0
    replay_failed: int = 0
    # Phase 1 intent-memory accounting.
    skipped_completed: int = 0
    skipped_blocked: int = 0
    skipped_stale_on_pop: int = 0
    pruned_after_completion: int = 0
    marked_success: int = 0
    marked_failed: int = 0
    marked_blocked: int = 0


@dataclass
class IntentFrontier:
    """State-aware DFS stack with run-scoped execution memory.

    Phase 1 fix: once a canonical intent succeeds, all queued duplicates for
    that canonical key are pruned and future discoveries are ignored. This
    prevents the loop that repeatedly executes already-successful actions like
    Go to Cart, Add to Cart, or Change Quantity.
    """

    stack: list[NormalizedIntent] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)
    attempted: set[str] = field(default_factory=set)
    completed: set[str] = field(default_factory=set)
    blocked: set[str] = field(default_factory=set)
    completed_keys: set[str] = field(default_factory=set)
    blocked_identities: set[str] = field(default_factory=set)
    memory: dict[str, IntentMemoryRecord] = field(default_factory=dict)
    canonical_success: dict[str, IntentMemoryRecord] = field(default_factory=dict)
    stats: FrontierStats = field(default_factory=FrontierStats)

    def push_many(self, intents: list[NormalizedIntent]) -> list[NormalizedIntent]:
        added = []
        for i in intents:
            if self.push(i):
                added.append(i)
        return added

    def push(self, intent: NormalizedIntent) -> bool:
        if self.is_completed(intent.canonical_key):
            self.stats.skipped_completed += 1
            self._remember(intent, "SKIPPED", "canonical intent already succeeded")
            return False

        key = intent.identity
        if key in self.blocked_identities:
            self.stats.skipped_blocked += 1
            self._remember(intent, "SKIPPED", "same concrete target already blocked")
            return False

        if key in self.seen or key in self.attempted or key in self.completed or key in self.blocked:
            self.stats.skipped_duplicate += 1
            self._remember(intent, "SKIPPED", "duplicate proposal in this run")
            return False

        self.seen.add(key)
        self.memory[key] = IntentMemoryRecord(
            identity=key,
            canonical_key=intent.canonical_key,
            expected_state=intent.expected_state,
            human_label=intent.human_label,
            status="NEW",
            attempts=0,
            source=intent.source,
        )
        self.stack.append(intent)
        self.stats.added += 1
        return True

    def is_completed(self, canonical_key: str) -> bool:
        return canonical_key in self.completed_keys

    def status_for(self, canonical_key: str) -> str | None:
        record = self.canonical_success.get(canonical_key)
        if record:
            return record.status
        return None

    def mark_executing(self, intent: NormalizedIntent) -> None:
        record = self._record_for(intent)
        record.status = "EXECUTING"
        record.attempts += 1
        self.attempted.add(intent.identity)

    def mark_completed(self, intent: NormalizedIntent, reason: str = "validated") -> None:
        self.completed.add(intent.identity)
        self.completed_keys.add(intent.canonical_key)
        record = self._record_for(intent)
        record.status = "SUCCESS"
        record.last_reason = reason
        self.canonical_success[intent.canonical_key] = record
        self.stats.marked_success += 1
        self._prune_completed_key(intent.canonical_key)

    def mark_failed(self, intent: NormalizedIntent, reason: str = "failed") -> None:
        record = self._record_for(intent)
        record.status = "FAILED"
        record.last_reason = reason
        self.blocked.add(intent.identity)
        self.blocked_identities.add(intent.identity)
        self.stats.marked_failed += 1

    def mark_blocked(self, intent: NormalizedIntent, reason: str = "blocked") -> None:
        record = self._record_for(intent)
        record.status = "BLOCKED"
        record.last_reason = reason
        self.blocked.add(intent.identity)
        self.blocked_identities.add(intent.identity)
        self.stats.marked_blocked += 1
        # Do not globally block the canonical key: the same intent may become
        # valid after replay/state change or with a different UI affordance.

    def pop_for_state(self, state: str) -> NormalizedIntent | None:
        self._drop_stale_stack_items()
        candidates = [i for i in self.stack if i.expected_state == state and not self.is_completed(i.canonical_key)]
        if not candidates:
            return None
        # Same-state local exploration must win over the exit transition: explore
        # the product's options before Add to Cart, and the cart's actions before
        # Proceed to Checkout. The exit fires only once the local frontier is done.
        exits = _EXIT_TRANSITIONS.get(state, frozenset())
        if exits:
            local = [
                i for i in candidates
                if i.canonical_key not in exits and i.risk in _LOCAL_RISKS
            ]
            if local:
                candidates = local
        candidates.sort(key=lambda i: self._score_for_state(i, state), reverse=True)
        chosen = candidates[0]
        self.stack.remove(chosen)
        self.mark_executing(chosen)
        self.stats.popped += 1
        return chosen

    def pop_any(self) -> NormalizedIntent | None:
        self._drop_stale_stack_items()
        if not self.stack:
            return None
        self.stack.sort(key=lambda i: self._score_for_state(i, i.expected_state), reverse=True)
        chosen = self.stack.pop(0)
        self.mark_executing(chosen)
        self.stats.popped += 1
        return chosen

    def has_state_items(self, state: str) -> bool:
        self._drop_stale_stack_items()
        return any(i.expected_state == state for i in self.stack)

    def pending_for_state(self, state: str) -> list[NormalizedIntent]:
        self._drop_stale_stack_items()
        return [i for i in self.stack if i.expected_state == state]

    def state_signature(self, state: str) -> tuple[str, ...]:
        self._drop_stale_stack_items()
        return tuple(sorted(i.identity for i in self.stack if i.expected_state == state))

    def memory_summary(self) -> dict[str, int]:
        counts = {"NEW": 0, "EXECUTING": 0, "SUCCESS": 0, "FAILED": 0, "BLOCKED": 0, "SKIPPED": 0}
        for rec in self.memory.values():
            counts[rec.status] = counts.get(rec.status, 0) + 1
        return counts

    def _score_for_state(self, intent: NormalizedIntent, current_state: str) -> float:
        score = intent.priority
        if self.is_completed(intent.canonical_key):
            return -999.0
        if intent.expected_state == current_state:
            score += 0.40
        if intent.risk == RISK_OBSERVE_ONLY:
            score += 0.35
        elif intent.risk == RISK_MUTATING_CLICK:
            score += 0.12
        elif intent.risk == RISK_DESTRUCTIVE_CLICK:
            score -= 0.10
        elif intent.risk == RISK_FORBIDDEN_CLICK:
            score -= 0.35
        # Keep local exploration ahead of the exit transition (options before Add
        # to Cart, cart actions before Proceed to Checkout).
        exits = _EXIT_TRANSITIONS.get(current_state, frozenset())
        if intent.canonical_key in exits:
            local_pending = [
                i for i in self.stack
                if i.expected_state == current_state
                and i.canonical_key not in exits
                and not self.is_completed(i.canonical_key)
                and i.risk in _LOCAL_RISKS
            ]
            if local_pending:
                score -= 1.00
        return score

    def _remember(self, intent: NormalizedIntent, status: IntentStatus, reason: str) -> None:
        rec = self.memory.get(intent.identity)
        if rec is None:
            rec = IntentMemoryRecord(
                identity=intent.identity,
                canonical_key=intent.canonical_key,
                expected_state=intent.expected_state,
                human_label=intent.human_label,
                status=status,
                attempts=0,
                source=intent.source,
                last_reason=reason,
            )
            self.memory[intent.identity] = rec
        else:
            rec.status = status
            rec.last_reason = reason

    def _record_for(self, intent: NormalizedIntent) -> IntentMemoryRecord:
        rec = self.memory.get(intent.identity)
        if rec is None:
            rec = IntentMemoryRecord(
                identity=intent.identity,
                canonical_key=intent.canonical_key,
                expected_state=intent.expected_state,
                human_label=intent.human_label,
                status="NEW",
                attempts=0,
                source=intent.source,
            )
            self.memory[intent.identity] = rec
        return rec

    def _prune_completed_key(self, canonical_key: str) -> None:
        before = len(self.stack)
        self.stack = [i for i in self.stack if i.canonical_key != canonical_key]
        self.stats.pruned_after_completion += before - len(self.stack)

    def _drop_stale_stack_items(self) -> None:
        before = len(self.stack)
        self.stack = [
            i for i in self.stack
            if not self.is_completed(i.canonical_key)
            and i.identity not in self.blocked_identities
        ]
        self.stats.skipped_stale_on_pop += before - len(self.stack)
