# Graph-guided agentic testing — Amazon checkout

This is my submission for the Testsigma AI Architect take-home. The short version:
I built a small system where a browser agent wanders through Amazon's checkout
flow like a curious user, everything it sees gets written into a Neo4j knowledge
graph, and then the graph *thinks about what the agent forgot to try* — and hands
those gaps back to the agent so it actually goes and tests them.

That last bit is the whole point. A browser agent on its own is a guesser: it pokes
at whatever it happens to notice. A graph is the opposite — it's structured, so it
can reason about what *should* be there even when the agent never looked. Stitching
those two together is what the assignment was really asking for, and it's where I
spent most of my time.

> I modeled **one** feature deeply — Amazon checkout (product page → cart →
> checkout boundary) — rather than a hundred features shallowly. That was a
> deliberate call, and it's the constraint the brief asks for.

---

## What's in here (the deliverables)

| Part | What it is | Where to look |
|---|---|---|
| **A — the working prototype** | The actual runnable loop: crawl → graph → reason | this repo (`src/`, `scripts/`); how to run it is below |
| A — how the graph is built | Schema, why I shaped it this way, the reasoning query | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| A — sample output | A real run, annotated: what the agent found, what the graph inferred, and the one scenario the agent **missed** but the graph caught | [docs/SAMPLE_OUTPUT.md](docs/SAMPLE_OUTPUT.md) |
| A — PR blast radius (the optional stretch) | "If this code changes, which tests are at risk?" | `scripts/pr_blast_radius.py` |
| **B — the architecture doc** | How this toy becomes real infrastructure for 100+ customers | **[PDF](docs/Part_B_Production_Architecture.pdf)** 

There's a Loom walkthrough in the submission email too.

---

## Why I picked Amazon checkout

I wanted a feature that would actually fight back. Checkout is perfect for that:
it's a real, messy, JavaScript-heavy flow with a hard line you must never cross —
you can explore the cart all day, but you must *never* actually place an order.
That single constraint forces the system to be careful in a way a friendlier demo
wouldn't. It also has a few behaviours that are easy to walk past but matter a lot
(does changing the quantity update the subtotal? does deleting an item?), which is
exactly the kind of thing I wanted the graph to catch.

## How the whole thing actually works

When you run it, here's the story that plays out, step by step:

1. **The crawler explores freely under a hard veto.** I use
   [browser-use](https://github.com/browser-use/browser-use) as the hands. It can
   try product options, cart controls, coupon/offer affordances, save-for-later and
   delete/remove actions, but a deterministic veto blocks final payment, account
   switches, repeat actions, and leaving the product under test.
2. **The crawler stops on action-level convergence.** It does not stop just because
   one canonical concept was seen. It keeps going until no new concepts, no new
   clicked labels, and no new validated concepts appear across repeated bursts.
3. **We write down everything it saw.** A "page observer" turns the raw page into
   typed facts — what state are we in (product? cart? checkout?), what controls are
   visible, what concepts exist (a subtotal, a quantity stepper, a delete button).
   All of it lands in Neo4j.
4. **The graph reasons about the gaps.** This is the interesting part. A Cypher
   query looks at the graph and asks: "Have I seen a cart item, a quantity control,
   and a subtotal — but never actually *proven* that changing the quantity moves the
   subtotal?" If so, that's a real test the agent skipped, and the graph surfaces it.
5. **The graph hands those gaps back as targeted probes.** Browser-use executes
   those probes on the right page, and the report attributes those clicks to the
   graph when they fulfill a surfaced concept. The graph isn't just a database at
   the end of the run; it actively steers the second pass.

The thing I kept reminding myself: **the browser agent is allowed to be wrong.**
It'll cheerfully tell you "I added it to the cart!" when it actually didn't. So I
never take its word for anything that matters — I re-read the real cart page and
check the numbers myself before I call something validated. That distrust is on
purpose, and it's wired through the whole codebase.

### Who's deterministic and who's the LLM (and why I split it that way)

| Job | Who does it | My reasoning |
|---|---|---|
| Free exploration and fuzzy clicking | **The LLM (browser-use)** | This is the genuinely hard, page-specific part. |
| Safety veto, provenance, graph writes | **Plain code** | Safety and reproducibility can't depend on a model's mood. |
| Structural missed-scenario inference | **Plain code (Cypher / fallback rules)** | The graph's value is that it remembers what was observed and proven. |
| Gap expansion after crawl convergence | **LLM-over-graph, with deterministic fallback** | Used after the crawler exhausts itself, to propose targeted probes. If the LLM is unavailable or returns a bad response, deterministic graph-derived probes keep the loop working. |

## A few things that were genuinely hard

I'm including these because they're the real story of building this, and because
they're the bugs that taught me what the system actually needed:

- **The agent kept "succeeding" at things that failed.** browser-use would report
  a quantity change as a failure (it couldn't see Amazon's cart re-render in its
  tiny observation window) when the quantity *had* actually changed. I fixed this by
  re-reading the canonical cart page myself and comparing the item count before and
  after — believing the numbers, not the narrator.
- **The crawl browser wasn't actually logged in.** Amazon's session cookies have a
  newer `partitionKey` field that browser-use's loader choked on, silently dropping
  the *entire* login. The cart worked anonymously but checkout bounced to sign-in.
  Took me a while to spot because nothing errored loudly. The fix sanitizes the
  cookies before handing them over.
- **It tested the wrong country's cart.** When I tried an `amazon.in` product, the
  cart URL was hardcoded to `amazon.com`, so the item went into the Indian cart
  while the code kept reading the (empty) US cart. Now the cart/checkout domain
  follows the product URL.
- **It nearly bought four copies of a book.** Early on, because a mutating action
  was never marked "done," the planner kept re-discovering and re-clicking "increase
  quantity" until the cart had four items. Run-scoped memory fixed that.

None of these are in the final code as scars — they're fixed — but they shaped
every safety and validation decision in here.

---

## Running it yourself

### Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env          # then fill in Neo4j + OpenAI
```

### Log in once

Amazon needs a real human login (OTP, CAPTCHA, the works), so I do it manually in a
real browser window once and save the session:

```bash
./.venv/bin/python scripts/login_amazon.py        # logs in on amazon.com by default
./.venv/bin/python scripts/verify_login.py
```

> **One gotcha worth knowing:** cart and checkout happen on the *same* Amazon
> marketplace as the product. If you want to test an `amazon.in` product, log in
> there first: `scripts/login_amazon.py --url https://www.amazon.in/`. If your saved
> session is for a different domain than the product, the run stops early and tells
> you, instead of quietly testing an empty cart.

### Run a crawl

```bash
./.venv/bin/python scripts/crawl.py \
  --reset-graph --reset-cart \
  --url https://www.amazon.com/dp/0307887898 \
  --tenant-id default --project-id amazon_demo --feature-key amazon_checkout \
  --enable-living-graph --debug
```

`--headed` lets you watch the browser do its thing. `--reset-cart` empties the cart
first so the "what did *this* run add?" check stays honest. The very first line of
output tells you which URL it's crawling — if that looks wrong, your terminal
probably mangled the command, so re-run it on a single line.

Every run also drops a full report and a structured JSON into `data/run_logs/`
(`latest_report.txt`, `latest_sample_output.json`), so you don't have to scroll the
console to find the result.

### Example products to try

Any public `/dp/<ASIN>` URL works. Give each product its own `--project-id` so their
graphs don't overwrite each other, and **paste each command on one line** (the
multi-line version with `\` breaks if your terminal slips a blank line in between):

```bash
# US book
./.venv/bin/python scripts/crawl.py --reset-graph --reset-cart --url "https://www.amazon.com/dp/0307887898" --tenant-id default --project-id us_book --feature-key amazon_checkout --enable-living-graph --debug

# India book
./.venv/bin/python scripts/crawl.py --reset-graph --reset-cart --url "https://www.amazon.in/dp/1847941834" --tenant-id default --project-id in_book --feature-key amazon_checkout --enable-living-graph --debug

# India electronics (a laptop, etc.)
./.venv/bin/python scripts/crawl.py --reset-graph --reset-cart --url "https://www.amazon.in/dp/B0DT74FF9P" --tenant-id default --project-id in_laptop --feature-key amazon_checkout --enable-living-graph --debug
```

Reusable template — change the two values and keep it on one line:

```bash
URL="https://www.amazon.in/dp/XXXXXXXXXX"; PROJ="in_test"; ./.venv/bin/python scripts/crawl.py --reset-graph --reset-cart --url "$URL" --tenant-id default --project-id "$PROJ" --feature-key amazon_checkout --enable-living-graph --debug
```

A small heads-up: pick products that are **in stock with a normal Add to Cart
button**. Some big-ticket items are "Buy Now only" (no cart), and if you hit one,
Add to Cart will correctly fail — that's the system being honest, not a bug. Books
and small electronics accessories are the safest bets. A good run ends with
`End-to-end checkout flow validated: true` and the forbidden purchase buttons never
touched.

### Look at the graph

```bash
./.venv/bin/python scripts/inspect_graph.py \
  --tenant-id default --project-id amazon_demo --feature amazon_checkout
```

### The PR blast-radius stretch

This answers "a developer just changed some code — which of our tests are now at
risk?" Point it at the selectors or concepts a PR touches and it traces the graph
from code → UI element → concept → scenario:

```bash
./.venv/bin/python scripts/pr_blast_radius.py --changed-selector "#add-to-cart-button"
./.venv/bin/python scripts/pr_blast_radius.py --changed-concept domain.subtotal
./.venv/bin/python scripts/pr_blast_radius.py --diff my_pr.diff
```

---

## What a good run looks like

The full annotated walkthrough is in [docs/SAMPLE_OUTPUT.md](docs/SAMPLE_OUTPUT.md),
but the headline is: Add to Cart, Change Quantity, and Proceed to Checkout all get
**validated**, the run reaches the secure-checkout boundary without ever clicking a
purchase button, and the report ends with a little "Graph impact" summary showing
how many scenarios the graph reasoned out beyond what the agent directly clicked —
including at least one the agent never tried at all.

## How the code is laid out

```text
src/
  config.py                     # env + paths
  domain/
    amazon_auth.py              # login/session + cart reset
    checkout_contract.py        # the "rules": intents, risk levels, states, inference rules
  explorer/
    graph_guided_explorer.py    # the conductor: runs the loop, does the reasoning
    browser_use_executor.py     # the thin layer that talks to browser-use
    page_observer.py            # turns a raw page into typed facts
    semantic_normalizer.py      # maps directed restore/probe intents when needed
    graph_expansion.py          # graph/LLM missed-scenario probes after crawl convergence
  graph/
    store.py                    # all the Neo4j reads/writes and the reasoning queries
    blast_radius.py             # the PR-impact logic
  reporting/report.py           # the human-readable run report
scripts/                        # login, crawl, inspect, blast-radius, build-the-PDF
tests/                          # 61 unit tests (no browser/network/Neo4j needed)
docs/                           # architecture notes, sample output, Part B PDF
```

## Tests

```bash
./.venv/bin/python -m compileall -q src scripts tests
./.venv/bin/python -m pytest -q
```

I kept the tests able to run with no browser, no network, and no Neo4j — they
exercise the deterministic brain (the planner, the risk gates, the inference rules,
the provenance parsing, the blast radius), which is the part I most want to be sure
stays correct.

## What I'd be honest about (limitations)

A few things are deliberately prototype-grade, and I'd rather call them out than
pretend otherwise:

- There are some **Amazon-specific hacks** in the core (handling their `smart-wagon`
  cart, parsing the subtotal). In a real product these belong in a per-app adapter,
  not the shared brain.
- The **"living graph" is read-only** right now. It can tell you which expected
  things haven't been confirmed lately, but it doesn't yet automatically re-queue
  them across runs. The hooks are there; wiring it up is the obvious next step (and
  I talk about it in Part B).
- Every step writes to Neo4j immediately. Fine for one feature; for a hundred
  customers you'd batch and invalidate instead. Also a Part B topic.

## A note on secrets

Your `.env` (OpenAI + Neo4j credentials) and the `data/` folder (your saved Amazon
session, screenshots of your logged-in account) are git-ignored on purpose and must
never be committed. If you cloned this from a working machine that had real
credentials sitting in `.env`, rotate them.
