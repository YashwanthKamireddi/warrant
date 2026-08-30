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
  llm.py         live → transcript → fallback, always labelled
  authorize.py   orchestration; write-ahead ordering
  chain.py       append-only hash chain; refusals are entries
  evidence.py    the chain as a Razorpay dispute submission
  interop.py     the chain in AP2 vocabulary, W3C-VC shaped
  rails/         Razorpay test mode; deterministic simulator
  api.py         HTTP surface; a view onto the engine, never a second one
```

`bench/` is the labelled corpus and harness. `console/` is a view onto the engine —
every verdict it renders came from `gate.evaluate()`. `.verify/` holds the gates:
secrets, tokens, contrast, overlap, layout, browser.
