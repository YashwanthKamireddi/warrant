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
> Measured across 540 labelled sessions: 81.8% of violations stopped, ₹27,700
> leaked against ₹281,635 at risk with no gate. Two categories score zero and are
> printed in the same table as the rest.

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

Record the console at 1580×960. Have a second tab open on your Razorpay test
dashboard. `make console`, and pay one payment link before you start so the
settlement beat is instant.

| time | beat | on screen |
| --- | --- | --- |
| **0:00** | *"Since February, Razorpay and NPCI have run agentic UPI in production with Zomato, Swiggy and Zepto. You approve once with your PIN, and then the agent spends from that block without asking again."* | first-run screen, mandate chain visible |
| **0:20** | *"Two holes. Nothing checks what the agent buys against what you asked for. And when you dispute it, the merchant has no device fingerprint, no session, no click — nothing."* | — |
| **0:40** | *"You say this."* Read the instruction. *"It becomes this."* | derive → certificate, seal stamps |
| **1:00** | *"Same tap you already made. It just means something specific now. Note the envelope narrowed what the model proposed — the model can only ever make this smaller."* | terms grid, narrowing note |
| **1:20** | Run five scripted baskets | ALLOW · BLOCK · BLOCK · BLOCK · ESCALATE |
| **1:40** | **The strongest 20 seconds.** Expand basket 3. *"That product name is an injected instruction. It's blocked — and look at the header: no model call. It never reached a model. It failed on the category bound. Delete my injection detector entirely and it still fails."* | `scope.category` fail, `no model call` |
| **2:10** | *"That's the design. A model runs in exactly two places, and in neither can it grant authority. The judge is hard-coded advisory — if an injected payload convinces it to say 'consistent', the outcome is byte-identical to it never running."* | — |
| **2:30** | Switch to Razorpay test mode, authorise a basket | real `order_…`, live `rzp.io` link |
| **2:50** | Cut to the Razorpay dashboard | the order, in their system |
| **3:05** | *"It says settled=false. A script can't authorise a payment for the customer — and that property is what found a double-spend my simulator had hidden for days."* Click **Check the rail for settlement** | signed receipt appears |
| **3:25** | Dispute evidence tab | the full pack |
| **3:45** | Click **Tamper with the ledger** | entry striped, status bar red, pack refuses to vouch |
| **4:05** | `make bench` in a terminal | the table, then scroll to **Where this loses** |
| **4:20** | *"Two categories score zero. Baskets inside every bound that are still wrong. No arithmetic catches those — only a model does. It's in the same table as everything else, because a benchmark you designed to pass isn't a benchmark."* | `injection_subtle 0/45`, `semantic_drift 0/45` |
| **4:40** | *"Categories still come from the merchant's own catalog. I check them against the acquirer's MCC, which closes half of it. The other half needs the rail — which is the argument for this living in NPCI's UAP."* | — |
| **4:55** | *"Warrant. No agent spends without one."* | — |

**Do not** narrate the architecture diagram, read the README aloud, or show code
scrolling. Every beat above is something happening on screen.

---

## Pre-submission checklist

```bash
make verify              # 8 gates, from a clean checkout
make browser-razorpay    # a real order lands (needs keys)
```

- [ ] `make verify` green on a **fresh clone**, not just locally
- [ ] repo is **public**
- [ ] `.env` absent from the repo — `make audit-secrets` proves it
- [ ] video unlisted, under 5:00
- [ ] resume attached
- [ ] submitted with a day to spare
