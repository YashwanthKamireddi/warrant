# Narration

Read over `out/warrant-pitch.mp4`. Word-for-word, timed to the actual cut —
**5:00 total**, which is the five-minute
limit.

Each heading gives the timestamp and how long that shot is held. If a section
feels rushed, it is because there are more words than seconds — cut a sentence
rather than speeding up.

**How to record it:** open the video, hit play, and read. If you fluff a line,
keep going — you can re-record just that stretch. Do not try to sound polished;
sound like someone explaining something they understand.

**Two rules.** Don't describe what's on screen — the screen does that. And when
you reach the losses, slow down; that's the part they remember.

---

### 0:00 · 20s — the problem *(dark card)*

> An AI agent is spending your money without asking again.
>
> Since February, Razorpay and NPCI have run agentic UPI payments in production —
> Zomato, Swiggy, Zepto. It works through UPI Reserve Pay: you block funds once
> with your PIN, and the agent then debits against that block repeatedly. No
> further PIN.

### 0:20 · 26s — two holes *(dark card)*

> That leaves two holes, and both are open today.
>
> Nothing checks what the agent buys against what you actually asked for. You
> said "coffee for my team, under a thousand rupees." The block is authorised. So
> what stops a four-hundred-and-forty-nine rupee charge for a mug nobody asked
> for?
>
> And when you dispute it, the merchant has nothing. No device fingerprint, no
> session, no click. Chargeback codes have no category for "correctly authorised
> agent, wrong outcome." The merchant eats it.

### 0:45 · 12s — the landing page *(live)*

> This is Warrant. Over five hundred and forty labelled cases, an amount ceiling
> on its own lets four hundred and sixteen through. Warrant lets ninety through,
> and has never once stopped a purchase the person actually authorised.

### 0:57 · 30s — what it is *(dark card)*

> One object closes both holes: a signed chain from the words a person said to
> the rupee that moved.
>
> The person's own device key signs a bounded permission. The authoriser signs an
> attestation that a specific basket was checked against it. And the receipt binds
> the payment to both.
>
> Only the person's key can widen what may be spent. The authoriser can attest
> that something already permitted was checked — it cannot grant authority it was
> never given.

### 1:26 · 14s — the permission *(live)*

> She says the thing once, and it becomes a permission with hard ceilings,
> restated in plain English, signed by her own key.
>
> This isn't a new step. Reserve Pay already asks for a PIN. That tap used to mean
> "block a thousand rupees." Now it means "up to a thousand, at this merchant, on
> food, for two hours." Same tap. More meaning.

### 1:40 · 26s — the agent, refused, adapting *(live)*

> **[this is the one — let it breathe]**
>
> Nobody pressed anything. A live model is reading a real merchant's catalogue —
> that's Sleepy Owl's actual storefront, their products, their prices, their
> photographs.
>
> It picks two units. Six hundred and ninety-eight rupees. Warrant escalates: that
> crosses the five hundred rupee threshold she set for a second signature.
>
> The agent is told the *reason*. Never the limits. And it comes back with one
> unit, three hundred and forty-nine, and says why. That is an agent discovering
> its boundary by being refused.

### 2:05 · 16s — what it prevents *(live)*

> Same shop, a different basket. A coffee mug. Four hundred and forty-nine rupees,
> comfortably under every ceiling — the bank would pay it without blinking.
>
> Nobody planted that mug. A coffee company sells mugs. Her permission was for
> food and drink, so it is refused twice: once by the category code her merchant's
> acquirer assigned, and once by the permission itself.

### 2:21 · 28s — where the model runs *(dark card)*

> That's the design. A model runs in exactly two places, and in neither can it
> grant authority.
>
> It turns an instruction into a scope — but a hard envelope clamps whatever it
> proposes, a human approves it, and only the person's key signs it. And it judges
> whether a basket looks like what was asked for — but that finding is hard-coded
> advisory. It can raise "allow" to "needs a human." It cannot approve, and it
> cannot overturn a block.
>
> So if an injected product name convinces that judge to say "consistent," the
> outcome is byte-identical to the judge never running. There's no prompt that
> makes it grant authority, because it holds none.

### 2:48 · 18s — the record, then tampering *(live)*

> Every decision is written down — including every refusal. Most systems log what
> they did. A dispute almost always turns on what was declined, and why.
>
> The chain is hash-linked, so let me break it on purpose. That entry has been
> rewritten. Everything after it is orphaned, and it names both hashes — the one
> the chain expected and the one it found — so you can check it yourself.

### 3:06 · 16s — the dispute pack and AP2 *(live)*

> And this is what the merchant sends the bank. The exact words the customer said,
> the permission they approved, the basket checked against it, and the signatures
> binding all three to the payment. The bank verifies it against the customer's own
> public key — it doesn't have to trust the merchant's records.

### 3:22 · 12s — a real Razorpay order *(live)*

> And this is a real Razorpay order, created from that record on their test API.
> The gate already allowed this basket; nothing is re-decided. If the account has
> hit its daily cap, the console says so in Razorpay's own words rather than
> pretending.

> The fair objection is that Google's AP2 already defines a chained mandate model.
> It does. But AP2 standardises what the credential *is*, not who *checks* it. The
> gate, the judge and the ledger are that gap. Same chain, exported in their
> vocabulary, with the three real divergences carried inside the document.

### 3:33 · 20s — results *(dark card)*

> Five hundred and forty labelled sessions, four policies, one seed.
>
> Warrant stops eighty-two percent of violations and leaks thirty thousand two
> hundred rupees, against three hundred and two thousand with no gate at all. An
> amount ceiling on its own leaks a hundred and seventy thousand. Decisions take
> under three hundred microseconds at the median, because this sits in the payment
> path.
>
> And the numbers in the README can't go stale — the build fails if they drift from
> what the code measures.

### 3:53 · 24s — where it loses *(dark card)*

> **[slow down — this is the part that matters]**
>
> Two categories score zero. They're printed in the same table as the wins.
>
> Those are baskets inside every bound the person signed — right merchant, right
> category, under every ceiling — that are still not what was asked for. No
> arithmetic catches those. Only reading the basket against the instruction does,
> and no model ran here.
>
> I could have left those out of the table. A benchmark you designed to pass isn't
> a benchmark.

### 4:16 · 22s — known limits *(dark card)*

> Three more things I'd want you to know before you believe any of it.
>
> Categories come from the merchant's own catalog. The acquirer's category code
> closes half of that — an acquirer assigns that code, the merchant doesn't pick
> it, so a coffee brand can't sell electronics however it tags them. But a power
> bank mislabelled as food *inside* that catalog still passes. There's a test
> asserting that gap, so nobody later mistakes the fix for a complete one.
>
> A compromised authoriser can still spend the block, because the rail enforces
> amount, not category. This gives detection with attribution — not prevention.
>
> And every number is measured on data this repository generates. That's exactly
> why the losses are printed.
>
> Closing the rest needs the rail itself to enforce scope. Which is precisely the
> layer NPCI's UAP is being designed to occupy.

### 4:38 · 16s — close *(dark card)*

> Three hundred and sixty-eight tests. Eleven gates, green from a clean clone. The
> interesting ones exist because a green build didn't catch a real bug — a ledger
> that forked under concurrent writes, six baskets that overspent a hundred-rupee
> mandate, and a detector I'd written that didn't detect the thing it was for. I
> only found that last one because I broke it on purpose to check.
>
> Warrant. No agent spends without one.

---

## If you need to trim

The submission form caps the video, and this runs 4:53. Cut in this order — first
to go is the least load-bearing:

1. **3:06 · the AP2 half** — keep the dispute pack, drop the AP2 answer. It is an
   objection-handler for a question a judge may not ask, and the README answers it
   in writing either way. Saves about 8s.
2. **4:16 · known limits** — the honesty is worth more in the README, where it can
   be read slowly, than in a timed video. Saves 22s.
3. **0:57 · what it is** — the three-signature structure is shown again on the
   permission and the record. Saves 30s.

Never cut **1:40 · the agent, refused, adapting**. It is the only part of the film
that cannot be faked in a slide, and it is the reason to watch.

---

## Before you record

- Read it once against the picture with the sound off. Every timestamp above is
  the composed timeline, not the sum of the clips — the crossfades overlap, so
  they differ by six seconds by the end.
- Every number here is measured, not estimated. If a run changes one,
  `make bench` rewrites `bench/RESULTS.json` and `make docs-check` fails until
  the README and this script agree with it.
