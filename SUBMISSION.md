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

> **Razorpay has already placed the bet. Warrant is what stops it hitting a
> ceiling.**
>
> Since February 2026, Razorpay and NPCI have run agentic UPI payments in
> production with Zomato, Swiggy and Zepto. The customer approves once with a
> PIN, funds are blocked, and the agent spends against that block with no
> further PIN. That is a genuinely new payment surface, and Razorpay owns the
> rails under it.
>
> Here is what caps it. When an agent buys the wrong thing — and it will, because
> a model chose the basket — the customer disputes the charge, and the merchant
> has nothing to show. No device fingerprint. No session. No click. Chargeback
> reason codes do not have a category for *"correctly authorised agent, wrong
> outcome"*, so it is not even classifiable, let alone defensible. The merchant
> eats it.
>
> Merchants respond to undefendable losses in exactly one way: they throttle the
> traffic that causes them. Low agent limits, category blocks, or refusing agent
> checkouts outright. Every one of those is a brake on the category Razorpay is
> building. **The bottleneck on agentic commerce is not payment rails. It is that
> nobody can prove what the customer agreed to.**
>
> Warrant is that proof. The customer's own device key signs a bounded permission
> — an amount, a merchant, a category, a deadline. Every basket the agent
> proposes is checked against it by deterministic code *before* settlement. Every
> decision, including every refusal, lands in a hash-chained ledger that renders
> as dispute evidence a bank can verify without taking the merchant's word for
> anything.
>
> **This is a growth product wearing a risk product's clothes.** A merchant with
> Warrant in front of it can accept agent traffic its competitors have to refuse.
> That is Track 01's brief almost word for word: it makes a merchant transactable
> by an AI buyer, end to end.
>
> **And it is a layer only the acquirer can credibly own.** Stripe has Radar for
> *"is this fraud?"* — a statistical question about the payer. Nobody has
> *"did this person agree to this?"* — a cryptographic question about the
> permission. Fraud engines are structurally blind to it: the card is real, the
> device is real, the customer is real. Every signal says the transaction is
> fine, and it is fine. It is simply not what was asked for. That gap is a new
> product line, a new pricing surface, and a reason for merchants to route agent
> volume to whoever offers it.
>
> **The timing is the whole point.** NPCI's UAP is being specified now, and this
> is a working specification of what that layer has to enforce — running
> merchant-side today because that is where it can run, and exporting to Google's
> AP2 / W3C Verifiable Credentials so it is not a private format.
>
> What it is worth, measured on 540 labelled sessions. With nothing checking,
> **₹3,02,663** moves outside what customers agreed. The amount ceiling a mandate
> already gives you only brings that to **₹1,69,825** — it stops big purchases,
> not wrong ones. Warrant cuts it to **₹30,208**, and has never once blocked a
> purchase the person actually authorised, because a control layer that
> inconveniences good customers gets switched off in a week.
>
> None of it is staged. The catalogue is 62 products read live from a real Indian
> coffee brand's public storefront. The agent is a live model that is never told
> the limits, only the reason it was refused. The payment is Razorpay's own
> Checkout on a real test-mode order, and what Checkout returns is verified
> server-side against the key secret before anything claims money moved.

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

*Commits and the long version: [INCIDENTS.md](INCIDENTS.md).*

> **Spending two days getting real keys instead of shipping features.**
>
> The tempting call was to demo on a simulator and spend the time on surface. I
> went and got Razorpay test credentials first. Ten minutes in, the first run
> against the real rail printed `the same cart, replayed → ALLOW (expected
> block)` — a step the simulator had passed for days across 155 tests.
>
> Replay protection consumed a cart's nonce on *settlement*. The simulator
> settles synchronously, so the nonce was always spent before a replay could
> arrive. A real rail does not behave that way: Razorpay creates the order
> server-side and reports `settled=false` until the customer authorises on their
> own device — the very property that makes the rail trustworthy. So on any real
> rail there was a window between *placed* and *settled* where the same cart
> could be presented repeatedly, placing an order each time. Under Reserve Pay
> each of those can capture. That is a double-spend in a payments product.
>
> The fix was to split a state transition that had always been two things wearing
> one name: `record_authorized()` consumes the nonce the moment the cart reaches
> the rail; `record_settled()` charges spend and attempt count, so an abandoned
> payment does not burn the customer's budget. The lesson I actually took: a
> simulator agrees with whatever assumption you built into it, and the cost of
> finding that out later is not a bug, it is a recall.
>
> **Discovering my own safety checks were theatre.**
>
> I wrote a detector for a CSS collision, then reintroduced the bug deliberately
> to watch it fire. It did not. Overflowing text does not change its element's
> bounding box, so sibling-box overlap can never catch a cascade collision. I had
> shipped something that would have passed forever while reporting it worked.
>
> It happened a second time, and I only caught it because I now look. I added a
> gate comparing the numbers in my video narration to what the code measures. Its
> checks ran *after* the block that reports failures and exits, so everything it
> found was collected and discarded — it printed "numbers match" over a script
> claiming 211 tests when there were 373. Both are fixed. More usefully, "break
> it on purpose and confirm the check fails" is now how I finish any check, and
> it has caught two more since.
>
> **A real payment, reported to the customer as a failure.**
>
> `POST /razorpay/{index}` was declared before `POST /razorpay/verify`, and
> FastAPI matches routes in declaration order — so every verification call was
> read as the index route with `index="verify"` and rejected as a bad integer.
> Razorpay had taken the money and returned a signed payment id the entire time.
> The console, which refuses to claim a payment happened until the server has
> recomputed that signature, correctly showed nothing. It presented exactly like
> a payment failure and it was a routing bug — the worst class of payments
> incident, because the money is gone and your own system says it is not. There
> is a test asserting that route resolves now, since nothing else would have
> caught it.
>
> **Deciding what a judge can trust.**
>
> I found four figures in my own README that had quietly stopped being true — a
> corpus described as 405 sessions that had grown to 540, a headline of 13.3%
> where the code measured 81.8%. For a project whose entire pitch is provable
> claims, that is worse than a bug: it is the pitch failing on itself. Rather
> than proofread, I made it structural. `make docs-check` fails the build if any
> number in the README, the landing page, the deck, this submission or the video
> narration drifts from what the code measures. Five documents, one source of
> truth. It has caught a stale figure four times since, including twice while
> writing this.
>
> The same instinct runs through the rest: 374 tests, 11 gates, and they pass
> from a cold clone with no credentials — cloned into an empty directory and run,
> because "works on my machine" is not a claim anyone should accept from me.

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
