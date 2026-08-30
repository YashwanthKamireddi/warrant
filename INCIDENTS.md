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

## Still open

Honesty requires listing what has not been fixed.

- **Categories come from the merchant's own catalog and are never verified.** This
  is the load-bearing weakness of the whole gate. A merchant that tags everything
  `food_beverage` defeats it. The fix is to take the category from the rail's
  merchant category code rather than item metadata, which needs rail-side data this
  layer does not have merchant-side.
- **`injection_subtle` and `semantic_drift` both score zero** without a live model.
  Those two rows are the only ones a model moves; every other row is arithmetic.
