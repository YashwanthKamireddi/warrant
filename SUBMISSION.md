# Submission

The form's fields, in the form's order, ready to paste.

---

## Track Selection

**Track 01 — AI Growth & Agentic Commerce**

---

## Project Name / Title

**Warrant**

---

## Project Objectives — what does it solve?

> Since February 2026, Razorpay and NPCI have run agentic UPI payments in
> production with Zomato, Swiggy and Zepto. The mechanism is UPI Reserve Pay: the
> customer approves once with their PIN, funds are blocked, and the agent then
> debits against that block repeatedly with no further PIN.
>
> That leaves two holes, and both are open today.
>
> **Nothing checks what the agent buys against what the customer asked for.** The
> bank never sees a basket, only a debit. A ceiling is equally happy to buy the
> thing that was asked for and the thing that was not — and no fraud signal
> fires, because none of this is fraud. Real card, real device, real customer.
> It simply is not what they agreed to.
>
> **And when the dispute arrives, the merchant has nothing.** An agent-initiated
> payment has no device fingerprint, no browsing session, no click. Chargeback
> reason codes have no category for "correctly authorised agent, wrong outcome",
> so the merchant absorbs it.
>
> Warrant closes both with one object: a signed chain from the words a person
> said to the rupee that moved. The customer's own device key signs a bounded
> permission — an amount, a merchant, a category, a deadline. Every basket the
> agent proposes is checked against it by deterministic code before settlement.
> Every decision, including every refusal, is appended to a hash-chained ledger
> that later renders as dispute evidence a bank can verify without trusting the
> merchant's records.
>
> Measured over 540 labelled sessions: Warrant stops 81.8% of violations and
> leaks ₹30,208, against ₹1,69,825 with the amount ceiling a mandate already
> gives you and ₹3,02,663 with no gate at all — and it has never once stopped a
> purchase the person actually authorised. Two categories score zero, and they
> are printed in the same table as the wins.
>
> Nothing in the demonstration is a mock. The catalogue is 62 products read from
> a real Indian coffee brand's public Shopify feed. The agent is a live model
> that is never told the limits, only the reason it was refused. The payment is
> Razorpay's own Checkout on a real test-mode order, and what Checkout returns is
> verified server-side against the key secret before anything claims the payment
> happened.
>
> No model can change a verdict. The gate is a pure function of the signed
> documents and the state; a model can propose and can advise, and neither can
> grant authority. Prompt injection in a product name is inert by construction
> rather than by filtering.

---

## GitHub Repository URL

`https://github.com/YashwanthKamireddi/warrant`

374 tests, 11 gates, green from a cold clone with no credentials.

---

## 5-min Pitch Video Link

*(paste the unlisted link once uploaded — the film is 4:53, built by
`.video/record.py` and `.video/compose.py`, narration in
[.video/NARRATION.md](.video/NARRATION.md))*

---

## Build Challenges & Technical Obstacles

*The long version, with commits, is in [INCIDENTS.md](INCIDENTS.md).*

> **A simulator agrees with whatever assumption you built into it.**
>
> Ten minutes after I got Razorpay test keys, the first run against the real rail
> printed `the same cart, replayed → ALLOW (expected block)`. The simulated rail
> had passed that step for days, across 155 tests.
>
> Replay protection consumed a cart's nonce on *settlement*. The simulator
> settles synchronously, so the nonce was always spent before a replay could
> arrive. A real rail does not work that way: Razorpay issues an order
> server-side and reports `settled=false` until the customer authorises on their
> own device — which is exactly the property that makes the rail trustworthy. So
> on any real rail there was a window between *placed* and *settled* where the
> same cart could be presented again and again, placing an order every time.
> Under Reserve Pay each of those can capture. That is a double-spend, not a
> cosmetic bug.
>
> The fix was to split a state transition that had always been two things wearing
> one name: `record_authorized()` consumes the nonce the moment the cart reaches
> the rail, and `record_settled()` charges spend and attempt count so an abandoned
> payment does not burn the mandate's budget. Every argument I had made for
> getting real keys was about credibility with a reviewer. The actual return was a
> double-spend vector found in the first minute, in a path that a passing test
> suite and a working demo both agreed was fine.
>
> **A check you have never watched fail is not a check.**
>
> I wrote a detector for a CSS collision that was painting a label over the text
> beneath it — then reintroduced the bug deliberately to confirm the detector
> fired. It did not. Overflowing text does not change its element's bounding box,
> so sibling-box overlap can never catch a cascade collision. I had written
> something that would have passed forever while reporting that it worked.
>
> That happened a second time, and I only caught it because I now look. I added a
> gate that checks the numbers in the video narration against what the code
> measures. Its checks ran *after* the block that reports failures and exits, so
> everything it found was collected and thrown away — it printed "numbers match"
> over a script claiming 211 tests when there were 373. Both are fixed, and both
> are now verified by breaking them on purpose.
>
> **A real payment, reported as a failure.**
>
> `POST /razorpay/{index}` was declared before `POST /razorpay/verify`, and
> FastAPI matches routes in declaration order — so every verification call was
> read as the index route with `index="verify"` and answered 422. Razorpay had
> taken the money and returned a signed payment id the whole time. The console,
> which will not claim a payment happened until the server has recomputed that
> signature, correctly said nothing. It looked exactly like a payment failing,
> and it was a routing bug. There is now a test asserting the route resolves,
> because nothing else would have caught it.
>
> **Numbers rot faster than code.**
>
> I found four figures in my own README that had quietly stopped being true — a
> corpus described as 405 sessions that had grown to 540, a headline of 13.3%
> where the code measured 81.8%. For a project whose entire argument is honest
> reporting, that is worse than a bug. `make docs-check` now fails the build if
> any number in the README, the landing page, the deck, the submission or the
> video narration drifts from what the code measures. It has caught a stale count
> four times since.

---

## Video script — 5:00

Record the console at 1580×960, with a second tab on the Razorpay test
dashboard. Run `make console`. Everything below is something happening on
screen — do not narrate the architecture, read the README aloud, or scroll code.

| time | beat | on screen |
| --- | --- | --- |
| **0:00** | *"Since February, Razorpay and NPCI have run agentic UPI payments in production — Zomato, Swiggy, Zepto. You approve once with your PIN, and the agent spends against that block without asking again."* | the landing page |
| **0:20** | *"Two holes. Nothing checks what the agent buys against what you asked for. And when you dispute it, the merchant has no device fingerprint, no session, no click — chargeback codes have no category for 'correctly authorised agent, wrong outcome.'"* | scroll to the measured numbers |
| **0:45** | Open the console. *"You said this once. It became a permission signed by your own key: an amount, a merchant, a category, a deadline."* | the permission, top of the console |
| **1:05** | **The centrepiece — let it breathe.** *"Nobody pressed anything. A live model is reading Sleepy Owl's actual storefront — their products, their prices — and it has no idea what your limits are."* | the agent's own reasoning appearing |
| **1:25** | *"It picks two packs. ₹698. Warrant will not decide this one — it crosses the ₹500 you said needs your say-so, so it stops and comes back to you. It cannot approve this itself, and neither can the agent."* | `Needs you`, and the ask |
| **1:45** | Click **Approve — sign with my key**. *"Your key signs the basket, the same gate runs again, and the check that failed a moment ago passes — because a signature exists that did not before."* | `Allowed`, the money bar moves |
| **2:05** | Click **Pay ₹698 on Razorpay**. *"That is Razorpay Checkout. Their script, their sheet, on an order this server created against the real test API."* Pay with UPI `success@razorpay`. | the real Razorpay sheet |
| **2:25** | *"And it is not taken at face value. Checkout hands back an order id, a payment id and an HMAC of the two under the key secret. The server recomputes that signature before anything here says the payment happened."* | `Paid on Razorpay`, then the dashboard tab |
| **2:45** | Click **Try to buy something you never asked for**. *"A coffee mug. ₹449, comfortably under every ceiling — the bank would pay it without blinking. Nobody planted it; a coffee company sells mugs."* | `Refused`, two rules named |
| **3:05** | *"Refused twice: by the category code the merchant's acquirer assigned, and by the permission itself. And there is what it would have cost with nothing checking."* | the priced refusal |
| **3:20** | *"A model runs in exactly two places here and in neither can it grant authority. If an injected product name convinces the advisory judge, the outcome is byte-identical to the judge never running."* | — |
| **3:40** | Open **See the record**. *"Every decision, including every refusal. Most systems log what they did; a dispute turns on what was declined."* | the ledger, fingerprints explained |
| **4:00** | Click **Try to rewrite the ledger**. *"Each fingerprint is computed from its entry and the one before, so editing any entry orphans everything after it — and it names both hashes so you can check."* | the break |
| **4:15** | Open the dispute pack, then the AP2 export. | the pack, then the credentials |
| **4:30** | `make bench`. *"540 labelled sessions. An amount ceiling alone lets 416 through. Warrant lets 90 through, and has never once stopped a purchase the person actually authorised."* | the table |
| **4:45** | *"Two categories score zero, printed in the same table as the wins. A benchmark you designed to pass is not a benchmark."* | `injection_subtle 0/45`, `semantic_drift 0/45` |
| **4:55** | *"Warrant. No agent spends without one."* | — |

The timed, word-for-word version of this is [.video/NARRATION.md](.video/NARRATION.md),
and `make film` cuts the footage to it.

---

## Pre-submission checklist

```bash
make verify              # 11 gates, from a clean checkout
make browser-razorpay    # Razorpay Checkout opens on a real order (needs keys)
```

- [ ] `make verify` green on a **fresh clone**, not just locally
- [ ] repo is **public**
- [ ] `.env` absent from the repo — `make audit-secrets` proves it
- [ ] video unlisted, under 5:00
- [ ] resume attached
- [ ] submitted with a day to spare
