# A real run, explained

This is one actual run of the system, against
`https://www.amazon.com/dp/0307887898` (the book *The Lean Startup*), with the graph
and cart both reset first so it's a clean story. I've pulled out the parts that
matter and explained what each one is telling you, because the raw console output
is long. The full report is in `data/run_logs/latest_report.txt`, and the same
information is dropped as machine-readable JSON at
`data/run_logs/latest_sample_output.json`.

The reason this run exists is to show the three things the assignment asks for:
what the agent **found by clicking around**, what the graph **reasoned out on its
own**, and — the important one — at least one scenario the agent **never tested but
the graph caught and then went and tested anyway**. If you only read one section,
make it section 3.

---

## Did the whole flow work end to end?

Yes. Here's the bottom line the run prints:

```
Add to Cart validated:                  true
Proceed to Checkout validated:          true
End-to-end checkout flow validated:     true
Forbidden final-purchase actions:       never clicked
Feature concept coverage:               92.3%  (12 of 13 concepts)
```

So the system went all the way from a product page to the secure-checkout boundary —
and, crucially, stopped there. It never clicked "Place Order." The deny-list veto
blocks the money line before it can execute, so the system can drive a real checkout
without ever risking an actual purchase.

## 1. What the agent found by actually clicking

These are the things browser-use physically did during the free crawl, and that I
then independently verified (I don't trust its self-report — I re-read the real cart
and check the numbers). Eight behaviours, all on the item under test:

| What it did | Result |
|---|---|
| Add to Cart | **validated** (item appeared in the cart, delta verified) |
| Increase / Decrease Quantity | **validated** (the quantity stepper moved) |
| Save for Later | **validated** (item left the active cart) |
| Move to Cart | **validated** (item moved back) |
| Delete item | **validated** (line removed) |
| Gift option / promo code | **validated** (typed an invalid code, `INVALIDCOUPON123`) |

Notice what's **not** in that list: **Proceed to Checkout.** The free crawl explored
the cart controls and converged — without ever pushing through to checkout. Hold that
thought; it's the whole point of section 3.

## 2. What the graph reasoned out on its own

After the crawl converges, the graph reasons about what *should* be true but was
never verified. The reasoning is **causal**: the graph holds `X SHOULD_CAUSE Y`
expectations and flags the ones with no validating attempt. From this run:

| The scenario the graph surfaced | The causal gap it spotted |
|---|---|
| Validate Proceed to Checkout | `action.proceed_to_checkout` **SHOULD_CAUSE** `domain.checkout_boundary` — never proven |
| Validate Go to Cart | `action.go_to_cart` **SHOULD_CAUSE** `domain.cart_item` — never proven |
| Validate Subtotal | `action.change_quantity` **SHOULD_CAUSE** `domain.subtotal` — the subtotal effect was never checked |
| Test Inventory State | `action.delete_item` **SHOULD_CAUSE** `domain.inventory_state` — never checked |

None of these came from a human writing test cases — they fall out of the graph
structure plus the seeded causal expectations. Across two reasoning rounds the graph
surfaced **7** such scenarios.

## 3. The one the agent missed (this is the whole point)

Take **"Proceed to Checkout."**

The free crawl never validated it — it exercised the cart and stopped. A crawler with
a database would end there and quietly report a cart that was never checked out.

The graph doesn't stop there. It reasons: *I've observed `action.proceed_to_checkout`
and I know it SHOULD_CAUSE `domain.checkout_boundary`, but nothing ever proved that
transition.* So it surfaces the gap **and acts on it**: it navigates back to the cart,
issues a **directed probe** that clicks Proceed to Checkout, and browser-use lands on
the **real secure-checkout / sign-in boundary** (step 24: `domain.checkout_boundary;
checkout URL`). That graph-directed probe is exactly what flips **End-to-end checkout
flow validated → true**. The click is attributed to `source=graph_inferred`, because
it would never have happened without the graph choosing that experiment.

That is precisely the difference between "a crawler with a database" and the system
the brief asks for: the crawl finds what it stumbles into, and the graph reasons
about — and then *closes* — what the crawl missed.

## 4. The "graph impact" summary (printed at the end of every run)

A scoreboard so the value is obvious at a glance:

```
Graph impact (this run) — crawler alone vs. with graph:
  - Behaviors validated by the crawler alone:          8
  - Scenarios surfaced ONLY by graph reasoning:        +7  (7 coverage gaps)
  - Graph-directed probe clicks:                       4
  - Graph-directed probes covered:                     4
  - Feature concept coverage:                          92.3%
  - Structural gaps the graph flagged:                 domain.final_order_boundary
  - Net: 8 directly-validated behaviors -> 15 documented + reasoned scenarios.
```

Read that as: the bare agent proved 8 behaviours; with the graph on top you end up
with 15 documented scenarios — one of which (reaching checkout) the agent tested
*only because the graph told it to*. The single structural gap it flags —
`domain.final_order_boundary` — is correct and is the safe answer: that's the line we
deliberately never cross.

## 5. Bonus: which tests a code change would put at risk

This is the optional PR-hook stretch, run against the graph this crawl built. If a
developer touches the quantity/subtotal code, the system traverses
`Concept → Scenario` and tells you exactly what's now in danger — without re-running
everything:

```
$ ./.venv/bin/python scripts/pr_blast_radius.py --tenant-id default --project-id dyn_test \
    --feature amazon_checkout --changed-concept domain.subtotal \
    --changed-concept action.change_quantity --changed-selector "select[name='quantity']"

Impacted concepts (resolved): action.change_quantity, domain.quantity_control, domain.subtotal
UI elements / actions at risk (from the feature contract):
  - action.change_quantity (Change Quantity, risk=mutating_click)
  - domain.quantity_control (Quantity Control, risk=observe_only)
  - domain.subtotal (Subtotal, risk=observe_only)
Inferred scenarios at risk (graph reasoning rules):
  - scenario.quantity_updates_subtotal   (the agent already validated the action)
  - scenario.delete_updates_subtotal     (this one the graph inferred)
```

So a one-line code change turns into a precise, bounded "here's what to re-test"
answer. That's the same graph doing a completely different job.
