"""Deny-list safety veto for an autonomous browser agent.

Design (agreed): the agent is free to discover and try ANY action — that is the
whole point of using a graph to surface scenarios nobody pre-conceived. An
allow-list would block every newly-discovered intent and defeat that purpose. So
safety is a *deny-list*: default-allow, and block only a short list of known-bad
actions before they execute.

Two things are blocked, and only two:
  1. Final payment — irreversible, so double-guarded by button text AND by the
     order-placement URL. This is the one line that must never be crossed.
  2. Off-product navigation — leaving to a *different* product or an external
     site. (A "stay on task" guard, not a money guard.)

The veto runs in the browser-use step callback, which fires after the LLM picks
an action but BEFORE it executes, so raising ``ForbiddenActionVeto`` prevents the
action from ever running.
"""
from __future__ import annotations

import re

from ..domain.checkout_contract import FORBIDDEN_TERMS


class ForbiddenActionVeto(Exception):
    """Raised in the step callback to stop a denied action before it executes."""


# 1) Final-payment button text (irreversible). Reuse the canonical forbidden
#    terms so there is a single source of truth: place order, pay now, buy now,
#    confirm/complete purchase, submit order.
_PAYMENT_TERMS = tuple(FORBIDDEN_TERMS)

# 1b) Order-placement / payment endpoints — the second lock on the money line.
_ORDER_URL_PATTERNS = (
    "/gp/buy/spc",          # Amazon single-page-checkout place-order handlers
    "/gp/buy/payselect",
    "/gp/buy/shipoptionselect",
    "/gp/buy/thankyou",
    "place-order", "placeorder", "place_your_order",
    "/checkout/p/", "/checkout/payment", "/payments/",
)

# Session-destroying account actions. Not payment, but they log the run out and
# derail everything — a known-bad action worth a deny-list entry.
_SESSION_TERMS = ("sign out", "signout", "log out", "logout", "switch account", "switch accounts")

# Navigation-style actions whose destination URL we can inspect before it runs.
_NAV_ACTIONS = {"navigate", "go_to_url", "open_tab", "new_tab"}

_ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})", re.I)
_HOST_RE = re.compile(r"^https?://([^/]+)", re.I)


def asin_from_url(url: str) -> str:
    m = _ASIN_RE.search(url or "")
    return m.group(1).upper() if m else ""


def host_of(url: str) -> str:
    m = _HOST_RE.match(url or "")
    return m.group(1).lower() if m else ""


def veto_reason(
    *,
    target_label: str,
    action_url: str,
    action_type: str,
    product_asin: str,
    base_host: str,
) -> str | None:
    """Return a short reason string if this action must be blocked, else None."""
    text = (target_label or "").lower()
    url = (action_url or "").lower()

    # 1) Final payment — text OR order-placement URL. Never crossed.
    if any(t in text for t in _PAYMENT_TERMS):
        return f"payment:text:{text[:40]}"
    if any(p in url for p in _ORDER_URL_PATTERNS):
        return f"payment:url:{url[:60]}"

    # 1c) Session-destroying account actions (sign out / switch account).
    if any(t in text for t in _SESSION_TERMS):
        return f"session:{text[:30]}"

    # 2) Off-product navigation (only checkable for navigation-style actions;
    #    click-driven cross-product moves are handled by the prompt + post-hoc
    #    state recovery).
    if action_type in _NAV_ACTIONS and url.startswith("http"):
        host = host_of(url)
        if base_host and host and host != base_host:
            return f"off_product:external:{host}"
        other = asin_from_url(url)
        if other and product_asin and other != product_asin:
            return f"off_product:other_asin:{other}"
    return None
