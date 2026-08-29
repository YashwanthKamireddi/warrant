# Warrant

**No agent spends without one.**

An authorization layer for agent-initiated payments. Every rupee an agent spends
traces back to a scope a human signed — checked *before* settlement, provable
*after* dispute.

```bash
make install
make demo      # the five-cart scenario, no API key, no network
make bench     # 405 labelled sessions, four policies
make console   # the control plane at http://127.0.0.1:8787
```

---

## The problem

Since February 2026, Razorpay and NPCI have run agentic UPI payments in
production on Claude, with Zomato, Swiggy and Zepto. They use **UPI Reserve Pay**:
the customer blocks funds once, and the agent debits against that block
repeatedly with no further PIN.

That leaves two holes, and both are open today.

**Nothing checks the debit against the intent before the money moves.** The
customer said "order chai and samosas for my team, under ₹1,000". The block is
authorized. What stops a ₹499 charge for something nobody asked for?

**When the dispute lands, the merchant has no evidence.** An agent-initiated
payment has no device fingerprint, no browsing session, no click. Chargeback
reason codes have no category for *correctly authorized agent, wrong outcome*.
The merchant eats it.

Warrant closes both with the same object: a signed chain from the words a person
said to the rupee that moved.

```
IntentMandate    signed by the USER's device key
    │            "spend up to ₹1,000 at Zomato on food, for 2 hours"
    ▼
CartMandate      signed by the AUTHORIZER
    │            "I checked this basket against that intent. It fits."
    ▼
DebitReceipt     signed by the AUTHORIZER
                 "this payment settled that cart under that intent"
```

The asymmetry is the point. Only the human's key can widen what may be spent.
The authorizer can attest that something already permitted was checked; it
cannot grant authority it was never given.

---

## Results

405 labelled sessions, four policies, one seed. `make bench` reproduces this
exactly on any machine.

| policy | violations caught | leaked | legitimate spend blocked |
| --- | --- | --- | --- |
| `no_gate` — today's default | 0.0% | ₹232,890 | ₹0 |
| `amount_only` — a ceiling and nothing else | 16.7% | ₹135,885 | ₹0 |
| `model_only` — ask a model if the basket looks right | 0.3% | ₹232,391 | ₹0 |
| **`warrant`** | **87.5%** | **₹24,750** | **₹0** |

### Where this loses

The number above is measured on data this repository generates. You should
discount it accordingly, and here is exactly where.

**`semantic_drift`: 0 of 45.** A basket at the right merchant, in the right
category, under every ceiling — and not what was asked for. No arithmetic
distinguishes that from a legitimate order. Only reading the basket against the
instruction does, and with no model reachable Warrant catches none of them. That
row is printed in the same table as the rest, and it is the only row a live model
moves. Every other row is arithmetic and will not change.

**The mechanical categories are exact by construction, not by cleverness.** A
ceiling comparison cannot be 97% right. Read `scope_drift`, `replay`, `expired`
and the rest as evidence the rules are wired up, not as evidence the approach is
smart.

**The corpus is eight-ninths violations**, so a bare accuracy figure would be
meaningless. That is why the table reports money and not accuracy.

---

## Where the model is, and where it isn't

Razorpay's brief asks for *the right tool in the right place, and where you chose
not to use one*. Here is the boundary, exactly.

A model runs in **two** places:

1. **Scope derivation** — turning "order chai for my team, under ₹1,000" into a
   machine-checkable scope. Wrapped in four constraints: a closed category
   taxonomy, a hard envelope it can only narrow, human approval in plain English,
   and the user's key. `tests/test_derive.py` feeds the narrowing step the output
   a hostile model would produce — 10⁹-paise ceilings, invented merchants,
   wildcard allowlists, year-long expiries — and asserts none of it escapes.

2. **Semantic divergence** — does this basket plausibly fulfil that instruction?
   `DivergenceFinding.as_check()` hard-codes `binding=False`, so a divergent
   finding escalates to a human and a consistent one adds nothing. **If an
   injected product name convinces this judge to say "consistent", the outcome is
   byte-identical to the judge never running.** There is no prompt that makes it
   grant authority, because it holds none.

Everything else is deterministic code: signatures, ceilings, counts, expiry,
replay, the block/allow decision, the ledger. The gate runs **first and alone** —
a cart that already failed a binding check never reaches a model at all.

The demo shows this working. The injected cart is refused with
`model_used=False`; it is blocked on the category bound, not on having spotted
the payload. Delete the injection heuristic entirely and it still fails.

---

## Honest limits

- **Disputes cannot be created through Razorpay's API** — they are bank-initiated.
  The evidence pack is assembled and verified in full, and maps onto the real
  contest schema, but submitting it needs a real dispute.
- **A payment cannot be completed server to server.** `--rail razorpay` creates
  **real** Orders and Payment Links in your test account and refuses to start
  against a non-test key, but reports `settled=False` until the rail confirms a
  capture. A script cannot fake a customer authorising on their own device, and
  that property is what makes the rail trustworthy.
- **The bundled transcript is authored, not captured.** With no API key, scope
  derivation replays it so `make demo` works offline. Every interpretation is
  labelled with the path it actually took — `live`, `transcript` or `fallback` —
  in the ledger, the CLI and the console. A replayed interpretation is never
  presented as a live one.

---

## Verifying it

```bash
make verify
```

Runs, in order, and fails on the first problem:

| gate | what it proves |
| --- | --- |
| `lint` | ruff over engine, bench and tests |
| `test` | 82 tests: signature forgery, chain tampering, replay, envelope escape |
| `typecheck` | the console compiles under `strict` |
| `audit-tokens` | no colour outside `:root`, no undefined token, no hex in a component |
| `audit-contrast` | all 29 rendered pairs meet WCAG AA, computed from the tokens |
| `browser` | the frame holds at 5 viewports; the real flow runs with no console errors, and the console's verdicts match what `warrant demo` prints |

Screenshots of every state land in `.verify/shots/`.

Two of those gates exist because looking at the thing in a browser found bugs
that a green build could not: the storefront had drifted by one SKU between two
files while all 75 tests passed, and the top bar reported "credentials
configured" while actually replaying a transcript.

---

## Layout

```
engine/warrant/
  canon.py       RFC 8785 subset. Rejects floats — money is integer paise.
  crypto.py      Ed25519 over canonical bytes. Seeded keys for reproducibility.
  models.py      Intent → Cart → Receipt, bound by content address.
  gate.py        The only layer that can block. Pure, replayable, no model.
  derive.py      Utterance → scope, narrowed by a hard envelope.
  divergence.py  The advisory judge. Can escalate; cannot authorise.
  authorize.py   Orchestration. Gate first, model second, ledger always.
  chain.py       Append-only hash chain. Refusals are entries, not silences.
  evidence.py    The mandate chain as a dispute submission.
  rails/         Razorpay test mode, and a deterministic simulator.
bench/           The labelled corpus, the four policies, the harness.
console/         The control plane. A view onto the engine, never a second one.
.verify/         Token, contrast, layout and browser gates.
```

---

Built for the Razorpay AI Buildathon, September 2026.
