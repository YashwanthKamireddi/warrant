# Architecture

How the pieces fit, where the trust boundaries sit, and why each load-bearing
decision was made rather than the obvious alternative.

---

## The one-paragraph version

A person's instruction becomes a **signed, bounded permission**. An agent's basket
is checked against that permission by **deterministic code that consults nothing
external**. A model is used in exactly two places, and in neither can it grant
authority. Every decision — including every refusal — lands in a **hash-chained
ledger**, which later renders as **dispute evidence a bank can verify without
trusting the merchant**.

---

## Flow

```
  person ──"chai and samosas, under ₹1,000"──▶ derive.py ──▶ ScopeProposal
                                                  │              │
                                     ┌────────────┘              │  model, narrow job
                                     ▼                           ▼
                                  Envelope ────intersect────▶ Scope
                                  (acquirer / PSP config;         │
                                   the model can only narrow)     │
                                                                  ▼
                                          person approves in plain English
                                                                  │
                                                    signs with THEIR device key
                                                                  ▼
                                                          IntentMandate
                                                                  │
  agent ──proposes basket──▶ CartMandate ─────────────────────────┤
                                     │                            │
                                     ▼                            │
                          ┌──────────────────────┐                │
                          │  gate.evaluate()     │◀───────────────┘
                          │  11 binding rules    │
                          │  pure · no network   │
                          └──────────┬───────────┘
                                     │
                     ┌───────────────┼────────────────┐
                     ▼               ▼                ▼
                  BLOCK          ESCALATE           ALLOW
                     │               │                │
                     │               │       divergence.py (model, advisory)
                     │               │                │  can only raise to ESCALATE
                     │               │                ▼
                     │               │        record_authorized()  ← nonce consumed
                     │               │                │
                     │               │                ▼
                     │               │           rails/*  ──▶ Razorpay test mode
                     │               │                │        or the simulator
                     │               │                ▼
                     │               │         DebitReceipt (on settle)
                     └───────────────┴────────────────┤
                                                      ▼
                                            chain.py — hash-chained ledger
                                                      │
                                    ┌─────────────────┴──────────────────┐
                                    ▼                                    ▼
                            evidence.py                            interop.py
                       Razorpay dispute pack                    AP2 / W3C-VC export
```

---

## Trust boundaries

| Party | Holds | Can do | Cannot do |
| --- | --- | --- | --- |
| **Person** | device signing key | Grant, narrow and revoke authority | — |
| **Agent** | nothing signable | Propose baskets | Sign anything. Widen anything. |
| **Authoriser** | attestation key | Check a basket; attest it was checked; refuse | Widen a scope. Produce a chain that verifies as in-scope for an unpermitted purchase. |
| **Merchant** | item catalog | Declare item categories | Declare a category outside its acquirer-assigned MCC |
| **Model** | nothing | Propose a scope; flag divergence | Grant authority. Overturn a block. Widen the envelope. |
| **Rail** | the funds block | Enforce the blocked amount | Enforce category or merchant scope — which is why this layer exists |
| **Acquirer** | the merchant registry | Assign a merchant its MCC | — (it is a file the deployer supplies; a merchant never writes its own line) |
| **API caller** | a bearer token | Mint, check, spend and revoke permissions | Reach any endpoint without one — `warrant_router` refuses to be constructed unauthenticated |
| **Log reader** | stderr | See verdicts, digests, rules, timings | See a basket, a product name or an utterance — none reach a log line |

**The precise claim.** Only the person's key can *widen* what may be spent, so the
authoriser cannot produce a chain that verifies as in-scope for a purchase nobody
permitted. A compromised authoriser **can** still skip its own gate and call the
rail, spending the remaining block on anything — the rail enforces amount, not
category. The chain gives **detection with attribution, not prevention**.
Preventing that outright requires the rail to enforce scope, which is the layer
NPCI's UAP is being designed to occupy.

---

## Decisions

### Money is an integer count of paise, everywhere

Floats have no canonical decimal form that two languages agree on, and the
console verifies signatures in JavaScript. `canon.py` **rejects a float outright**
rather than rounding it, so an amount that would serialise differently on the
verifier's machine can never be signed.

*Rejected:* `Decimal`. Correct arithmetic, no canonical wire form, same problem.

### Identifiers are content addresses

`im_a3f2…` *is* the first 16 hex of the intent's digest. An id cannot be forged,
reassigned, or made to point at a different document.

*Rejected:* UUIDs. They need a separate integrity check for the binding an id is
supposed to express.

### The deterministic gate runs first and alone

A cart that fails a binding check is refused before any model sees it. This is a
control, not an optimisation: an out-of-scope basket carrying an injected payload
in its product names never reaches a model at all. The demo shows it — the injected
cart is refused with `model_used=False`.

### The judge is structurally powerless

`DivergenceFinding.as_check()` hard-codes `binding=False`. If an injected product
name convinces the judge to return `consistent`, the outcome is **byte-identical to
the judge never running**. There is no prompt that makes it grant authority,
because it holds none. Tested end to end in `test_divergence.py`.

*Rejected:* letting the model block. It would have made every product description
on the internet an input to a refusal decision.

### The envelope, not prompt engineering

Whatever `derive.py` proposes is intersected with a hard envelope configured out
of band. `test_derive.py` feeds the narrowing step the output a hostile model
would produce — 10⁹-paise ceilings, invented merchants, wildcard allowlists,
year-long expiries — and asserts none escapes. The worst case is a scope too
narrow, which fails closed.

### Categories are checked against the acquirer's MCC

Merchants declare item categories; card networks solved half of this decades ago
by having the **acquirer** assign a category code the merchant does not pick.
`merchants.py` holds that registry and `merchant.mcc_scope` is binding.

**Closes:** a merchant outside a category cannot serve a mandate scoped to it.
**Still open:** a merchant mislabelling *inside* its own catalog. Zomato is MCC
5812; a power bank listed there as `food_beverage` still passes. Asserted by
`test_the_known_gap_is_documented_by_a_test` so nobody mistakes this for complete.

### Refusals are ledger entries, not silences

Most systems log what they did. A dispute almost always turns on what was
*declined*, when, and under which rule. `cart_blocked` carries the failed rule
names and the observed-versus-limit numbers.

### Authorisation is serialised per mandate

Checking a ceiling and then spending against it is a read-modify-write. Six carts
arriving together each read a budget nobody had claimed yet, all passed a ₹100
ceiling, and settled **₹360** between them — a direct double-spend in the one
thing this system exists to prevent, invisible to 198 single-threaded tests.

The lock is keyed on the intent digest, so one customer's mandate serialises while
every other proceeds in parallel. It is held across the rail call deliberately: a
mandate is a single person's bounded delegation and has no reason to run parallel
debits, and releasing early to reclaim throughput would put the window straight
back.

### Ledger reads are serialised too

A sqlite3 connection is not safe for interleaved cursor use across threads, even
with `check_same_thread=False`. Locking only the writes left readers walking a
cursor while an append moved underneath them, surfacing as entries that
deserialised with a `None` kind and as `another row available` errors — the audit
trail handing back garbage instead of failing loudly, which is the worst way for
this particular component to be wrong.

Reads materialise their rows inside the lock before yielding, so a caller that
abandons a generator half-way cannot hold the connection either.

*Found by* a test that was flaky 3 runs in 5. The flake was the bug.

### Appends are serialised

Deriving the next sequence number and the previous hash, then inserting, is a
read-modify-write. Two interleaving produce a duplicate sequence number or a
forked chain. Under eight concurrent writers this store lost **251 of 320
entries** and broke its own chain — the worst class of bug for an audit trail,
because the damage is invisible until someone verifies. Every append now runs in
a `BEGIN IMMEDIATE` transaction behind a process lock.

*Rejected:* deriving the sequence from `COUNT(*)`. It is wrong the moment
anything is removed, and would silently reuse a number.

### Writes are ordered write-ahead

`cart_allowed` is recorded **before** the rail is called, so a crash between the
two leaves something for reconciliation. `debit_settled` is recorded **before** the
running totals move, because those totals are rebuilt from the ledger — a counter
*ahead* of the record survives as a permanent overspend allowance. Both orderings
are asserted by tests that fail the write on purpose.

### The nonce is consumed at authorisation, not settlement

A real rail reports `settled=False` until the customer authorises on their own
device. Consuming the nonce on settlement left a window in which the same cart
could be presented repeatedly, placing an order each time. **Found by running
against Razorpay test mode; the simulator settles synchronously and hid it for
days.** See [INCIDENTS.md](INCIDENTS.md) §7.

### The merchants and the products are configuration, not source

Five merchants were compiled in, four of them Indian food delivery. Adopting
this meant forking it, and the gate's most interesting rule — check declared
categories against what an acquirer actually underwrote — was unreachable for
anyone whose merchants were not `zomato`.

Both load from TOML. `WARRANT_MERCHANTS` and `WARRANT_CATALOG`, or objects
passed to `evaluate()` and `Warrant()` directly. The second keeps the gate a
pure function of its arguments, which was always its stated property and was
quietly untrue while it read a module global.

A path that was *asked for* and does not exist raises. Only the absence of any
configuration falls back to the bundled records — a typo must not hand you a
registry full of merchants you have never heard of.

### The convenience layer adds no policy

`Warrant.check()` and `Warrant.spend()` call the same `gate.evaluate()`
everything else calls. A facade that could change a verdict would be a second
place for authorization logic to live, which is how two places drift apart.

It did drift once, in the direction that matters: `check()` honoured the
registry it was handed and `spend()` read the process-wide one, so a preview
could say *allow* where the spend said *block*. A preview that runs different
code is a preview of nothing. The registry belongs to the `Authorizer` — one per
merchant deployment — and both paths read it.

### Retries are idempotent in two layers, and one of them is only a cache

The same basket sent three times charged three times. Every call minted a fresh
cart nonce, so a retry built a *different* cart, which the gate has no reason to
refuse. The engine's replay guard was never reached.

`spend()` takes an `idempotency_key`; the service reads `Idempotency-Key`. A
repeat returns the first decision without touching the rail — returning a
refusal instead would be safe and useless, because a caller told "blocked:
replay" reasonably concludes the payment failed and tries again. And the cart
nonce is *derived* from the key, so when the bounded cache evicts an entry the
gate's own `replay.cart_nonce` check refuses the repeat. The cache is the
convenience; the nonce is the safety net.

The slot is single-flight. Checking the cache and filling it were two critical
sections, so eight simultaneous retries all missed, all authorized, and seven
came back refused — the money right and the answer wrong.

### Authentication is required to construct, not to remember

`warrant_router` raises unless it is given authentication. A service that mints
spending permissions must not become usable-because-reachable when somebody
forgets an argument, so running open is possible and has to be typed:
`auth=NO_AUTH`.

Health and readiness are never guarded. An orchestrator holds no credential, and
a probe that returns 401 reports the process as dead.

### Logs carry digests, never contents

The ledger is the record of what was decided. Logs are for whoever is on call,
and they are read by tools, tailed into aggregators, and increasingly fed to
language models.

Half the catalogue here carries an instruction inside a *product name*, and a
refused basket is exactly the one somebody investigates. Writing that name into
a log line puts an injected instruction in front of every tool that reads logs —
a longer and far less guarded path than the one the gate defends. So a decision
is logged by digest, verdict and failed rules. The names are in the ledger,
where nothing reads them by accident. Neither is the person's utterance, which
is theirs.

### The console is a demonstration and the service is the product

`warrant serve` has a button that tampers with its own ledger. That belongs in a
demonstration and must not be one flag away from something in front of money, so
`warrant api` is a different command serving a different app — `service.py`, not
`api.py`. The console's endpoints for replaying scripted baskets and breaking
its own chain do not exist there.

### Fail closed, with nothing to fail

Warrant refuses rather than waves through — safe only because the binding path has
**no external dependencies**: no network, no model, no database read, not even a
clock it does not receive as an argument. `test_availability.py` makes every socket
call raise and asserts verdicts still come back and all eleven rules still fire.

p50 **252µs**, p95 **1.5ms**, p99 **2.4ms**.

---

## Where the model runs

| | job | authority | on failure |
| --- | --- | --- | --- |
| `derive.py` | utterance → checkable scope | proposes only; envelope clamps it; a human approves it; the person's key signs it | deterministic fallback, narrowed hard, labelled `fallback` |
| `divergence.py` | is this basket what was asked for? | **advisory only** — can raise ALLOW to ESCALATE, nothing else | no opinion; recorded as skipped |

Everything else is arithmetic: signatures, ceilings, counts, expiry, replay, MCC,
the block/allow decision, the ledger. `llm.py` degrades **live → transcript →
fallback** and records which path ran on every proposal, so a replayed
interpretation is never presented as a live one.

---

## Modules

```
engine/warrant/
  canon.py       RFC 8785 subset; rejects floats
  crypto.py      Ed25519 over canonical bytes; seeded keys for reproducibility
  models.py      Intent → Cart → Receipt, bound by content address
  merchants.py   acquirer-assigned MCC registry
  gate.py        the only layer that can block; pure, replayable
  derive.py      utterance → scope, clamped by a hard envelope
  divergence.py  the advisory judge
  agent.py       a real model shopping; never told the limits
  llm.py         live → transcript → fallback, always labelled
  providers.py   Anthropic and Groq; model overrides scoped per provider
  authorize.py   orchestration; write-ahead ordering
  chain.py       append-only hash chain; refusals are entries
  evidence.py    the chain as a Razorpay dispute submission
  interop.py     the chain in AP2 vocabulary, W3C-VC shaped
  rails/         Razorpay test mode; a real UPI mandate; deterministic simulator
  merchants_shopify.py  a real store's catalogue and real orders
  demo.py        the five-basket scenario, pinned identical everywhere
  cli.py         warrant demo / serve / api / verify / trace
  client.py      the front door: permit / check / spend. Adds no policy
  service.py     the router a company mounts. Auth required to construct
  observability.py  structured logs; digests in, contents never
  catalog.py     the products, loaded from the deployer's TOML
  storefront.py  a real merchant's catalogue, snapshotted from their storefront
  py.typed       PEP 561; without it every annotation here is invisible
  api.py         the console's HTTP surface; a view onto the engine, never a second one
```

`bench/` is the labelled corpus and harness. `console/` is a view onto the engine —
every verdict it renders came from `gate.evaluate()`. `.verify/` holds the gates:
secrets, tokens, contrast, overlap, layout, browser, and `docs-examples`, which
executes every code block in the documentation because prose is not otherwise
checked by anything.
