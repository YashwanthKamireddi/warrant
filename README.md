<div align="center">

# Warrant

### No agent spends without one.

**An authorization layer for agent-initiated payments.**
Every rupee an agent spends traces back to a scope a human signed —
checked *before* settlement, provable *after* dispute.

<br>

[![tests](https://img.shields.io/badge/tests-347%20passing-0b6e54?style=flat-square)](#verifying-it)
[![gates](https://img.shields.io/badge/gates-10%20green-0b6e54?style=flat-square)](#verifying-it)
[![latency](https://img.shields.io/badge/p50-under%20300µs-16264f?style=flat-square)](#results)
[![rail](https://img.shields.io/badge/rail-Razorpay%20test%20mode-16264f?style=flat-square)](#the-real-rail)
[![python](https://img.shields.io/badge/python-3.12+-16264f?style=flat-square)](pyproject.toml)

<br>

*Built for the Razorpay AI Buildathon · Track 01, AI Growth & Agentic Commerce*

</div>

---

## The problem

Since **February 2026**, Razorpay and NPCI have run agentic UPI payments in
production on Claude — with Zomato, Swiggy and Zepto. They use **UPI Reserve Pay**:
the customer blocks funds once, and the agent then debits against that block
repeatedly **with no further PIN**.

That leaves two holes, and both are open today.

> **Nothing checks the debit against the intent before the money moves.**
> The customer said *"chai and samosas for my team, under ₹1,000."* The block is
> authorized. What stops a ₹499 charge for something nobody asked for?

> **When the dispute lands, the merchant has no evidence.**
> An agent-initiated payment has no device fingerprint, no browsing session, no
> click. Chargeback reason codes have no category for *correctly authorized agent,
> wrong outcome*. The merchant eats it.

Warrant closes both with one object: **a signed chain from the words a person said
to the rupee that moved.**

<br>

<div align="center">
<img src="docs/screenshots/02-decisions.png" alt="Five baskets checked against a signed permission" width="100%">
<br><em>Five baskets, one signed permission. Every verdict names the rule that produced it.</em>
</div>

---

## How it works

```
IntentMandate    signed by the PERSON's device key
    │            "up to ₹1,000 at Zomato on food, for 2 hours"
    ▼
CartMandate      signed by the AUTHORISER
    │            "I checked this basket against that intent. It fits."
    ▼
DebitReceipt     signed by the AUTHORISER
                 "this rail payment settled that cart under that intent"
```

Each document binds to the one above it by **content address** — `im_a3f2…` *is*
the first 16 hex of the intent's digest, so an id cannot be forged or reassigned.

**Only the person's key can widen what may be spent.** The authoriser can attest
that something already permitted was checked; it cannot grant authority it was
never given.

<details>
<summary><b>Being precise about what that buys — because the tempting claim is wrong</b></summary>

<br>

A compromised authoriser **can** still skip its own gate and call the rail. The
rail enforces the blocked *amount*, not the category allowlist, so it could spend
the remaining block on anything. The chain does not prevent that — it makes it
**provable afterwards**, because the receipt names a cart, the cart names an
intent, and anyone with the subject's public key can see the purchase fell
outside what was signed.

**Detection with attribution, not prevention.**

Preventing it outright needs the *rail* to enforce scope, not just an amount —
which is the layer NPCI's UAP is being designed to occupy. This is what that layer
has to do; it runs merchant-side today because that is where it can run.

</details>

---

## Use it in your own product

Warrant is not a demo of a payment flow — it is a layer you put in front of one.
Nothing in it knows about any particular merchant, country or rail.

```python
import time

from warrant import Warrant
from warrant.models import Scope

now = int(time.time())
warrant = Warrant(merchants="warrant.example.toml")

# Once, when the person approves. These bounds normally come from a form.
permission = warrant.permit("lunch for the team", scope=Scope(
    merchants=("acme-grocers",),
    categories=("food_beverage",),
    max_total_paise=100_000,
    max_per_txn_paise=50_000,
    max_txns=3,
    not_before=now,
    expires_at=now + 7200,
))

# Every time the agent proposes a basket.
sandwich = {"sku": "sandwich", "category": "food_beverage", "qty": 2, "unit_paise": 24_000}
cable = {"sku": "cable", "category": "electronics", "qty": 1, "unit_paise": 29_900}

assert warrant.check(permission, "acme-grocers", [sandwich]).allowed
assert not warrant.check(permission, "acme-grocers", [cable]).allowed

# Charge it. Pass an idempotency key to anything that can be retried.
paid = warrant.spend(permission, "acme-grocers", [sandwich], idempotency_key="order-4417")
assert paid.settled

warrant.close()
```

Or mount the service into an app you already have:

```python
import secrets

from fastapi import FastAPI

from warrant import Warrant
from warrant.service import ApiKeyAuth, warrant_router

app = FastAPI()
app.include_router(
    warrant_router(
        Warrant(merchants="warrant.example.toml"),
        auth=ApiKeyAuth([secrets.token_urlsafe(32)]),
    )
)
```

`warrant_router` **refuses to be constructed without authentication**. A service
that mints spending permissions should not become usable-because-reachable
because an argument was forgotten; running open is possible and has to be
spelled `auth=NO_AUTH`.

### Everything is a file you supply

| | | |
|---|---|---|
| Merchants and their ISO 18245 codes | `WARRANT_MERCHANTS` | [`warrant.example.toml`](warrant.example.toml) |
| Products | `WARRANT_CATALOG` | [`catalog.example.toml`](catalog.example.toml) |
| API keys | `WARRANT_API_KEYS` | — |

The bundled Indian merchants and their chai exist so a clone runs with nothing
configured, and so the benchmark measures the same thing on every machine. They
are a default, not a dependency: start the console with `WARRANT_CATALOG` set
and it sells whatever you sell.

**[Full integration guide →](docs/INTEGRATION.md)** — three calls, the verdict
table, retries, endpoints, and a production-notes section that says plainly
which defaults are wrong for a deployment.

---

## Results

**540 labelled sessions, four policies, one seed.** `make bench` reproduces this
exactly on any machine.

| policy | violations caught | leaked | legitimate spend blocked |
| :--- | ---: | ---: | ---: |
| `no_gate` — today's default | 0.0% | ₹291,555 | ₹0 |
| `amount_only` — a ceiling and nothing else | 14.8% | ₹155,923 | ₹0 |
| `model_only` — ask a model if the basket looks right | 0.8% | ₹289,559 | ₹160 |
| **`warrant`** | **81.8%** | **₹27,280** | **₹0** |

**Reproducible without paying for anything.** The engine runs on Anthropic or on
Groq's free tier — same interface, and the engine cannot tell which answered. A
submission whose numbers can only be checked by someone holding a paid API key is
a submission whose numbers cannot really be checked. Drop a free
[Groq key](https://console.groq.com/keys) into `.env` and run `make bench-live`
yourself.

Measured, committed and checked on every build: `bench/RESULTS.json` is written by
`make bench`, the table above quotes it, and **`make docs-check` fails the build if
the two disagree.** The numbers in this document cannot drift away from the numbers
the code produces.

**Decision latency** — this sits in the payment path, so it is measured, not
assumed: **p50 under 300µs and p99 under 3ms** across 540 in-process decisions with
no model call. Stated as bounds rather than a point, because a hardware figure
quoted to the microsecond is a claim about my laptop.

### Where this loses

Every number above is measured on data this repository generates. Discount it
accordingly — and here is exactly where.

**`injection_subtle`: 0 of 45. `semantic_drift`: 0 of 45.** Both sit inside every
bound the subject signed — right merchant, right category, under every ceiling — so
no arithmetic touches them, and the payload in `injection_subtle` is phrased to
evade the instruction-text heuristic. Only reading the basket against the
instruction catches either, and the committed run had no model reachable.

**So I ran them against a live model, and the result was worse than I expected.**
36 cases, 72 calls, `openai/gpt-oss-120b` on Groq — `bench/RESULTS-live-sample.json`:

| category | offline | with a live model |
| :--- | ---: | ---: |
| `semantic_drift` | 0 / 45 | **2 / 12** |
| `injection_subtle` | 0 / 45 | **0 / 12** |
| `legitimate`, no false blocks | 45 / 45 | 12 / 12 |

A model moves `semantic_drift` from nothing to roughly one in six, and does not
touch `injection_subtle` at all. And `model_only` — the policy that trusts the
model to decide — blocked **5 legitimate baskets** for ₹2,200 of killed
conversion while catching 4.2% of violations.

**That result argues for this architecture rather than against it.** If the model
were reliable here, you could let it block. It isn't, so it can only escalate, and
the deterministic gate stays binding. The honest position is that these two
categories are genuinely hard and nobody should claim otherwise.

Results also vary between runs, because the model does. The committed
`RESULTS.json` is the offline run for exactly that reason: it is the one a
reviewer can reproduce byte-for-byte.

**`injection_oos` is scored separately on purpose.** Those payloads are blocked, but
on the *category* bound — nothing recognised the payload. Folding them into an
"injection caught" figure would be the flattering way to report this, and it is how
most demos of this kind are reported.

**`legitimate 45/45` and `friction ₹0` are close to circular.** This corpus defines
a legitimate basket as one inside the scope, and the policy allows baskets inside
the scope. Read that row as evidence the gate is not over-firing, and nothing more.

**The mechanical categories are exact by construction, not by cleverness.** A ceiling
comparison cannot be 97% right.

---

## Where the model runs — and where it deliberately doesn't

Razorpay's brief asks for *the right tool in the right place, **and where you chose
not to use one***. Here is the boundary, exactly.

| | job | authority | on failure |
| :--- | :--- | :--- | :--- |
| `derive.py` | utterance → checkable scope | **proposes only** — a hard envelope clamps it, a human approves it in plain English, the person's key signs it | deterministic fallback, narrowed hard, labelled |
| `divergence.py` | is this basket what was asked for? | **advisory only** — can raise ALLOW to ESCALATE, nothing else | no opinion, recorded as skipped |

Everything else is arithmetic: signatures, ceilings, counts, expiry, replay, MCC,
the block/allow decision, the ledger.

> **`DivergenceFinding.as_check()` hard-codes `binding=False`.**
> If an injected product name convinces the judge to return `consistent`, the
> outcome is **byte-identical to the judge never running**. There is no prompt that
> makes it grant authority, because it holds none.

The gate runs **first and alone** — a cart that already failed a binding check never
reaches a model at all. The demo shows it: the injected cart is refused with
`model_used=False`. **It is blocked on the category bound, not on having spotted the
payload.** Delete the injection heuristic entirely and it still fails.

---

## The real rail

`--rail razorpay` creates **real Orders and Payment Links** in your test account and
refuses to start against any key not beginning `rzp_test_`.

<div align="center">
<img src="docs/screenshots/07-razorpay.png" alt="A real Razorpay order and payment link" width="100%">
<br><em>A real order in Razorpay test mode, with a live payment link.</em>
</div>

<br>

It reports `settled=false` until the rail confirms a capture, because **a script
cannot fake a customer authorising on their own device** — and that property is
exactly what makes the rail trustworthy.

> It is also what found a **double-spend** the simulator had hidden for days.
> Replay protection consumed a cart's nonce on *settlement*; a real rail settles
> asynchronously, leaving a window where the same cart could be presented again and
> again, placing an order every time. See [INCIDENTS.md](INCIDENTS.md) §7.

---

## The console

<table>
<tr>
<td width="50%"><img src="docs/screenshots/03-ledger.png" alt="Hash-chained ledger"><br><em><b>Ledger</b> — refusals are entries, not silences.</em></td>
<td width="50%"><img src="docs/screenshots/05-tampered.png" alt="Tamper detection"><br><em><b>Tampered</b> — entry 5 onward orphaned, with both hashes named.</em></td>
</tr>
<tr>
<td width="50%"><img src="docs/screenshots/04-evidence.png" alt="Dispute evidence pack"><br><em><b>Dispute evidence</b> — mapped to Razorpay's real contest schema.</em></td>
<td width="50%"><img src="docs/screenshots/06-ap2.png" alt="AP2 export"><br><em><b>AP2 export</b> — with the divergences carried inside the document.</em></td>
</tr>
</table>

---

## Interoperability with AP2

The fair criticism is that Google's AP2 already defines a chained mandate model —
Intent, Cart, Payment — with 60-plus partners, and NPCI's UAP will do agent
authorisation at the network level. So why a merchant-side implementation?

> **Because those specify what the credential *is*, not who *checks* it.**

AP2 standardises a signed, chained, non-repudiable record of what a user authorised.
It does not say which rules a merchant evaluates before settlement, what happens when
a basket sits inside every stated bound and is still wrong, or how a refusal is
recorded. **That gap is the gate, the judge and the ledger here.**

`GET /api/sessions/{id}/ap2` emits the chain in AP2's vocabulary inside a W3C
Verifiable-Credentials envelope, and the console's **AP2 export** tab renders it next
to the divergences. `tests/test_interop.py` reconstructs a verifier's job from the
exported document alone — canonicalise, check the proof against the published key,
follow the digests — and confirms it holds.

It is **shape-compatible, not certified interop**, and the three places the models
genuinely differ travel *inside* the document under a `warrant:` namespace rather
than being left for someone to discover.

---

## Run it

```bash
git clone https://github.com/YashwanthKamireddi/warrant && cd warrant

make demo      # the five-cart scenario. no API key, no network, no install step
make bench     # 540 labelled sessions, four policies
make console   # the walkthrough at http://127.0.0.1:8787
make verify    # every gate, from a clean checkout
```

To run the authorization service rather than the console:

```bash
export WARRANT_API_KEYS=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
uv run warrant api --port 8080 --ledger ./warrant.db --merchants ./warrant.toml
```

`warrant serve` is the demonstration and has a button that tampers with its own
ledger. `warrant api` is the thing that goes in front of money. They are
different commands on purpose.

`make demo` works on a bare clone — `uv` resolves the environment on first run. The
console and browser targets install their own prerequisites, so there is no step to
remember and no order to get right. Verified by cloning into a temp directory and
running `make verify` cold.

<details>
<summary><b>Optional: run against real Razorpay test mode</b></summary>

<br>

```bash
cp .env.example .env      # add your rzp_test_ key id and secret
uv run warrant demo --rail razorpay
make browser-razorpay     # asserts a real order_… and an https://rzp.io/… link
```

The rail refuses any key not beginning `rzp_test_`, so it cannot touch live money.

</details>

---

## Verifying it

```bash
make verify
```

Runs in order, and fails on the first problem:

| gate | what it proves |
| :--- | :--- |
| `audit-secrets` | no credential material tracked, staged, or anywhere in git history |
| `lint` | ruff over engine, bench and tests |
| `test` | 347 tests: signature forgery, chain tampering, replay, envelope escape, judge authority, evidence self-verification, rail error handling, write ordering, concurrency, merchant registry loading, mandate lifecycle, Shopify catalog boundary, the documented SDK example |
| `typecheck` | the console compiles under `strict` |
| `docs-check` | every number in this README matches what the code measures |
| `docs-examples` | fail if any code example in the documentation does not run. Prose is not executed, so nothing else can catch a README that has quietly stopped being true |
| `audit-tokens` | no colour outside `:root`, no undefined token, no hex in a component |
| `audit-contrast` | all 37 rendered pairs meet WCAG AA, computed from the tokens |
| `audit-overlap` | nothing spills outside its box or paints over a sibling, across 6 states |
| `browser` | the frame holds at 5 viewports; the real flow runs with no console errors, and the console's verdicts match what `warrant demo` prints |

Screenshots of every state land in `.verify/shots/`.

<details>
<summary><b>Why these gates exist — each traces to a real bug a green build did not catch</b></summary>

<br>

- **The storefront had drifted by one SKU** between two files while all 75 tests passed
- **The top bar reported "credentials configured"** while actually replaying a transcript
- **A component rendered `className="signer seal"`**, and `seal` was a standalone rule
  elsewhere setting a 46px circle, so the label was clamped and its text spilled
- **Four numbers in this README had stopped being true** — a corpus described as 405
  sessions that had grown to 540, a headline figure of 13.3% where the code measured 81.8%
- **The ledger forked under concurrent writes** — 320 appends produced 69 entries
- **Concurrent carts overspent a mandate** — six baskets settled ₹360 against a ₹100 ceiling
- **A test that was flaky 3 runs in 5** turned out to be the bug, not the harness: ledger
  reads were returning rows with a `None` kind while a writer moved underneath them

The last one is worth reading in full. The first detector written for the CSS
collision *did not work* — sibling-box overlap cannot catch a cascade collision,
because overflowing text does not change its element's bounding box. The check that
does catch it is *content larger than its own box while overflow is visible*,
confirmed by reintroducing the bug and watching the detector name it:

```
span.link-signer.seal spills 145x0px outside its box
```

**If you change a detector, prove it the same way — break the thing on purpose and
check that it fails.**

</details>

---

## Honest limits

- **Categories come from the merchant's own catalog.** Half of that hole is closed:
  an acquirer assigns a merchant its category code and the merchant does not pick it,
  so `merchant.mcc_scope` is binding and an unregistered merchant fails closed. What
  stays open is a merchant mislabelling *within* its own category — Zomato is MCC 5812,
  and a power bank listed there as `food_beverage` still passes. Catching that needs
  the item actually purchased, which no metadata layer can see.
  `test_the_known_gap_is_documented_by_a_test` asserts the gap so nobody later mistakes
  the MCC rule for a complete fix.
- **The committed benchmark ran with no model reachable.** Every interpretation is
  labelled with the path it actually took — `live`, `transcript` or `fallback` — in
  the ledger, the CLI and the console, and a replayed one is never presented as
  live. That is why `injection_subtle` and `semantic_drift` read zero in the table
  above. Set either API key and rerun `make bench-live` to move them.
- **Disputes cannot be created through Razorpay's API** — they are bank-initiated. The
  evidence pack is assembled and verified in full and maps onto the real contest schema,
  but submitting it needs a real dispute.
- **A payment cannot be completed server to server**, so the Razorpay rail reports
  `settled=false` until it confirms a capture.

---

## Layout

```
engine/warrant/
  client.py      The front door. Warrant.permit / check / spend.
  service.py     The router a company mounts. Auth required to construct.
  canon.py       RFC 8785 subset. Rejects floats — money is integer paise.
  crypto.py      Ed25519 over canonical bytes. Seeded keys for reproducibility.
  models.py      Intent → Cart → Receipt, bound by content address.
  merchants.py   Acquirer-assigned MCC registry, loaded from your TOML.
  catalog.py     The products, loaded from your TOML.
  gate.py        The only layer that can block. Pure, replayable, no model.
  derive.py      Utterance → scope, clamped by a hard envelope.
  divergence.py  The advisory judge. Can escalate; cannot authorise.
  authorize.py   Orchestration. Write-ahead ordering, serialised per mandate.
  chain.py       Append-only hash chain. Refusals are entries, not silences.
  evidence.py    The chain as a Razorpay dispute submission.
  interop.py     The chain in AP2 vocabulary, W3C-VC shaped.
  py.typed       PEP 561. Without it every annotation here is invisible.
  rails/         Razorpay test mode, a real UPI mandate, and a simulator.
bench/           The labelled corpus, the four policies, the harness.
console/         The walkthrough. A view onto the engine, never a second one.
docs/            The integration guide. Its examples are run by the build.
.verify/         Secrets, tokens, contrast, overlap, layout, docs and browser gates.
warrant.example.toml   Merchants and their MCCs. Yours goes here.
catalog.example.toml   Products. Half of them exist to be refused.
```

---

<div align="center">

**[INTEGRATION.md](docs/INTEGRATION.md)** — how to put this in your own product
· **[ARCHITECTURE.md](ARCHITECTURE.md)** — trust boundaries and the decision record
· **[INCIDENTS.md](INCIDENTS.md)** — what broke, kept as it happened

<br>

*Warrant. No agent spends without one.*

</div>
