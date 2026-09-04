# Submission

Everything the form asks for, ready to paste. Twelve fields.

---

## About the build

**Track** — 01, AI Growth & Agentic Commerce

**Project name** — Warrant

**What it solves**

> Since February 2026, Razorpay and NPCI have run agentic UPI payments in
> production on Claude, with Zomato, Swiggy and Zepto. They use UPI Reserve Pay:
> the customer blocks funds once, and the agent then debits against that block
> repeatedly with no further PIN.
>
> That leaves two holes. Nothing checks the debit against the customer's actual
> intent before the money moves — a basket can sit under every ceiling, at the
> right merchant, and still be something nobody asked for. And when the dispute
> arrives, the merchant has no evidence: an agent-initiated payment has no device
> fingerprint, no browsing session, no click, and chargeback reason codes have no
> category for "correctly authorised agent, wrong outcome."
>
> Warrant closes both with one object: a signed chain from the words a person said
> to the rupee that moved. The customer's own key signs a bounded permission.
> Every basket is checked against it by deterministic code before settlement. Every
> decision — including every refusal — lands in a hash-chained ledger that later
> renders as dispute evidence a bank can verify without trusting the merchant.
>
> Measured across 540 labelled sessions: 81.8% of violations stopped, ₹30,208
> leaked against ₹302,663 with no gate at all — and ₹1,69,825 with the amount
> ceiling a mandate already gives you, which is the comparison that matters. Two
> categories score zero and are printed in the same table as the rest.
>
> The payment leg is Razorpay's own. An allowed basket opens Razorpay Checkout on
> an order created against the real test API, and what Checkout hands back is
> verified server-side against the key secret before anything claims the payment
> happened.

**GitHub repo** — `https://github.com/YashwanthKamireddi/warrant`

**Video** — *(unlisted link)*

---

## What broke, and how you got out

*They say this is the one they read first. Paste this; the long version is in
[INCIDENTS.md](INCIDENTS.md).*

> Ten minutes after I got Razorpay test keys, the first run against the real rail
> printed `4  The same cart, replayed → ALLOW (expected block)`. The simulator had
> passed that step for days.
>
> Replay protection consumed a cart's nonce on settlement. The simulated rail
> settles synchronously, so the nonce was always spent before a replay arrived. A
> real rail doesn't work that way — Razorpay issues an order and a payment link
> server-side and reports `settled=false` until the customer authorises on their
> own device, which is exactly the property that makes the rail trustworthy. So on
> any real rail there was a window between *placed* and *settled* where the same
> cart could be presented again and again, placing an order every time. With
> Reserve Pay each of those can capture. That's a double-spend, not a cosmetic bug.
>
> I split the state transition, because it had always been two things wearing one
> name: `record_authorized()` consumes the nonce the moment the cart reaches the
> rail, and `record_settled()` charges spend and attempt count so an abandoned
> payment doesn't burn the mandate's budget.
>
> Every argument I'd made for getting real keys was about credibility with a
> reviewer. The actual return was a double-spend vector found in the first minute,
> in a code path that 155 tests and a passing demo agreed was fine. A simulator
> agrees with whatever assumption you built into it.
>
> Two others worth naming. I wrote a detector for a CSS collision that was painting
> a label over the text beneath it — then reintroduced the bug on purpose to check
> the detector fired, and it didn't. Overflowing text doesn't change its element's
> bounding box, so sibling-box overlap can never catch a cascade collision; I'd
> written a check that would have passed forever while telling me it worked. And I
> found four numbers in my own README that had quietly stopped being true — a
> corpus described as 405 sessions that had grown to 540, a headline figure of
> 13.3% where the code measured 81.8%. For a project whose whole argument is honest
> reporting, that's worse than a bug. Both are now generated and gated:
> `make docs-check` fails the build if any number in the README drifts from what
> the code measures.

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
