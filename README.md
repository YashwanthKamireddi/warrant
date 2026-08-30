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

Only the human's key can *widen* what may be spent, so the authorizer cannot
produce a chain that verifies as in-scope for a purchase nobody permitted.

**Being precise about what that buys, because the tempting claim is wrong:** a
compromised authorizer can still skip its own gate and call the rail directly.
The rail enforces the blocked *amount*, not the category allowlist, so it could
spend the remaining block on anything. The chain does not prevent that — it makes
it provable afterwards, because the receipt names a cart, the cart names an
intent, and anyone with the subject's public key can see the purchase fell
outside what was signed. **Detection with attribution, not prevention.**

Preventing it outright needs the *rail* to enforce scope, not just an amount —
which is the layer NPCI's UAP is being designed to occupy. This is what that
layer has to do; it runs merchant-side today because that is where it can run.

---

## Results

405 labelled sessions, four policies, one seed. `make bench` reproduces this
exactly on any machine.

| policy | violations caught | leaked | legitimate spend blocked |
| --- | --- | --- | --- |
| `no_gate` — today's default | 0.0% | ₹239,290 | ₹0 |
| `amount_only` — a ceiling and nothing else | 13.3% | ₹142,285 | ₹0 |
| `model_only` — ask a model if the basket looks right | 0.2% | ₹238,791 | ₹0 |
| **`warrant`** | **80.0%** | **₹28,900** | **₹0** |

**Decision latency** — this sits in the payment path, so it is measured, not
assumed: **p50 252µs, p95 1.5ms, p99 2.4ms** across 495 in-process decisions with
no model call. A model call adds its own round trip and only ever runs on carts
that already cleared every binding check.

### Where this loses

Every number above is measured on data this repository generates. Discount it
accordingly — and here is exactly where.

**`injection_subtle`: 0 of 45. `semantic_drift`: 0 of 45.** Both sit inside every
bound the subject signed — right merchant, right category, under every ceiling —
so no arithmetic touches them, and the payload in `injection_subtle` is phrased to
evade the instruction-text heuristic. Only reading the basket against the
instruction catches either, and no model was reachable on this run. **These two
rows are the only ones a live model moves.** Every other row is arithmetic.

**`injection_oos` is scored separately on purpose.** Those payloads are blocked,
but on the *category* bound — nothing recognised the payload. Folding them into an
"injection caught" figure would be the flattering way to report this, and it is
how most demos of this kind are reported.

**`legitimate 45/45` and `friction ₹0` are close to circular.** This corpus defines
a legitimate basket as one inside the scope, and the policy allows baskets inside
the scope. Read that row as evidence the gate is not over-firing, and nothing
more. It is not evidence real customers would not be blocked, because no real
customer generated it.

**The mechanical categories are exact by construction, not by cleverness.** A
ceiling comparison cannot be 97% right. Read `scope_drift`, `replay`, `expired`
and the rest as evidence the rules are wired up, not that the approach is smart.

### Known limitations, stated plainly

**Categories come from the merchant's own catalog. Half of that hole is now
closed, and it is worth being exact about which half.**

Card networks solved the first half decades ago: an acquirer assigns a merchant a
**category code** at onboarding, and the merchant does not pick it. Razorpay does
this today — it is the MCC on every account it underwrites. `merchants.py` holds
that registry and `merchant.mcc_scope` is a binding rule, so a merchant cannot
serve a mandate scoped to a category its acquirer never underwrote it for. An
unregistered merchant fails closed: nothing is backed, rather than anything being
allowed.

What stays open is a merchant mislabelling *within* its own category. Zomato is
MCC 5812; a power bank listed there as `food_beverage` still passes. Catching that
needs the item actually purchased, which no metadata layer can see — it needs the
rail. `test_the_known_gap_is_documented_by_a_test` asserts the gap so nobody later
mistakes the MCC rule for a complete fix.

**The heuristic that catches `injection_blunt` is shallow and beatable.** That is
the point of `injection_subtle` scoring zero next to it. The heuristic is an
early-warning signal, never the defence; the defence is that nothing a model
emits can widen a signed scope.

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

## Interoperability with AP2

The fair criticism is that Google's AP2 already defines a chained mandate model —
Intent, Cart, Payment — with 60-plus partners, and NPCI's UAP will do agent
authorisation at the network level. So why a merchant-side implementation?

**Because those specify what the credential is, not who checks it.** AP2
standardises a signed, chained, non-repudiable record of what a user authorised.
It does not say which rules a merchant evaluates before settlement, what happens
when a basket sits inside every stated bound and is still wrong, or how a refusal
is recorded. That gap is the gate, the judge and the ledger here.

`GET /api/sessions/{id}/ap2` emits the chain in AP2's vocabulary inside a W3C
Verifiable-Credentials envelope. `tests/test_interop.py` reconstructs a verifier's
job from the exported document alone — canonicalise, check the proof against the
published key, follow the digests — and confirms it holds.

**It is shape-compatible, not certified interop**, and the three places the models
genuinely differ travel *inside* the document under a `warrant:` namespace rather
than being left for someone to discover. The one that matters: AP2 has the user
sign every Cart Mandate; Warrant has the authoriser sign it and requires the
user's co-signature only above a step-up threshold — because Reserve Pay exists so
a user does not re-authenticate per purchase, and a chain demanding a user
signature on every cart cannot express standing delegation at all. Above the
threshold the two converge exactly.

## What happens when this is unavailable

A fair question about putting a gate in the payment path: fail open and it is
decorative, fail closed and it is a single point of failure for a payments
company.

Warrant **fails closed** — no verdict, no debit — and that is safe because the
binding path has **no external dependencies at all**. No network, no model, no
database read, not even a clock it does not receive as an argument.
`gate.evaluate()` is a pure function of `(intent, cart, state, now, key)`, so it
cannot be down unless the merchant's own process is down, at which point there is
no checkout to protect. It is designed to be embedded in-process, not called over
a network.

`tests/test_availability.py` holds that to account: it makes every socket call
raise, then asserts verdicts still come back, every rule still fires, evaluation
never mutates the state it is given, and the rail is never reached when no verdict
exists.

The model is advisory and degrades explicitly. The rail reports failures rather
than raising them. The ledger is local and append-only. Nothing in the path that
can say **no** depends on anything that can be unreachable.

**Decision latency**: p50 252µs, p95 1.5ms, p99 2.4ms.

## Honest limits

- **Disputes cannot be created through Razorpay's API** — they are bank-initiated.
  The evidence pack is assembled and verified in full, and maps onto the real
  contest schema, but submitting it needs a real dispute.
- **Replay protection consumes a nonce at authorisation, not settlement.** A real
  rail reports `settled=False` until the customer authorises on their own device,
  so consuming the nonce on settlement leaves a window in which the same cart can
  be presented repeatedly, placing an order each time. Found by running against
  Razorpay test mode; the simulator settles synchronously and never showed it.
- **Writes are ordered write-ahead.** `cart_allowed` is recorded before the rail
  is called, so a crash between the two leaves something for reconciliation to
  find. `debit_settled` is recorded before the running totals move, because those
  totals are rebuilt from the ledger — a counter ahead of the record would survive
  as a permanent overspend allowance, whereas a counter behind it is corrected by
  the next replay. Both orderings are asserted by tests that fail the write on
  purpose.
- **A payment cannot be completed server to server.** `--rail razorpay` creates
  **real** Orders and Payment Links in your test account and refuses to start
  against a non-test key, but reports `settled=False` until the rail confirms a
  capture. A script cannot fake a customer authorising on their own device, and
  that property is what makes the rail trustworthy. The console offers the same
  choice, and `make browser-razorpay` asserts a real `order_…` id and an
  `https://rzp.io/…` link come back — deliberately outside `make verify`, which
  must pass for anyone who clones the repo without credentials.
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
| `audit-secrets` | no credential material tracked, staged, or anywhere in git history |
| `lint` | ruff over engine, bench and tests |
| `test` | 162 tests: signature forgery, chain tampering, replay, envelope escape, judge authority, evidence self-verification, rail error handling, write ordering |
| `typecheck` | the console compiles under `strict` |
| `audit-tokens` | no colour outside `:root`, no undefined token, no hex in a component |
| `audit-contrast` | all 29 rendered pairs meet WCAG AA, computed from the tokens |
| `audit-overlap` | nothing spills outside its box or paints over a sibling, across 6 states |
| `browser` | the frame holds at 5 viewports; the real flow runs with no console errors, and the console's verdicts match what `warrant demo` prints |

Screenshots of every state land in `.verify/shots/`.

Three of those gates exist because looking at the thing in a browser found bugs
a green build could not:

- the storefront had drifted by one SKU between two files while all 75 tests passed
- the top bar reported "credentials configured" while actually replaying a transcript
- a component rendered `className="signer seal"`, and `seal` was a standalone rule
  elsewhere setting a 46px circle, so the label was clamped and its text spilled
  across the content beneath it

The last one is why `audit-overlap` checks *content spilling out of its box*, not
just sibling overlap — sibling-box overlap does not catch a cascade collision,
which was verified by reintroducing the bug and watching the detector name it:
`span.link-signer.seal spills 145x0px outside its box`.

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

**[ARCHITECTURE.md](ARCHITECTURE.md)** — trust boundaries and the decision record.
**[INCIDENTS.md](INCIDENTS.md)** — what broke, kept as it happened.

Built for the Razorpay AI Buildathon, September 2026.
