# Part B — Production Architecture

*Turning the little Amazon-checkout prototype into the intelligence layer of an agentic
testing platform — the thing that sits between every code change and every confident
release.*

I wrote this the way I'd actually pitch it to a founding team: opinionated, specific
enough that a senior engineer could start building from it, and honest about the parts
I'd refuse to ship until I'd seen proof. Where a claim already has a working seed in
Part A, I say so — §13 maps every production claim back to the function that already
does a small version of it.

One framing up front, because it drives everything else. It would be easy to spend
this document arguing about frameworks — LangGraph vs. a custom orchestrator, Neo4j
vs. something else. I think that's the wrong fight. **The architecture that matters is
the agent harness and the evaluation layer.** Get those two right and the framework
underneath is a six-week refactor. Get them wrong and no framework saves you. So this
document is organised around those two spines, and everything else — agents, models,
graph, guardrails — hangs off them.

---

## 0 · The one belief this rests on

A browser agent and a knowledge graph have opposite strengths, and the whole design is
about letting each do only what it's good at.

The browser agent is a **guesser**. Point it at a page and it'll find the thing that
adds to cart — genuinely hard, fuzzy, page-specific work that survives Amazon shipping
a redesign. But it's a terrible historian: it'll cheerfully tell you it succeeded when
it didn't, and it has no memory of what it already tried.

The graph is the mirror image. It can't click anything, but it's **structural memory**
— it holds everything we've ever seen about checkout and can reason over it: what's
been observed, what's actually been proven, what *should* exist but doesn't.

> **The belief:** the crawler is a probabilistic discovery device; the graph is the
> structural memory that tells you what discovery missed. Neither is trustworthy alone.
> The value is the loop between them — and the harness that keeps that loop honest.

The failure mode I actually lose sleep over isn't the agent missing a button. You can
always crawl again. It's the system **silently believing something false** — "checkout
works" when the click never landed, "the promo field is gone" when the agent just
wandered. So the whole architecture is built to make confident-wrong states *expensive
to reach and cheap to detect*. That single idea shows up in every section below.

[[FIG:loop|The core loop: the graph plans, the browser acts, the harness validates and writes memory, and the graph reasons over what it learned — then does it again.]]

---

## 1 · The multi-agent network

The biggest call I made is to split the work into small, single-purpose agents with
hard boundaries, instead of building one clever agent that does everything. A mega-agent
that decides what to test, clicks it, judges whether it worked, and writes the result is
impossible to trust or debug — every failure is tangled up with every other one.

At Testsigma's scale this becomes a network of specialised agents. Here's how I'd
decompose it, with the boundary each one isn't allowed to cross:

| Agent | Owns | LLM? | The boundary I enforce |
|---|---|---|---|
| **Planner** | The frontier — what to explore/test next, priorities, budgets | No | Decides *what*; it never touches the browser. |
| **Crawler** | One UI action via browser-use (DOM, ARIA, screenshot) | Yes (small/fast) | Executes *how*; it never writes graph truth or decides what "passed." |
| **Observer** | Page snapshot → typed state, controls, concepts, raw artifacts | Mostly no | Hands back the *raw evidence* (DOM, screenshot, URL), not a summary to trust. |
| **Reasoner** | Missed / absent / causal scenarios from graph structure | LLM proposes, Cypher decides | The trustworthy floor is deterministic; the LLM only *widens* the candidate set. |
| **Validator** | Deterministic post-conditions after an action | No | Nothing becomes "validated" until it re-checks from independent evidence. |
| **Healer** | Selector repair when a locator breaks | Small model + graph | Proposes a fix; the Validator still has to confirm it. |
| **Triage** | Cluster failures, decide flake vs. real regression | LLM + graph history | Escalates; it doesn't silently suppress. |
| **Safety supervisor** | The guardrails, checked before every action | No | Vetoes *before* the browser ever sees the task. |
| **Ingestor** | Idempotent graph writes with provenance + confidence | No | No model calls; every write is typed and replayable. |

The boundary I care about most is between the Crawler and the Validator. **The Crawler
is allowed to be wrong. The Validator's entire job is to not believe it.** When the
Crawler says "I changed the quantity," the Validator re-reads the actual cart and checks
the number moved — because the model is wrong about exactly that surprisingly often.

The other thing worth spelling out is what happens when an agent **fails, stalls, or
returns low confidence** — because that's where demos and production part ways:

- **Fails** (throws, times out): the harness retries with backoff up to a budget, then
  marks the step failed and moves on. A failed step is data, not a crash.
- **Stalls** (keeps acting without progress — I actually hit this: the agent re-clicked
  "increase quantity" four times): a per-run action ledger + a no-repeat guard turns it
  into a fast veto instead of a runaway loop.
- **Low confidence**: the agent doesn't get to quietly pass. Below its threshold it
  either escalates to a stronger model, hands off to a human, or writes an explicit
  "unverified" marker into the graph. Uncertainty is a first-class output, not an
  inconvenience.

### 1.1 · The contract between agents

Agents don't share a blob of state — they pass **typed contracts** (Pydantic schemas in
Python), and that's deliberately the most important interface in the system. Every
hand-off carries: the intent, the expected state it applies to, a **confidence
structure** (not a vibe — a number plus what it's conditioned on), success evidence to
look for, a risk class, and an escalation signal. I'd freeze those contracts before a
single agent is built, because they're what lets me swap the model or the framework
underneath any one agent without the others noticing.

[[FIG:agents|The agent network around the harness and the graph. Nothing writes graph truth except the Ingestor, and nothing becomes "validated" without the Validator.]]

---

## 2 · The agent harness — this is the architecture

If I could only get one thing right, it'd be this. The **harness** is the runtime every
agent runs inside. It owns state, retries, timeouts, tool dispatch, output-schema
enforcement, deterministic replay, and the human-in-the-loop interrupt protocol.
Frameworks like LangGraph give you the state-machine primitives; the value I'm adding
lives *above* them.

What the harness owns, concretely:

- **State + replay.** Every run is a durable, resumable workflow — I'd use **Temporal**
  here, because crawls are long-running and I want to replay a failure step-by-step six
  weeks later, not guess at it. Every agent step is recorded with its inputs, outputs,
  model + prompt version, and a trace ID.
- **Structured tool dispatch + output validation.** Agents don't return prose that
  something downstream parses hopefully. They return schema-validated objects, and a
  response that doesn't fit the schema is a failure the harness catches — not silent
  garbage that becomes ground truth.
- **Retries, timeouts, circuit breakers.** Per-stage latency and token budgets. A stage
  that blows its budget surfaces as an observable failure, not silent spend or a hang.
- **HITL interrupts.** A clean protocol for "stop and ask a human" — with the run
  paused, not abandoned, so a person can answer and the workflow continues.

Here's the thing I'd say in the room and mean it: the choice between LangGraph and a
custom orchestrator genuinely is a refactor. The harness contracts — *what state looks
like, how replay works, how output is validated, when a human is pulled in* — are the
part that's expensive to get wrong and expensive to change later. So that's what I'd
design and defend first.

---

## 3 · Guardrails, designed per agent — not as global middleware

Production agent systems fail in ways demos don't, and a single global "safety
middleware" is the wrong shape for it, because every agent is uncertain about different
things. So guardrails are **per agent**: each one declares what "uncertain" means for
it and what happens at that boundary.

The Part-A prototype already ships the sharpest example of this — the **deny-list
safety veto**. I want to defend the shape of it, because it's the opposite of the
obvious choice.

The tempting move is an **allow-list**: enumerate the safe actions, permit only those.
Safe, and wrong for *this* system. The whole reason to put a graph behind the crawler is
to surface scenarios nobody pre-conceived — an allow-list can only permit actions
someone already thought of, so it would block every newly discovered or graph-inferred
intent and quietly defeat the product. A guardrail that only passes what you already
enumerated can't guard a system whose job is to find what you *didn't* enumerate.

So safety is a **deny-list**: default-allow, block a short, enumerable set of known-bad
actions before they execute. The trick is that the genuinely dangerous actions are
exactly the ones you *can* enumerate, because they're irreversible or identity-level —
place order, pay, sign out, navigate off the product under test. Everything reversible
(quantity, delete, save-for-later, promo) is fair game, because a mistake there is cheap
and the Validator catches it.

Around that, the production guardrail layer per agent:

| Guardrail | What it does |
|---|---|
| **Output validators / schema enforcement** | The agent's output must fit its contract or it's a failure, full stop. |
| **Confidence gating** | Below threshold → escalate, fall back, or write "unverified." No silent low-confidence passes. |
| **Circuit breakers** | An agent that fails N times in a row on a feature gets tripped and the feature is flagged, not hammered. |
| **Fallback chains** | Frontier model → small model → deterministic rule → human, in that order, per agent. |
| **The deny-list veto** | The one hard wall: irreversible actions blocked before execution, as a *separate* process a planning bug can't bypass. |

---

## 4 · Model routing and composition

This role is about being the most sophisticated *consumer* of models in the room, not
training them. So I'd own a routing table, and I'd defend it with eval numbers rather
than brand preference. The principle is boring and correct: **deterministic by default,
small models for high-volume fuzzy work, the frontier model only where reasoning value
is high and volume is low.**

| Task | What I'd route it to | Why |
|---|---|---|
| State resolution, validation, inference, ingestion | **Deterministic code (free)** | ~90% of operations. Must be explainable and repeatable. You never use a model to check a model. |
| Which element to click (the Crawler) | **Small/fast** — GPT-4o-mini / Haiku / Gemini Flash | High volume, low stakes, latency-sensitive UI skill. |
| Locator-stability / flake classification | **Fine-tuned small open model** (Mistral-class) | Narrow, repetitive, cheap to fine-tune, and it beats a frontier model on cost at this volume. |
| Graph gap reasoning, root-cause chains, eval adjudication | **Frontier — Claude-class, extended thinking** | Low volume, high reasoning value; amortised across customers and releases. |

A few opinions I'd stake:

- **Compose models without compounding hallucination.** The danger in a pipeline is one
  model's guess becoming the next model's "fact." The defence is the same as everywhere
  else here: between model stages sits a deterministic check or a graph lookup, so a
  guess never silently hardens into truth.
- **Pin prompt + model versions.** Every run records which model and prompt version ran.
  When a provider ships a "better" model, I want to know it changed *my* decision quality
  before a customer does — which is a canary-eval problem (§8), not a hope.
- **Context management for long sessions.** A long agentic crawl accumulates context
  fast. I'd compress aggressively: the graph *is* the long-term memory, so the working
  context stays small — the agent pulls exactly the graph slice it needs via the Query
  Machine (§6) rather than dragging the whole history along.

On cost, worked through: a feature-crawl in steady state is ~25 small-model steps at
roughly 3k in / 0.3k out — call it 75k in / 7.5k out per crawl. The frontier model isn't
in that path at all; it runs offline on rule discovery and eval adjudication, amortised
across every customer. A customer crawling 50 features nightly is ~1,500 crawls/month,
and the bill is dominated by the cheap model on purpose. The expensive levers I'd pull to
keep it there: cache LLM calls by graph-state signature, invalidate bounded subgraphs
instead of re-crawling everything, and never put a frontier model on the hot path.

---

## 5 · The production graph schema

The textbook hierarchy for UI testing is `Element → Component → Flow → Feature`. I
wouldn't use it as the backbone, because it models the UI's *shape* but not the two
things this platform actually sells: **provenance** (why do we believe this?) and
**absence** (what should exist but doesn't?). So I built the graph around the questions
we have to answer, not around the DOM tree.

**Node types**

| Node | Key properties | A query it answers |
|---|---|---|
| Tenant / App / Feature | ids | Everything is scoped; one feature modeled deeply. |
| Run | `commit_sha`, `started_at`, `model_version`, `cost` | What did we know at run N vs. N+1? |
| Observation | `state`, `url`, `artifact_ref`, `screenshot_ref` | Replay exactly what the browser saw. |
| Concept | `key`, `kind`, `observed`, `validated`, `expected`, `confidence`, `first_seen`, `last_seen` | Expected-not-observed; observed-not-validated. |
| Intent | `source`, `status`, `risk`, `selector_ref`, `confidence` | Why an action ran, passed, or was vetoed. |
| Scenario | `key`, `status`, `confidence`, `last_confirmed_run` | Which scenarios are trusted right now vs. decayed. |
| Selector | `hash`, `css/xpath/role`, `stability`, `last_failed` | Blast radius and self-healing. |
| CodeArtifact | `path`, `symbol`, `commit_sha` | Map a PR change to selectors → concepts → scenarios. |

The single most important choice: **the unit of meaning is a `Concept` — a behaviour —
not a DOM element.** Selectors are the least stable thing in the whole system; they
change every redesign. Model the graph around *what a control means* ("this is the
add-to-cart capability") instead of *how to find it* (`#some-id`), and the graph stays
meaningful across redesigns while selectors churn underneath as replaceable properties.

**The edges are where the value is** — and I'd put **provenance and confidence on every
edge**, not just nodes:

| Edge | Between | What it lets me ask |
|---|---|---|
| `OBSERVED` / `SAW_CONCEPT` | Run → Observation → Concept | "What did we see, and where?" |
| `TARGETS` | Intent → Concept | "Which attempt exercised which behaviour, and did it pass?" |
| `DEPENDS_ON` | Scenario → Concept | "Which concepts does this scenario rely on?" (blast radius) |
| `SHOULD_CAUSE` | Concept → Concept | "This cause should produce this effect" — the causal expectation the reasoner checks |
| `BACKS` | CodeArtifact → Selector | "Which code backs this locator?" (PR risk) |

Here's a concrete instance of the graph after one checkout crawl — small enough to read,
real enough to reason over:

[[FIG:sample_graph|A sample knowledge graph after one Amazon-checkout crawl. Solid nodes were validated; the dashed subtotal node was observed but never proven; the dashed SHOULD_CAUSE edge is the causal gap the reasoner surfaces.]]

That dashed `SHOULD_CAUSE` edge from *change-quantity* to *subtotal* — observed cause,
expected effect, never proven — is exactly the kind of missed test the graph surfaces and
the crawler would never have written for itself.

### 5.1 · Why a graph and not just vectors

I'd push back hard on "just use RAG for this." Vector similarity is great at "find me
things like this," and useless at the three things that actually matter here:

- **Absence.** "What test *should* exist and doesn't" is not a similarity query — there's
  nothing to be similar to. It's a structural query over expected-but-not-observed, which
  the graph answers in one hop and a vector store can't express at all.
- **Temporal reasoning.** "What did the system know at commit X?" needs edges stamped
  with time and `commit_sha`, not nearest neighbours.
- **Multi-hop traversal.** `CodeArtifact → Selector → Concept → Scenario` is a four-hop
  walk. Vectors give you one hop of fuzzy similarity; the walk is the whole point.

Vectors still earn a place — selector repair and semantic matching — so I'd run
**pgvector** (or Weaviate) alongside Neo4j as a **hybrid**: the graph is the source of
truth, the vector index is an auxiliary lookup. It never replaces graph truth; it helps
you *find* a starting node for the traversal.

---

## 6 · The Query Machine — how the LLM actually uses the graph

A graph is only as useful as the questions the agents can ask it. Dumping the whole
graph into a prompt doesn't work (context blows up, and the model drowns), and hand-
writing a Cypher query for every agent need doesn't scale. So I'd build a **Query
Machine**: the layer that sits between the agents and Neo4j and turns "what does the
graph know?" into structured, bounded, typed answers the LLM can actually reason over.

It has three tiers, and the ordering is the whole point:

1. **A library of parameterised, typed graph queries — exposed as tools.** These are the
   90% case. `missed_scenarios(feature)`, `absence(feature)`, `blast_radius(concept)`,
   `neighbours(concept, hops)`, `confidence_of(scenario)`, `what_did_we_know_at(commit)`.
   Each is hand-written, reviewed Cypher with a typed result schema. The agent LLM picks
   a query and fills the parameters as a structured tool call — it never writes Cypher.
   Deterministic, cacheable, can't hallucinate a traversal.
2. **Guarded natural-language → Cypher, for the long tail.** When an agent has a genuinely
   novel question, a frontier model translates it to Cypher — but the query runs
   **read-only**, against a schema allow-list, with a cost/row cap, and the generated
   Cypher is logged for review. If it fails validation, it falls back to tier 1. The LLM
   gets flexibility without getting the keys to the database.
3. **Hybrid graph + vector.** For "find the right starting node" the Query Machine can
   hit pgvector first (semantic match on a concept/selector), then hand the node id to a
   graph traversal. Similarity to *locate*, structure to *reason*.

Every answer comes back the same way: typed rows, each carrying provenance and confidence,
small enough to drop into the model's context. That's what "the graph information can be
fully utilised by the LLM" actually means in practice — not a bigger prompt, but a
**bounded, trustworthy query interface** the agent calls like any other tool.

[[FIG:query_machine|The Query Machine: agents ask questions as typed tool calls; deterministic Cypher templates answer the common ones; a guarded NL→Cypher path handles the long tail; every answer is typed, provenance-tagged, and small enough for the model's context.]]

In Part A this exists in embryo: the deterministic inference (`infer_missed_scenarios`)
and the blast-radius traversal are the first two "tools," and the graph-expansion LLM is
the first taste of the NL path. Production is mostly turning that into a real, versioned,
guard-railed query library.

---

## 7 · Keeping the graph correct over time (the living property)

The brief pushes hardest here, rightly: how is the graph still correct on the 50th run,
six months in, after 30 PRs? The answer is a clean split between what's incremental,
recomputed, invalidated, and what compounds.

| Operation | Trigger | How |
|---|---|---|
| **Incremental** | every crawl | Upsert observations, bump `last_seen`, append evidence, add `Scenario-[:CONFIRMED_BY]->Run`. O(seen this run). |
| **Recomputed** | a run touching a feature | Re-run inference + confidence **for that feature only**. Never global. |
| **Invalidated** | a PR touches mapped code; a selector fails N times; repeated validation failure | Mark a *bounded subgraph* stale; push affected scenarios into the retest frontier. |
| **Compounds** | many runs over time | Selector stability, flake rate, transition probabilities, confidence-decay curves — the six-month moat a fresh competitor can't clone. |

Two things I'd design carefully because they're where "living" gets hard:

- **Conflict resolution.** When this run disagrees with last week (the promo field was
  here, now it's gone), I don't overwrite — I keep both, stamped with `commit_sha` and
  time, and let confidence decay carry the old signal down. "What did we know at time T"
  stays answerable because I never destroy history; I supersede it.
- **Decisions become signal.** Every validated agent decision is training signal for
  tomorrow — a confirmed scenario raises the prior on the next run, a repeatedly-flaky one
  lowers it. That's the compounding institutional asset the whole thing is about, and it's
  why confidence decay (below) is load-bearing rather than a nice-to-have.

Confidence decays unless something renews it — roughly, halve the distance to a floor each
time a run *could* have confirmed a scenario but didn't; reset on a fresh confirmation. A
scenario that drops below threshold re-enters the retest frontier on its own.

[[FIG:decay|Confidence over successive runs: a scenario decays when runs don't reconfirm it, and snaps back to full confidence the moment a run proves it again. Below the retest line it re-enters the frontier automatically.]]

> **The refusal:** I will not ship "recompute the whole graph nightly" as the freshness
> story. It's expensive and it *hides* drift. Bounded invalidation, proven on a golden
> tenant to catch a real regression, is the version I'd defend.

---

## 8 · Eval and confidence — the other spine

This is the layer that separates a research demo from a production system, and the JD is
right that it *is* the architecture. Two places this system can be confidently wrong, and
they need different checks: the agent clicked the wrong thing (perception), and the graph
inferred a scenario that isn't real (reasoning).

**Three eval layers I'd build:**

1. **Offline golden apps + regression suites.** Versioned, human-labelled trajectories.
   Every prompt or model change runs against them before it ships. Deterministic pass/fail
   plus trajectory- and step-level grading.
2. **Online production sampling.** A sampled slice of real runs graded continuously, so
   you catch drift the golden set didn't anticipate.
3. **Canary evals.** Every model/prompt bump runs against the golden trajectories *before*
   customer rollout. This is what catches a provider shipping a "better" model that
   quietly degrades *your* decision quality.

| Question | Signal | Metric |
|---|---|---|
| Did it click the right target? | trace + positive/negative-target check | wrong-target rate, wander rate |
| Did the action succeed? | deterministic post-condition after re-observe | validation pass rate |
| Is the scenario reproducible? | replay across clean sessions | flake rate, pass@k |
| Are confidence scores honest? | predicted confidence vs. observed reproduction | **ECE, Brier score** |
| Did a model change regress us? | canary on versioned golden trajectories | delta vs. baseline |

On tooling: I'd start on a managed eval store (Braintrust or LangSmith-style) to move
fast, but I'd own the golden sets and the grading logic in-house, because that's the
moat. **LLM-as-judge, calibrated against human spot-checks** — never an uncalibrated
judge, and never a model grading something that has a deterministic check available.

The confidence point deserves emphasis because it's an architectural requirement, not a
feature: **the system has to know what it doesn't know.** Every agent output carries a
calibrated confidence, the harness gates on it, and I *measure* the calibration (ECE /
Brier) rather than trusting it. Confidence without calibration is just false authority,
and it doesn't go anywhere near a customer UI until the calibration check passes.

[[FIG:eval|The eval spine: offline golden sets and online sampling feed a grader (deterministic where possible, calibrated LLM-judge where not); calibration and canary gates stand between a model change and a customer.]]

---

## 9 · Observability and operations

Agentic systems fail in ways ordinary services don't — same prompt, different outcome; a
correct action the model *reports* as a failure; slow drift after a model upgrade. You
can't operate that on plain logs.

- **A trace ID that follows a reasoning chain** across every agent call, with model +
  prompt version at each hop — **OpenTelemetry** as the backbone.
- **Decision audit trails** — the frontier score, the guardrail decision, the confidence,
  for every action that ran or was vetoed. Every decision is replayable.
- **Latency + cost budgets per agent stage**, so a stall or runaway is an observable
  failure, not silent spend.
- **Anomaly detection tuned for non-determinism** — the alerts I'd actually wire:
  executor wander-rate climbing after a model upgrade (a canary that shipped anyway),
  validation-failure rate spiking on a feature (a real regression or a broken selector),
  stale-concept count growing without new runs (the freshness loop stalled).

And because autonomy should be *earned*, the platform moves through rollout modes rather
than flipping a switch: observe-only → recommend → gated execution (safe actions auto-run,
mutating ones need approval) → autonomous safe execution, only after confidence, flake
rate, and safety thresholds clear.

---

## 10 · Multi-tenancy and scale

The platform has to work for a team of five and a team of five hundred, and one
customer's knowledge graph must never bleed into another's. My default here is to
**over-isolate**, and I'm comfortable saying so — in a tool that crawls people's apps and
stores their DOM and screenshots, a cross-tenant leak is existential.

| Layer | Isolated per tenant | Shared |
|---|---|---|
| Graph | Tenant/app/feature partition; database-per-tenant for big accounts | Schema + inference engine (code, not data) |
| Artifacts | Per-tenant object-store namespace, retention, redaction | Storage implementation |
| Models/prompts | Customer vocabulary stays isolated; versions in traces | Generic prompt templates |
| Learning | **No** selectors, DOM, screenshots, or scenarios cross tenants | Aggregated, reviewed *structural priors* only |

For scale: **async agent execution** on a queue (**Celery + Redis**), long-running crawls
as durable **Temporal** workflows, LLM calls cached by graph-state signature, and
graph-query optimisation via the parameterised Query Machine (bounded, indexed queries
instead of ad-hoc traversals). The heavy artifacts (DOM, screenshots) live in **S3/GCS**;
Neo4j stores references only. Backend is **Python (async, typed) + FastAPI**, packaged in
**Docker/K8s** on AWS or GCP.

Cross-customer learning is deliberately fenced. We can learn *structural priors* —
"checkout flows usually have a quantity→subtotal relationship" — as reviewed, aggregated
shape. We never move a selector, a DOM snapshot, or a scenario across a tenant boundary.

---

## 11 · PR blast radius

The optional PR hook isn't a separate feature — it falls straight out of the graph. A PR
is a set of changed `CodeArtifact`s, and the answer is a downward traversal:
`CodeArtifact → Selector → Concept → Scenario → confidence`. The discipline is in the
output: it's never "rerun all the checkout tests," it's "*these* two selectors, *these*
validated scenarios, and *this* one inferred scenario are at risk — retest exactly those."
Part A already does the traversal (`pr_blast_radius.py`); production adds confidence and
freshness to the ranking.

---

## 12 · What I'd refuse to ship — and the hardest problem

This is the section I'd most expect to get grilled on, which is exactly why it's here.

| Refusal | Why, and what I'd need first |
|---|---|
| A path that can click final purchase — even behind a flag | Flags get flipped. Money pages must be *structurally* incapable of a final submit. First I'd want a red-team that tries to make it buy something and fails every time. |
| LLM self-report as validation | Every mutating action needs a deterministic post-condition. The prototype already does this for cart and checkout. |
| An uncalibrated confidence number in the UI | Confidence without calibration is false authority. Not until §8's calibration check passes. |
| Nightly full-graph recompute as the freshness story | Expensive, and it hides drift. Bounded invalidation, proven on a golden tenant. |
| Unreviewed cross-tenant learning | Priors may cross tenants; concepts/selectors/DOM/scenarios may not. First I'd want an audit log and a human promotion step. |
| The prototype's hard-coded concept vocabulary, as-is | Fine for one feature, wrong for a hundred apps. Production replaces the keyword map with a learned, per-tenant concept model behind an adapter. |

And since the JD asks it directly — **the hardest unsolved problem in production agent
systems, in my view: knowing a probabilistic system is wrong *before* a human does.**
Everything downstream depends on confidence you can trust, and calibrating confidence is
genuinely hard when your judge is itself an LLM and the distribution keeps shifting under
you (new app, new model, new sprint). I don't think there's a clean solved answer. The
best I have is the architecture in this document — deterministic floors under the
probabilistic parts, calibrated confidence measured not assumed, canaries between a model
change and a customer, and a graph that remembers what was true so you can tell when it
stops being true. That's the problem I'd want to spend the next few years on.

---

## 13 · How Part A grounds every claim here

None of this is hand-waving — each production claim already has a working seed in the
prototype:

| Production claim | Prototype seed |
|---|---|
| Planner / Crawler split; graph plans, browser acts | `GraphGuidedExplorer._autonomous_loop`, `BrowserUseIntentExecutor` |
| Guardrails an LLM can't bypass (deny-list, pre-execution) | `safety_guard.veto_reason`, in the browser-use step callback |
| Executor output is evidence, not truth | re-observe + `_run_assertions`, cart-delta / checkout verification |
| Graph reasons about missed + causal gaps | `infer_missed_scenarios`, `CAUSAL_EXPECTATIONS` / `SHOULD_CAUSE` |
| The Query Machine (tier 1 + NL taste) | `infer_missed_scenarios`, `blast_radius`, `graph_expansion.expand_from_graph` |
| Absence as a graph query | `seed_expected_concepts`, `missing_expected_concepts` |
| Everything after the graph takes over is the graph's | `graph_phase_started` attribution |
| PR blast radius as a traversal | `pr_blast_radius.py`, `GraphStore.blast_radius` |
| Provenance + confidence on writes | `write_intent`, `write_observation` (source, confidence, last_seen) |

---

## 14 · The stack, and why

Tools should fall out of the boundaries, not the other way round. Here's what I'd reach
for and, just as important, what I'd avoid.

| Layer | I'd start with | I'd avoid |
|---|---|---|
| Agent harness | Custom harness over **LangGraph** primitives; **Temporal** for durable runs | A fully autonomous agent with no state/replay contract |
| Browser execution | **Playwright + browser-use**, sandboxed | An agent with no action contract or veto |
| Graph store | **Neo4j** (temporal patterns, provenance/confidence on edges) | Graph-shaped deps in relational tables |
| Retrieval | **pgvector / Weaviate**, auxiliary — hybrid graph+vector | Letting vector similarity replace graph truth |
| Query Machine | Parameterised Cypher tool library + guarded NL→Cypher | Free-form model-written Cypher on the hot path |
| Models | **Claude** (frontier reasoning/judge), **GPT-4o-mini / Haiku / Gemini Flash** (executor), **fine-tuned Mistral-class** (narrow classifiers), deterministic for validation | "We use OpenAI" as the whole model strategy |
| Eval | Versioned golden apps; **Braintrust/LangSmith-style** store; calibrated LLM-judge | Shipping prompt changes without canaries |
| Observability | **OpenTelemetry** + trace IDs + decision audit | Plain logs with no trace IDs |
| Async / queue | **Celery + Redis**; **FastAPI**; **Docker/K8s** on AWS/GCP | Fire-and-forget cron for long, retryable crawls |
| Artifacts | **S3 / GCS**; Neo4j holds refs only | Large DOM/screenshot blobs inside Neo4j |

If I had to put the whole thing in one line: the valuable part was never the clever
crawler — it's the loop between a probabilistic explorer and a structural memory, with a
hard wall between what the system *did* and what it's allowed to *believe*. Get the harness
and the eval layer right, and everything flashy underneath becomes a replaceable detail.
