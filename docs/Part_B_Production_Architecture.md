# Part B — Production Architecture

*How the little Amazon-checkout prototype becomes infrastructure that runs for 100+
customers, eighteen months in, against apps that change every sprint.*

This is a document I would defend to a founding team, not a textbook chapter. It is
opinionated, it shows the trade-offs, and it names the things I would refuse to ship.
Everything here has a working seed in Part A — §11 maps each production claim back to
the function that already does a small version of it.

---

## 0 · The short version

The prototype is two engines pointed at one feature, and the production plan is
mostly "keep that division of labour and harden it."

- **Engine 1 — the free crawler.** A browser agent (browser-use) explores Amazon
  checkout *autonomously*. It is not handed a catalogue of actions to perform; it
  pokes at whatever it notices — product options, the quantity stepper, delete,
  save-for-later, coupons, proceed-to-checkout — and we write down everything it
  touches. It is a **guesser**: it finds what it stumbles into.
- **Engine 2 — the graph that reasons about the gaps.** Once the crawl stops finding
  new behaviour, an LLM reads the Neo4j graph — what was *observed*, what was
  *validated*, what was *expected and never seen* — and proposes the scenarios the
  crawl skipped. Those proposals are then handed back to the browser agent as
  **targeted probes**, and a deterministic Cypher layer keeps the whole thing honest.

The one belief the architecture rests on: **the crawler is a probabilistic discovery
device, and the graph is the structural memory that tells you what discovery missed.**
Neither is trustworthy alone. The crawler hallucinates success; the graph can only
reason about structure it has been taught. The value is in the loop between them.

The production failure mode I worry about most is *not* the agent missing a button —
you can always crawl again. It is the system **silently believing something false**:
"checkout works" when the click never landed, or "the promo capability is gone" when
the run just wandered. So the architecture is built to make confident-wrong states
*expensive to reach* and *cheap to detect*.

> **Decision.** Treat executor output as *evidence*, never *truth*. Every
> "clicked" must be re-observed and asserted before it becomes "validated."
> **Trade-off.** More observation steps, slightly higher cost per crawl.
> **Refusal line.** I will not let an LLM's own self-report mark an action validated.

Three things break this loop the moment you leave the demo, and they organise the
rest of the document: **safety at scale** (§1, §9), **a graph that stays correct over
time** (§2, §3), and **knowing any of it is right when both layers are probabilistic**
(§4), all under a **cost ceiling** (§5) and **hard tenant isolation** (§6).

---

## 1 · Agent decomposition and boundaries

The biggest call I made is to **split responsibilities into small services instead of
building one clever agent.** A single mega-agent that decides what to test, clicks it,
judges whether it worked, and writes the result is impossible to trust, debug, or
bound on cost — every failure is entangled with every other.

| Service | Owns | LLM? | The boundary I enforce |
|---|---|---|---|
| **Free crawler** (Engine 1) | Autonomous exploration: which control to try next | **Yes** (small model) | Discovers and executes; it **never writes graph truth** and never decides what "passed." |
| **Safety veto** | The deny-list, checked before *every* action | **No** | Runs in the agent's step callback *before* execution. A planning or model bug can never bypass it. |
| **Observer** | Page snapshot → state, visible controls, concepts, raw artifacts | Mostly no | A small classifier is fine, but it must hand back the **raw evidence** (DOM, screenshot, URL). |
| **Ingestor** | Idempotent graph writes: provenance, confidence, artifact refs | **No** | No model calls. Every write is typed, attributed, and replayable. |
| **Graph reasoner** (Engine 2) | Missed / absent scenarios from graph structure | **LLM proposes, Cypher decides** | The trustworthy floor is deterministic; the LLM only *widens* the candidate set. |
| **Probe director** | Turns a surfaced scenario into a narrow browser probe, on the right page | No | Navigates to the concept's home state, then asks Engine 1 to execute one intent. |
| **Validator** | Deterministic post-conditions after an action | **No** | Required before "executed" may become "validated." Cannot be satisfied by model prose. |

The boundary I care about most: **the crawler is allowed to *say* "I clicked Proceed
to Checkout," but only the validator, re-observing the page, is allowed to *believe*
it.** That single split is what keeps a probabilistic agent from writing false history
into the graph.

I keep **safety as its own gate**, structurally separate from exploration, for the same
reason banks separate the person who approves a payment from the person who requests
it. In the prototype this is `safety_guard.veto_reason`, evaluated inside browser-use's
step callback — which fires *after* the model picks an action but *before* the action
executes. A raised veto stops the action from ever running.

### 1.1 · Why a deny-list, not an allow-list

This is the design decision I most want to defend, because it is the opposite of the
obvious one.

The tempting choice is an **allow-list**: enumerate the safe actions, permit only
those. It is safe, and it is wrong for *this* system. The entire reason to put a graph
behind the crawler is to surface scenarios **nobody pre-conceived**. An allow-list can
only ever permit actions someone already thought of — so it would block every newly
discovered or graph-inferred intent and quietly defeat the product. A guardrail that
only lets through what you already enumerated cannot guard a system whose job is to
find the things you did not enumerate.

So safety is a **deny-list**: default-allow, and block a short, *enumerable* set of
known-bad actions before they execute. The trick is that the genuinely dangerous
actions are exactly the ones you *can* enumerate, because they are irreversible or
identity-level:

| Deny-list rule (prototype) | What it blocks | Why it is enumerable |
|---|---|---|
| `payment:text` / `payment:url` | Place order, Pay now, Buy now, order/payment endpoints | The money line is a finite, known set. |
| `session:*` | Sign out, switch account | Identity-destroying; small and known. |
| `off_product:other_item` / `:other_asin` / `:external` | Wandering onto a different product or site | The product under test is known; everything else is off-scope. |
| `off_product:cart_recommendation_add` | Adding a *recommended* item from the cart page | On the cart page, any "add to cart" is a different item. |
| `cart_scope:irrelevant_action` | Sponsored tiles / recommendation rails on the cart page | Cart pages have effectively infinite recommendation labels. |
| `repeat:already_done` | Re-running an action already executed this run | Pure waste; bounded by what's been done. |

Everything *reversible* — quantity, delete, save-for-later, promo, gift options — is
fair game, because a mistake there is cheap and the validator + graph catch it. The
deny-list's honest weakness (it cannot block an unknown-bad action it never enumerated)
is bounded precisely because the unknown-bad actions that actually matter are
irreversible, and irreversible actions on a checkout flow are a *short, known list*.
I return to this, and how I would harden it, in §9.

### 1.2 · The two runtime contracts

Engine 1 and Engine 2 hand work to the browser through two different contracts:

- **Free-crawl envelope** (Engine 1's day job): a goal ("explore this cart"), an
  expected state, and the deny-list. Deliberately loose — looseness is where discovery
  comes from. The only hard constraints are the veto and a **no-repeat / action-level
  convergence** rule so the crawl can't loop forever or chase recommendation junk.
- **Graph-probe contract** (Engine 2 → probe director → Engine 1): a specific
  surfaced concept, the **home state** it lives in (so we navigate to the cart before
  probing a cart behaviour, not hunt for it on a product page), a positive target, and
  success evidence. Tight, because here we are *verifying a hypothesis*, not exploring.

The contract fields that earn their place: `expected_state` (stops the agent hunting
for cart controls on a checkout page), `success_evidence` (keeps "clicked" and
"validated" as separate ideas), and `risk` (drives the safety and replay policy).

---

## 2 · The production graph schema

The obvious thing to reach for is the textbook hierarchy — Element → Component → Flow →
Feature. I would **not** ship that as the spine. It models the UI's shape but not the
two things this product actually sells: **provenance** (why do we believe this?) and
**absence** (what should exist but doesn't?). The schema below is organised around the
queries we must answer, not around the DOM tree.

### 2.1 · Node types

| Node | Key properties | A query it answers |
|---|---|---|
| **Tenant / App / Feature** | `tenant_id`, `app_id`, `feature_key` | Everything is tenant/app/feature scoped; one feature modeled deeply. |
| **Run** | `run_id`, `commit_sha`, `started_at`, `model_version`, `prompt_version`, `cost` | What was known at run N vs N+1; canary and rollback analysis. |
| **Observation** | `state`, `url`, `artifact_ref`, `screenshot_ref`, `step` | Replay and audit exactly what the browser saw. |
| **Concept** | `key`, `kind`, `expected`, `observed`, `executed`, `validated`, `confidence`, `first_seen`, `last_seen` | Expected-not-observed; observed-not-validated; stale concepts. |
| **Intent** | `source`, `status`, `risk`, `selector_ref`, `evidence`, `confidence` | Why an action ran, failed, or was vetoed — and *who* drove it (crawler vs graph). |
| **Scenario** | feature-scoped `key`, `status`, `kind`, `confidence`, `last_confirmed_run` | Which scenarios are trusted right now versus decayed. |
| **Selector** | `hash`, `css/xpath/role`, `quality`, `stability`, `last_failed` | PR blast radius and self-healing. |
| **CodeArtifact** | `path`, `symbol`, `commit_sha` | Map a PR change to selectors, concepts, and scenarios. |

### 2.2 · Edges

The edges are the product. The ones that carry weight:

- `Run -[:OBSERVED]-> Observation -[:EVIDENCES]-> Concept` — provenance for every
  fact, traceable back to a screenshot.
- `Intent -[:TARGETS]-> Concept` and `Intent -[:USED]-> Selector` — *why* an action
  ran and *how* it found its target. Intent carries `source` so a graph-directed probe
  is permanently distinguishable from a crawler stumble.
- `Scenario -[:CONFIRMED_BY]-> Run` — the spine of the living graph (§3). A scenario's
  trust is a function of *which runs* still confirm it.
- `CodeArtifact -[:BACKS]-> Selector -[:EXERCISES]-> Concept -[:COVERED_BY]-> Scenario`
  — the blast-radius traversal (§8), top to bottom.

### 2.3 · Three changes from the prototype, each earning its keep

1. **Scenario becomes feature-scoped, not run-scoped**, with `CONFIRMED_BY` edges back
   to the runs that proved it. This is what lets confidence decay and lets a scenario
   survive (or expire) across runs.
2. **Selector becomes a first-class node** (the prototype keeps it as a property on the
   intent). You cannot do PR blast radius or self-healing if the locator is buried
   inside an intent.
3. **`commit_sha` and time live on everything.** That turns "show me the concepts that
   existed at commit X but not at HEAD" into a single query, which is the regression
   half of absence modeling.

### 2.4 · Indexes, constraints, and what does *not* belong in Neo4j

Uniqueness constraints on `(tenant_id, app_id, feature_key, concept.key)` and on
`scenario.key`; range indexes on `last_seen` and `commit_sha` for the temporal
queries; an index on `selector.hash` for blast radius. The **DOM and screenshot blobs
do not belong in Neo4j** — `Observation.artifact_ref` points at object storage (S3/GCS).
The graph stores structure and references; the evidence store holds the heavy bytes.

### 2.5 · Modeling absence — the part most designs skip

Absence is not "missing data." For a testing platform it is often *the product itself*:
the most valuable thing the graph can tell you is what **should** be there and isn't.

| Type | Definition | Example |
|---|---|---|
| **Structural** | `expected ∧ ¬observed` | The expected checkout boundary was never reached. |
| **Behavioural** | `observed ∧ ¬validated` | The quantity control exists, but the subtotal update was never *proven*. |
| **Regression** | `last_seen < latest_run` | The promo field used to exist; gone after commit X. |

The prototype already ships the first two: a hand-authored set of expected concepts is
seeded (`seed_expected_concepts`), and `missing_expected_concepts` plus the coverage
summary report exactly what was expected and never observed/validated. Production adds
the third by leaning on `commit_sha` and `last_seen`.

### 2.6 · The reasoning: a deterministic floor with an LLM that widens it

This is the heart of the two-engine design, and the part where I am most careful about
trust.

- **The floor is deterministic.** Inference rules are *data, not code*: a set of
  prerequisites plus the pivot action whose validation would close the gap. In the
  prototype, `INFERENCE_RULES` + `GraphStore.infer_missed_scenarios` produce missed
  scenarios from graph structure with plain Cypher. Because it is deterministic, it
  **cannot hallucinate** — it can only be wrong if a rule is wrong, and rules are
  reviewable, versioned, and testable.
- **Engine 2 widens the candidate set.** An LLM reads the graph state (observed,
  validated, expected, absent) and proposes *additional* gap scenarios the rules didn't
  encode — "removing the last item should empty the cart," "an invalid promo should
  show an error." In the prototype this is `graph_expansion.expand_from_graph`, with a
  deterministic fallback when the model is unavailable.

The division of trust: **the LLM may propose, but it does not get to decide a scenario
is real.** A proposed scenario only earns trust by being *probed* (handed back to
Engine 1, executed, and validated) or by matching a deterministic rule. This is the
answer to "how do you use an LLM in the reasoning layer without it inventing tests
that don't exist": you let it expand recall, and you make the deterministic layer and
the validator the precision filter.

---

## 3 · Keeping the graph honest over time

The brief pushes hardest here, rightly: how is the graph still correct on the 50th run,
six months in, after 30 PRs? The answer is a clear split between what is incremental,
recomputed, invalidated, and what compounds.

| Operation | Trigger | Implementation |
|---|---|---|
| **Incremental** | every crawl run | Upsert observations, bump `last_seen`, append evidence, update concept rollups, add `Scenario-[:CONFIRMED_BY]->Run`. O(seen this run). |
| **Recomputed** | a run touching a feature | Re-run inference and scenario confidence **for that feature only**. Never global. |
| **Invalidated** | a PR touches mapped code; a selector fails N runs; repeated validation failure | Mark a *bounded subgraph* stale; push the affected scenarios into the retest frontier. |
| **Compounds** | many runs over time | Selector stability, flake rate, transition probabilities, confidence-decay curves — the six-month moat that a fresh competitor cannot clone. |

### 3.1 · Confidence decay and retest

Every scenario's confidence **decays unless something renews it** — roughly, halve the
distance to a floor each time a run *could* have confirmed it but didn't, and reset on
a fresh confirmation. A scenario that drops below threshold re-enters the retest
frontier on its own.

> **Decision.** Freshness comes from **bounded invalidation**, not nightly full recompute.
> **Trade-off.** You must maintain the code→selector→concept map that makes invalidation precise.
> **Refusal line.** I will not ship "recompute the whole graph every night" as the freshness story — it is expensive and it *hides* drift instead of surfacing it.

---

## 4 · How I'd know any of it is actually right

There are two places this system can be confidently wrong, and they need different
checks: **the agent clicked the wrong thing**, and **the graph inferred a scenario that
isn't real**. One is a perception problem, the other a reasoning problem.

| Question | Signal | Metric |
|---|---|---|
| Did it click the right target? | browser-use trace + positive/negative-target check | wrong-target rate, wander rate |
| Did the action succeed? | deterministic post-condition after re-observation | validation pass rate |
| Is the scenario reproducible? | replay across clean sessions + golden apps | flake rate, pass@k |
| Are confidence scores calibrated? | predicted confidence vs observed reproduction | ECE, Brier score |
| Did a model/prompt change regress? | canary evals on versioned golden trajectories | delta vs baseline |

I would run **three eval layers**: offline **golden apps** with human-labeled states,
actions, and scenarios (deterministic regression for prompt/model changes); **replay**
of recorded trajectories across clean sessions (flake and reproduction); and
**canaries** on every model or prompt bump before customer rollout.

> **Decision.** Never use a model to grade a model on anything that has a deterministic check.
> **Trade-off.** Building golden apps and labeled trajectories is real upfront work.
> **Refusal line.** Confidence numbers do not go in the customer UI until the calibration check passes — uncalibrated confidence is just false authority.

---

## 5 · What this costs, and which model does what

The strategy is emphatically **not** "use the smartest model everywhere" — that is how
inference bills reach five figures for work a regex could do. The rule is: **deterministic
by default, small models for high-volume fuzzy work, the frontier model only for
low-volume high-reasoning work, offline where possible.**

| Task | Default | Why |
|---|---|---|
| State resolution, validation, inference floor, ingestion, convergence | **Deterministic (free)** | ~90% of operations; must be explainable and repeatable. Never use a model to check a model. |
| Browser execution (which element to click) — Engine 1 | **Small/fast** — GPT-4o-mini / Haiku-class / Gemini Flash | High volume, low stakes, latency-sensitive UI skill. |
| Graph gap proposals — Engine 2 | **Cached, mid-tier**, keyed by graph-state signature | Useful breadth, *not trusted directly*; re-used when the graph state hasn't changed. |
| Rule discovery, eval adjudication, onboarding triage | **Frontier — Claude Opus-class**, offline | Low volume, high reasoning value; amortized across customers and releases. |

### 5.1 · The math, worked through

Per feature-crawl, steady state. Engine 1 runs ~25 browser steps at roughly 3k in /
0.3k out tokens on a small model: ≈ **75k in / 7.5k out per crawl**. Engine 2 fires a
handful of graph-reasoning calls only at convergence — say 4 calls at ~4k in / 0.5k
out on a mid-tier model, cached by graph-state signature so an unchanged page costs
nothing: ≈ **16k in / 2k out per crawl**, and often far less on cache hits.

Scale it: a customer with 50 features crawled nightly is ≈ 50 × 30 = **1,500
crawls/month**. At the per-crawl figures above, that is a small-model bill dominated by
Engine 1, with Engine 2 a rounding error because it is gated on convergence and cached.
The frontier model is **not** in this path at all — it runs offline on rule discovery
and evals, amortized across the whole customer base.

### 5.2 · Cost levers (the redesign added three concrete ones)

| Lever | What it buys |
|---|---|
| **Action-level convergence** | The crawl stops when no *new* concept/label/validation appears — not after a fixed step budget, and not after a single concept. Short runs end short. |
| **No-repeat guard** (`repeat:already_done`) | An action done once is vetoed if attempted again this run. Directly kills the "re-do the same thing five times" token drain. |
| **Cart-scope bound** (`cart_scope:irrelevant_action`) | Recommendation rails create effectively infinite new labels; bounding the cart action surface is what lets convergence *actually converge* on a real Amazon page. |
| Cache Engine 2 by graph-state signature | No repeat reasoning calls when the page and concepts haven't changed. |
| Invalidate instead of full recrawl | You only spend on the bounded subgraph a PR touched. |

> **Decision.** Budget tokens and latency per stage; a stall is an observable failure, not silent spend.
> **Refusal line.** I refuse "LLM-judge every step in real time" — it makes cost scale with token price instead of with the number of real behaviours, and it puts a model in the trust path where a deterministic check belongs.

### 5.3 · Production tooling

Tooling falls out of the boundaries above, not the other way round.

| Layer | Start with | Avoid |
|---|---|---|
| Browser execution | Playwright + constrained LLM executor | A fully autonomous agent with *no* action contract or veto. |
| Graph store | Neo4j | Storing graph-shaped dependencies only in relational tables. |
| Artifact storage | S3 / GCS | Putting large DOM/screenshot blobs *inside* Neo4j. |
| Workflow orchestration | Temporal / durable queue | Fire-and-forget cron jobs for long, retryable crawls. |
| Search / vector memory | pgvector / OpenSearch (auxiliary, for selector repair) | Letting vector similarity *replace* graph truth. |
| Observability | OpenTelemetry + run traces + artifact refs | Plain logs with no trace IDs. |
| Eval store | Versioned golden apps + labeled trajectories | Shipping prompt changes without canaries. |

---

## 6 · A hundred customers, kept apart

My default here is to **over-isolate**, and I am comfortable saying so. In a tool that
crawls people's web apps and stores their DOM and screenshots, a cross-tenant leak is
existential.

| Layer | Isolated per tenant | Shared |
|---|---|---|
| Graph | Tenant/app/feature partition; database-per-tenant for large accounts | Schema + inference engine (code, not data) |
| Artifacts | Per-tenant object-store namespace, retention, redaction | Storage implementation |
| Models/prompts | Customer vocabulary stays isolated; versions visible in traces | Generic executor/reasoner prompt templates |
| Learning | **No** selectors, DOM, screenshots, or scenarios cross tenants | Aggregated, reviewed *structural priors* only |
| Ops | Per-tenant budgets and throttles | Global monitoring + anomaly detection |

Cross-customer learning is deliberately fenced. We may learn **structural priors** —
"checkout flows usually have a quantity→subtotal relationship" — as reviewed, aggregated
shape. We may **never** move a selector, a DOM snapshot, a screenshot, or a scenario
across a tenant boundary. The shared asset is the *schema and the inference engine*;
the moat is each tenant's own compounded history.

---

## 7 · Operations and observability

Agentic systems fail in ways ordinary services do not: same prompt, different outcome;
a correct click that the model *reports* as a failure; slow drift after a model upgrade.
You cannot operate this on plain logs.

| Telemetry | Example fields | Why it matters |
|---|---|---|
| Trace id per run/intent | tenant, app, feature, run_id, step, model_version, prompt_version | Reconstruct a failure across every service that touched it. |
| Decision audit | convergence signal, graph priority, safety decision, confidence | Explain why an action ran or was vetoed. |
| Artifact refs | DOM snapshot, screenshot, browser-use trace, transition | Human debugging and eval labeling. |
| Cost / latency | tokens, model, cache hit, duration, retries | Budget governance and customer pricing. |
| Health metrics | wander rate, validation-failure rate, stale-concept count, flake rate | Catch degradation before customers do. |

The alerts I would actually wire: **executor wander rate climbing after a model
upgrade** (the canary failed and shipped anyway), **validation-failure rate spiking on
a feature** (a real regression or a broken selector), and **stale-concept count growing
without new runs** (the freshness loop stalled).

### 7.1 · Test accounts and environments

A production agentic testing platform cannot depend on arbitrary customer *production*
accounts and real money. Each tenant gets **dedicated test accounts and a target
environment**, with the deny-list as the last line of defence even there. The platform
never needs to reach a real payment to validate a checkout flow — reaching the checkout
*boundary* is the assertion; crossing it is the thing we structurally forbid.

---

## 8 · PR blast radius

The optional PR hook is not a separate feature — it falls straight out of the same
graph. A PR is a set of changed `CodeArtifact`s, and the answer is a downward traversal:

| Step | Question it answers |
|---|---|
| CodeArtifact changed | What paths/symbols did the PR touch? |
| CodeArtifact → Selector | Which UI locators/components are backed by this code? |
| Selector → Concept | Which controls or capabilities are affected? |
| Concept → Scenario | Which discovered *and inferred* scenarios are at risk? |
| Scenario → Run / confidence | Which of those risks are stale, high-confidence, or just validated? |

The discipline is in the output. It is **never** "rerun all the checkout tests." It is:
*these* three selectors, *these* two validated scenarios, and *this* one inferred
scenario are at risk — retest exactly those. The prototype already does the traversal
(`scripts/pr_blast_radius.py`, `GraphStore.blast_radius`).

---

## 9 · The things I'd refuse to ship

This is the section I would most expect to be grilled on, which is exactly why it is
here.

| Refusal | Why, and what I'd need first |
|---|---|
| **A path that can click final purchase/payment — even behind a flag.** | Flags get flipped. Money pages must be *structurally* incapable of a final submit: the deny-list enforced as a separate process, plus a target environment that has no real payment. First I'd want a red-team that *tries* to make it buy something and fails every time. |
| **LLM self-report as validation.** | Every mutating action needs a deterministic post-condition. First I'd want a validator that cannot be satisfied by model prose — which the prototype already does for cart and checkout. |
| **A deny-list with no upper bound on the unknown-bad.** | A deny-list cannot block a dangerous action nobody enumerated. I'm comfortable shipping it *only because* the irreversible actions on a checkout flow are a short, known set (payment, account, money) — and those are exactly what we deny. Before widening to new app types I'd want a per-app review of "what is irreversible here," plus the red-team above. This is the honest seam in the design, and I'd rather name it than paper over it. |
| **The prototype's hard-coded concept vocabulary, as-is.** | Part A maps observed actions to canonical concepts (`action.delete_item`, `capability.promo_code`, …) with a deterministic keyword map, and scores coverage against a hand-authored expected list. That is a fine *prototype* shortcut and a poor *product*: it cannot generalise to a new app's vocabulary. Production replaces the keyword map with a learned, per-tenant concept model and treats the expected list as data discovered over runs, not a constant. First I'd want the concept layer behind an adapter so the core never hard-codes a single app's words. |
| **Nightly full-graph recomputation as the freshness strategy.** | Expensive, and it hides drift. Invalidate bounded subgraphs instead. First I'd want the invalidation path proven to catch a real regression on a golden tenant. |
| **Unreviewed cross-tenant learning.** | Aggregated priors may cross tenants; concepts, selectors, DOM, screenshots, and scenarios may not. First I'd want an audit log, a human promotion step, and a privacy review. |
| **Site-specific hacks in the platform core.** | App quirks — marketplace URL handling, subtotal parsing, cart-readiness — belong in adapters. The core owns state, safety, validation, graph, and eval. First I'd want the adapter boundary plus two genuinely different apps running through it. |

---

## 10 · Delivery roadmap

I would ship in phases that keep the system **runnable after every step**.

| Phase | Deliverable | Exit criteria |
|---|---|---|
| 0 · Working slice | One feature, autonomous crawl, graph ingest, an inferred missed scenario | Add-to-cart + quantity validated; a graph-surfaced miss probed (**done in Part A**). |
| 1 · Harness hardening | Deny-list veto, deterministic validator, no-repeat / convergence, strict provenance | No duplicate execution; no LLM self-report validation (**done**). |
| 2 · Living graph | Feature-scoped scenarios, confidence decay, bounded invalidation | Stale selectors/concepts re-enter the retest frontier on their own. |
| 3 · Eval harness | Golden apps, canaries, calibration dashboards | Model/prompt regressions caught before customer rollout. |
| 4 · Multi-tenant beta | Tenant isolation, budgets, artifact retention, observability | 100-customer architecture exercised under load and cost tests. |
| 5 · PR blast radius | CodeArtifact → Selector → Concept → Scenario traversal | A PR produces a bounded risk report and a retest plan (**seed in Part A**). |

### 10.1 · Rollout modes — autonomy is earned, not assumed

The platform moves through modes rather than flipping a switch:

| Mode | What the platform is allowed to do |
|---|---|
| 1 · Observe-only | Crawl and build the graph; no mutating clicks. |
| 2 · Recommend | Surface inferred scenarios and blast radius, but do not execute them. |
| 3 · Gated execution | Safe actions auto-run; mutating/destructive actions need policy approval. |
| 4 · Autonomous safe execution | Only after confidence, flake rate, and safety checks clear thresholds. |

---

## 11 · How Part A grounds every claim here

None of this is hypothetical. Each production claim already has a working seed:

| Production claim | Prototype function |
|---|---|
| Two engines: free crawl, then graph closes the gaps | `GraphGuidedExplorer._autonomous_loop` (Phase A/B/C), `BrowserUseIntentExecutor.explore_autonomously` |
| Safety an LLM cannot bypass (deny-list, pre-execution) | `safety_guard.veto_reason`, run inside browser-use's step callback |
| Bounded action surface / cost control | `is_cart_relevant_action`, no-repeat `_done_labels`, action-level convergence in `_autonomous_loop` |
| Executor output is evidence, not truth (re-observe + assert) | `_run_assertions`, `_checkout_reached_ok`, cart-delta provenance |
| Graph *reasons* about missed scenarios (Engine 2) | `graph_expansion.expand_from_graph` + deterministic `GraphStore.infer_missed_scenarios` / `INFERENCE_RULES` |
| Graph reasoning feeds back into exploration, with honest attribution | `_run_graph_probes`, strict `graph_directed` crediting in `_ingest_autonomous` |
| Absence as a graph query | `seed_expected_concepts`, `missing_expected_concepts`, `_coverage_summary` |
| PR blast radius as a graph traversal | `scripts/pr_blast_radius.py`, `GraphStore.blast_radius` |
| Quantified graph value | the report's "Graph impact" block |

---

## 12 · Where I'd plant the flag

If I had to put the whole argument in one line: **the valuable thing here was never the
clever crawler — it was the loop between a probabilistic explorer and a structural
memory, with a hard wall between what the system *did* and what it is allowed to
*believe*.**

A browser agent finds what it bumps into. A graph reasons about what should exist. The
deny-list keeps the explorer free without letting it do anything irreversible, and the
deterministic validator and inference floor keep the graph from believing the agent's
optimism. Get *that* right — the boundaries, the provenance, the absence modeling, the
earned autonomy — and the flashy parts (browser-use, Playwright, whichever model is in
fashion this quarter) become replaceable implementation details. That is the system I'd
defend, and the one I would actually want on call at 3 a.m.
