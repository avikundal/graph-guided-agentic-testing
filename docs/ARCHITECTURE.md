# How the prototype is put together

This is the "why did you build it this way" doc for Part A. The README tells you
how to run it; this one explains the decisions underneath. I've tried to keep it
plain, because the design choices are honestly more interesting than the code.

## The one idea everything hangs off

A browser agent and a knowledge graph have opposite strengths, and I wanted each to
do only what it's good at.

The browser agent is great at the fuzzy, human part: "look at this page and click
the thing that adds it to the cart." It's terrible at being reliable — it'll
confidently tell you it succeeded when it didn't, and it has no memory of what it's
already tried.

The graph is the mirror image. It's hopeless at clicking anything, but it's
perfect at structure and memory: it can hold "here is everything we've ever seen
about checkout" and reason over it.

So the entire design is just: **let the LLM do the messy perception and clicking,
and let plain deterministic code do the planning, the safety, the validation, and
the reasoning.** Once I committed to that split, most of the hard questions answered
themselves.

## Who does what

There's no single big "agent." There's a conductor and a handful of small,
single-purpose pieces, each with a boundary it isn't allowed to cross:

- **The planner** (the DFS frontier) decides what to test next. It never clicks
  anything — it just keeps an ordered to-do list and hands one item at a time to
  the executor.
- **The executor** (the browser-use wrapper) performs exactly one UI action and
  reports back. It's deliberately thin and dumb: it gets one instruction, does it,
  and stops. It never writes to the graph.
- **The observer** turns a raw web page into typed facts — what state we're in, what
  controls are visible, what concepts are present.
- **The validator** is the skeptic. Before anything is allowed to count as
  "validated," it re-checks from independent evidence. The executor saying "done"
  is just a rumour until the validator confirms it.
- **The reasoner** is the Cypher query that finds missed and absent scenarios.
- **The graph store** does all the Neo4j reads and writes.

The boundary I care about most is between the executor and the validator. The
executor is allowed to be wrong; the validator's whole job is to not believe it.
For a quantity change, that means actually re-reading the cart and checking the
item count moved — not trusting the model's summary, which is often wrong about
exactly this.

## The graph schema, and why it's shaped like this

The textbook hierarchy for UI testing is `Element → Component → Flow → Feature`.
It's reasonable vocabulary, but I didn't use it as my backbone, because it's not
what the platform actually needs to *ask*. The questions I care about are: what did
we observe, what did we actually prove, what should exist but doesn't, and which
scenarios depend on which pieces. So I built the graph around those.

**The node types:**

| Node | What it represents |
|---|---|
| `Feature` / `Run` | The thing under test, and one exploration session |
| `Observation` | A single snapshot of a page the agent saw |
| `PageState` | A canonical UI state (product page, cart, checkout…) |
| `Concept` | The real unit of meaning: an affordance or behaviour (`action.add_to_cart`, `domain.subtotal`). This is the spine of the graph. |
| `Intent` | A concrete attempt to exercise a concept, with its outcome |
| `Scenario` | A behaviour worth testing — discovered, inferred-as-missed, or a safety boundary |

The single most important choice: **the unit of meaning is a `Concept` — a
behaviour — not a DOM element.** Elements (and their CSS selectors) are the least
stable thing in the whole system; they change every time Amazon ships a redesign.
If I'd modeled the graph around elements, it would rot constantly. By modeling
around *what a control means* ("this is the add-to-cart capability") rather than
*how to find it* (`#some-id`), the graph stays meaningful across redesigns.

Every node is also tagged with `tenant_id / project_id / feature_key`, which is the
seed of multi-tenancy — even in this prototype, every query is scoped, so two
different products or customers never bleed into each other.

## Modeling "absence" — the thing that's easy to skip

Most of a graph is about what *is* there. But for a testing tool, what *isn't*
there is often the real signal: "we expected a promo-code field and never saw one,"
or "delete was here last week and vanished after a deploy."

So before the crawl even starts, I seed the graph with every concept the feature is
*supposed* to have, marked `expected = true`. Then absence becomes a one-line query
instead of a guess:

- **Structurally absent** — expected, but never observed at all.
- **Behaviourally absent** — observed, but never actually validated. (This is what
  the reasoner surfaces as a "missed scenario.")

That second kind is the whole game. "We saw the delete button and the subtotal, but
never proved that deleting changes the subtotal" is a behavioural absence, and it's
a genuinely useful test the agent would never have written for itself.

## The reasoning query, in plain English

The reasoning rules live as *data*, not code — each one says "here are the concepts
that need to be present, and here's the action whose success would prove this
behaviour." The query then asks the graph: for each rule, were all the prerequisite
concepts actually observed, but the proving action never validated? If so, that's a
missed scenario.

Because this is a deterministic database query and not the LLM, it can't make things
up. The only way it can be wrong is if a *rule* is wrong — which is a much smaller,
more controllable surface than trusting a model to invent scenarios on the fly. (In
Part B I talk about how you'd evaluate and promote those rules at scale.)

And the loop closes: the actionable missed scenarios get pushed back onto the
planner's to-do list, so the agent actually goes and runs them. The graph isn't a
report you read at the end — it steers the next thing the crawler does.

## Where this is honestly still a prototype

A few seams I left rough on purpose, because the brief is "one feature deeply," not
"production-hardened":

- Some Amazon-specific handling (their dynamic cart page, subtotal parsing) sits in
  the core where, in a real product, it'd be a per-app plugin.
- The graph is recomputed simply and written to on every step. That's fine for one
  feature and completely wrong for a hundred customers — which is exactly the kind
  of thing Part B is about.

Those rough edges are deliberate handoff points to the production design, not
things I overlooked.
