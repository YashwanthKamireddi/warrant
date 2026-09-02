# What broke

Kept as it happened, not reconstructed afterwards. The interesting ones are not
the crashes — those announce themselves. They are the times everything was green
and the thing was still wrong.

---

## 1. All 75 tests passed and the console was broken

**What happened.** The demo storefront existed in two files: the scripted scenario
in `demo.py` and the API's catalog in `api.py`. They had drifted by exactly one
SKU — `chai-2` in one, `chai-6` in the other. Clicking *Run five scripted baskets*
returned a 400 on step two. Every backend test passed. The CLI demo passed. The
build passed.

**Why nothing caught it.** Both files were internally consistent and each was
tested against itself. Nothing tested the *seam*, because the seam was two
constants that were supposed to agree and nobody had written down that they were
supposed to agree.

**How I got out.** Not by fixing the string. A catalog that appears in two places
will eventually disagree with itself, so it now appears in one — `catalog.py` — and
`tests/test_catalog.py` asserts that every scripted SKU resolves against it, and
that prices and categories match. Then I made `walk.py` assert that the console's
five verdicts equal what `warrant demo` prints, so the two surfaces can never
silently diverge again.

**What I took from it.** Duplicated data is a test target, not a style issue.

---

## 2. The UI told a lie I had specifically built the backend not to tell

**What happened.** The top bar read *"credentials configured"* with a green dot,
while the scope on screen had actually been replayed from a bundled transcript. No
live call had been made.

**Why.** `resolve_mode()` checked whether an SDK client could be *constructed*.
It could — there was an OAuth profile on disk. The token had expired ten months
earlier, which you only discover at call time. So the function predicted "live"
and the actual call quietly fell through to the transcript.

**Why it mattered more than a wrong label.** The engine's whole design principle
is that a replayed interpretation is never presented as a live one. I had built
that carefully into the ledger and then broken it in the one place a person
actually looks.

**How I got out.** Deleted the prediction. `describe_capability()` now reports only
what is *available*, and the authoritative mode is the `source` field recorded on
each proposal *after* the call ran. The chip shows the path actually taken.

**What I took from it.** "Can I construct a client" is not "do I have working
credentials". Don't predict what a call will do — report what it did.

---

## 3. My detector for a visual bug did not detect the visual bug

**What happened.** A component rendered `className="signer seal"`. `seal` was also
a standalone rule elsewhere in the stylesheet setting a 46×46 gold circle. The
label got clamped to 46px and its text spilled across the content beneath it.
Build green, types green, 82 tests green, page visibly wrong.

**The interesting part.** I wrote a detector for it — walk the DOM, flag any two
in-flow siblings whose bounding boxes intersect. Then I reintroduced the bug on
purpose to check the detector fired.

It did not fire.

Overflowing text does not change its element's bounding box. The element was still
46×46; the *paint* escaped. Sibling-box overlap can never catch a cascade
collision, and I had just written a check that would have passed forever while
telling me it was working.

**How I got out.** Rewrote it to check the actual symptom: content larger than its
own box while `overflow` is `visible`. Reintroduced the bug again. This time:

```
span.link-signer.seal spills 145x0px outside its box
```

Then namespaced the class so it cannot collide.

**What I took from it.** A detector you have not deliberately broken is a detector
you are guessing about. `.verify/README.md` now says: if you change the detector,
break the thing on purpose and check that it fails.

---

## 4. I read my own benchmark as a hostile reviewer and it was flattering me

**What happened.** No bug, no red test. I sat down and attacked the project the way
a panel would, and the injection result did not survive.

The injected item in the corpus was category `electronics`. It got blocked — on
the *category* bound. Nothing had recognised the payload. It would have blocked
identically if the item had been a lamp. And the README claimed, as though it
proved something: *"delete the injection heuristic and this still fails."*

It proved the attack was out of scope by construction.

**How I got out.** Split injection into three honestly-scored categories:

| | |
| --- | --- |
| `injection_oos` | payload also out of scope → blocked on a bound, **not detected** |
| `injection_blunt` | payload inside every bound, obvious phrasing → 45/45 |
| `injection_subtle` | payload inside every bound, phrased to evade the heuristic → **0/45** |

`injection_subtle` is a real ₹50 `food_beverage` item at the permitted merchant
whose text slips past every regex in `gate.py` — verified against the patterns, not
assumed. It is the honest measure of what the deterministic core cannot do, and it
is printed in the same table as everything else.

**What broke immediately after.** Adding those products to the catalog silently
contaminated the `legitimate` category — the random basket builder started picking
injected items for baskets that were supposed to be clean, turning 13 of them into
escalations and making the friction figure meaningless. Caught it because
`legitimate` dropped from 100% to 71.1% in the same run.

**What I took from it.** The most dangerous number in a benchmark is the one you
designed to pass.

---

## 5. My threat model was overclaimed, in the README and in the code

**What happened.** Both said a compromised authoriser *"cannot manufacture a spend
the user never sanctioned."*

That is false. A compromised authoriser skips its own gate and calls the rail
directly. Reserve Pay enforces the blocked *amount*, not the category allowlist —
so it can spend the remaining block on anything at all.

**How I got out.** Rewrote it to say what is true: the chain gives **detection with
attribution, not prevention**. The receipt names a cart, the cart names an intent,
and anyone holding the subject's public key can see the purchase fell outside what
was signed. Preventing it outright needs the *rail* to enforce scope rather than an
amount — which is the layer NPCI's UAP is being designed to occupy.

**What I took from it.** This one improved the pitch. "Here is what my layer cannot
do, and here is the layer that has to do it" is a stronger argument than a claim
that does not survive one question.

---

## 6. Two tests failed and the engine was right both times

**What happened.** Writing tests for `evidence.py`, two failed on first run.

The better one: a test built a variant mandate with `model_copy` to change the rail
binding, then expected an evidence pack. It got "no settled payment". `model_copy`
mutates the signed body, so the signature stopped verifying, so the gate refused
the cart as unsigned, so nothing settled.

**How I got out.** Re-signed the mandate in the test. The engine was correct;
my test had quietly forged a document and the gate caught it.

**What I took from it.** When a test fails against a signature check, assume the
test is wrong first.

---

## 7. The real rail found a double-spend the simulator was hiding

**What happened.** Ten minutes after Razorpay test keys existed, the first run of
`warrant demo --rail razorpay` printed:

```
4  The same cart, replayed    ALLOW  (expected block)
```

The simulator had passed this step every time for days.

**Why.** Replay protection consumed a cart's nonce in `record_settled()`. The
simulated rail settles synchronously, so the nonce was always consumed before the
replay arrived. A real rail does not work that way: Razorpay issues an order and a
payment link server-side and reports `settled=False` until the customer authorises
on their own device — which is correct, and which is precisely the property that
makes the rail trustworthy.

So on any real rail there was a window between *placed* and *settled* in which the
same cart could be presented again and again, **placing an order every time**. With
Reserve Pay each of those can capture. That is a double-spend, not a cosmetic bug.

**How I got out.** Split the state transition in two, because it was always two
things wearing one name:

- `record_authorized()` — consumes the nonce the moment the cart reaches the rail.
  Replay protection guards the *presentation* of a cart.
- `record_settled()` — charges spend and attempt count. Those stay on settlement,
  so a payment the customer abandons does not burn the mandate's budget.

**What I took from it.** Every argument for getting real keys was about
credibility with a reviewer. The actual return was a double-spend vector found in
the first minute of running it, in a code path 155 tests and a passing demo had
agreed was fine. A simulator agrees with whatever assumption you built into it.

---

## 8. The convenience layer double-charged on every retry

**What happened.** I added a small facade over the engine so adopting this did not
require choosing a signing key and inventing a nonce. Then I asked what a payments
API has to survive, and sent the same basket three times:

```
attempt 1: allow  settled=True  cart=cm_b11e020b…
attempt 2: allow  settled=True  cart=cm_b0472749…
attempt 3: allow  settled=True  cart=cm_7a08c415…
total spent: 72000 paise
```

Rs 720 for one lunch.

**Why.** The engine has a replay guard and it was never reached. Every call minted
a fresh cart nonce, so a retry built a *different* cart, which the gate has no
reason to refuse. The engine had been correct the whole time; the convenience
layer handed it a new nonce every call. An agent retrying a timed-out request is
not an edge case, it is the normal case.

**How I got out.** Two layers, because one of them is only a cache.

- A repeat with the same `idempotency_key` returns the first decision without
  touching the rail. Returning a *refusal* would be safe and useless: a caller
  told "blocked: replay" reasonably concludes the payment failed and tries again.
- The cart nonce is **derived** from the key, so when the bounded cache evicts an
  entry the gate's own `replay.cart_nonce` check refuses the repeat. A test clears
  the cache and asserts the second charge still does not happen.

Then eight simultaneous retries produced one allow and seven refusals — the money
right and the answer wrong, the same failure one level up. Checking the cache and
filling it were separate critical sections. The slot is single-flight now, and a
test asserts different keys still never contend.

**What I took from it.** The engine was never wrong. I put a friendlier surface in
front of it and the surface reintroduced the exact class of bug the engine exists
to prevent. Convenience layers need the same tests as the thing they wrap.

---

## 9. I shipped a payment authorization service with no authentication

**What happened.** I built the mountable service — permissions, checks, spends,
revocations — and went looking for something else to improve. On a whim I grepped
it for `Depends`, `auth`, `token`. Nothing. Every endpoint was open. Anyone who
could reach the port could mint a spending permission and spend it.

**Why.** I had been building the thing that decides whether money may move and had
never once asked who was allowed to ask it. Every test I wrote called the handlers
as a trusted caller, so every test passed.

**How I got out.** `warrant_router` now *raises* unless it is given
authentication. Not a warning, not default-open with a note in the docs —
construction fails. A service that mints spending permissions must not become
usable-because-reachable when somebody forgets an argument, so running open is
possible and has to be typed: `auth=NO_AUTH`.

Bearer tokens compare with `compare_digest` against every configured key rather
than returning on the first match, so a rejection takes the same time whichever
key it was measured against. Health and readiness stay unguarded, because an
orchestrator holds no credential and a probe that returns 401 reports the process
as dead.

**What I took from it.** The gap was not hard to fix and was invisible from
inside: my tests modelled a world with no attacker in it.

---

## 10. My own credential guard let a real API key into a commit

**What happened.** A Groq key arrived in chat. I wrote it to `.env`, confirmed
`.env` was gitignored and untracked, and then — because a guard that has never
been seen to fire is not a guard — deliberately appended the key to `README.md`
and tried to commit it.

It committed. Exit 0. `git log -S` found the key sitting in local history.

**Why.** The global pre-commit hook has a pattern per vendor and had no pattern
for Groq's `gsk_` prefix. Worse, its generic `API_KEY=` rule required the value to
be **quoted** — so a bare `KEY=value`, the exact shape of every line in a `.env`
file and the way a key is most often pasted, matched nothing at all.

**How I got out.** Reset the commit — `origin` had never been ahead of it, so the
key never left the machine — then added the missing patterns, made the generic
rule work without quotes, and re-ran the same three probes:

```
GROQ_API_KEY           blocked
SHOPIFY_TOKEN          blocked
DB_PASSWORD            blocked
```

**What I took from it.** I had trusted that guard for days across every repository
on this machine. It took ninety seconds to test and it was wrong. The lesson is
not "add Groq to the list" — it is that a detector nobody has watched fail is a
belief, not a control. Every gate in this project has since been proven by
breaking what it watches: the overlap detector, the docs-links audit, the
screenshot staleness check.

---

## Still open

Honesty requires listing what has not been fixed.

- **Categories come from the merchant's own catalog and are never verified.** This
  is the load-bearing weakness of the whole gate. A merchant that tags everything
  `food_beverage` defeats it. The fix is to take the category from the rail's
  merchant category code rather than item metadata, which needs rail-side data this
  layer does not have merchant-side.
- **`injection_subtle` and `semantic_drift` both score zero** without a live model.
  Those two rows are the only ones a model moves; every other row is arithmetic.
