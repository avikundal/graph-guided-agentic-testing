# A real run, explained

This is one actual run of the system, against
`https://www.amazon.in/dp/1847941834` (the book *Atomic Habits*), with the graph
and cart both reset first so it's a clean story. I've pulled out the parts that
matter and explained what each one is telling you, because the raw console output
is long and a bit overwhelming on its own.

The reason this run exists is to show the three things the assignment asks for:
what the agent **found by clicking around**, what the graph **reasoned out on its
own**, and — the important one — at least one scenario the agent **never tested but
the graph caught anyway**. If you only read one section, make it section 3.

A live run also drops this same information as machine-readable JSON at
`data/run_logs/latest_sample_output.json`, in case you'd rather diff it than read
it.

---

## Did the whole flow work end to end?

Yes. Here's the bottom line the run prints:

```
Add to Cart validated:                  true
Proceed to Checkout validated:          true
End-to-end checkout flow validated:     true
Cart provenance:                        cart_confirmation_or_cart_delta_verified
Forbidden final-purchase actions:       never clicked
```

So the agent went all the way from a product page to the secure-checkout boundary —
and, crucially, stopped there. It never clicked "Place Order." That line about
forbidden actions is the one I care about most: the system can drive a real
checkout without ever risking an actual purchase.

## 1. What the agent found by actually clicking

These are the things browser-use physically did, and that I then independently
verified (I don't trust its self-report — I re-read the real cart and checked the
numbers):

| What it did | Result | How I know it really happened |
|---|---|---|
| Add to Cart | **validated** | The item showed up in the cart |
| Change Quantity | **validated** | I re-read the cart: the count went from 1 → 2 |
| Proceed to Checkout | **validated** | The page actually reached secure checkout |

It also *noticed* a bunch of other controls without clicking them — a quantity
stepper, a subtotal, a "save for later", a "delete", a promo-code box. Noticing
matters, because that's the raw material the graph reasons over next.

## 2. What the graph reasoned out on its own

After the agent's done poking around, the graph looks at everything it saw and
works out which behaviours *ought* to be tested, whether or not the agent got to
them:

| The scenario the graph proposes | Why it proposed it |
|---|---|
| Changing quantity should recalculate the subtotal | It saw a cart item, a quantity control, and a subtotal together |
| Deleting an item should update the subtotal | It saw a cart item, a delete control, and a subtotal |
| "Save for later" should move an item out of the active cart | It saw a cart item and a save-for-later control |
| Address and payment live deeper inside checkout | It reached the checkout boundary |
| The final "place order" line must be detected and never crossed | The safety boundary itself |

None of these came from a human writing test cases. They fall out of the structure
of what was observed.

## 3. The one the agent missed (this is the whole point)

Take **"deleting an item should update the subtotal."**

The agent *saw* the delete button and *saw* the subtotal — but it never clicked
delete, because deleting is destructive and I keep destructive actions in
observe-only mode by default. So a pure crawler would just move on, and that
behaviour would go untested forever.

The graph doesn't move on. It reasons: *I have a cart item, a delete control, and a
subtotal all present, but I've never actually proven that deleting changes the
subtotal.* That's a genuine gap — a test that should exist and doesn't — and the
graph surfaces it as `INFERRED_MISSED`. This is precisely the difference between
"a crawler with a database" and the system the brief is asking for.

And here's the part I'm happiest about: the graph doesn't just *report* the gap, it
**acts on it**. For "changing quantity should recalculate subtotal," the graph
pushed that action back onto the agent's to-do list (you'll see `source=graph_inferred`
in the run), the agent went and did it, and it got validated. The graph literally
made the crawler test something it would otherwise have skipped.

## 4. The "graph impact" summary (printed at the end of every run)

I added a little scoreboard so the value is obvious at a glance instead of buried:

```
Graph impact (this run) — crawler alone vs. with graph:
  - Behaviors validated by the crawler alone:          3
  - Scenarios surfaced ONLY by graph reasoning:        +5  (3 coverage gaps + 2 boundary/safety)
  - Actions the graph pushed into exploration:         +1  (covered by crawler: 1)
  - Redundant re-executions the graph memory avoided:  62
  - Feature concept coverage:                          92.3%
  - Structural gaps the graph flagged:                 domain.final_order_boundary
  - Net: 3 directly-validated behaviors -> 8 documented + reasoned scenarios.
```

Read that as: the bare agent proved 3 behaviours; with the graph on top, you end up
with 8 documented scenarios, one of which the agent actively went and tested
*because the graph told it to*. The single "structural gap" it flags — the final
order boundary — is correct and is the safe answer: that's the line we deliberately
never cross.

## 5. Bonus: which tests a code change would put at risk

This is the optional PR-hook stretch. If a developer changes the cart subtotal code,
the system can trace through the graph and tell you exactly what's now in danger —
without re-running everything:

```
$ ./.venv/bin/python scripts/pr_blast_radius.py \
    --changed-concept domain.subtotal --changed-selector "select[name='quantity']"

Impacted concepts: action.change_quantity, domain.quantity_control, domain.subtotal
UI actions at risk:
  - action.change_quantity (mutating)
  - domain.quantity_control (observe-only)
  - domain.subtotal (observe-only)
Scenarios at risk:
  - scenario.quantity_updates_subtotal   (the agent already validated this)
  - scenario.delete_updates_subtotal     (this one the graph inferred)
```

So a one-line code change turns into a precise, bounded "here's what to re-test"
answer. That's the same graph doing a completely different job.
