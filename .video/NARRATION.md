# Narration

Read over `out/warrant-pitch.mp4`. Word-for-word, timed to the actual cut —
**4:43 total**, so you have seventeen seconds of headroom against the five-minute
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
> said "chai and samosas, under a thousand rupees." The block is authorised. So
> what stops a four-hundred-and-ninety-nine rupee charge for something nobody
> asked for?
>
> And when you dispute it, the merchant has nothing. No device fingerprint, no
> session, no click. Chargeback codes have no category for "correctly authorised
> agent, wrong outcome." The merchant eats it.

### 0:46 · 7s — the console at rest *(live)*

> This is Warrant. It sits between the agent and the payment.

### 0:52 · 30s — what it is *(dark card)*

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

### 1:22 · 20s — instruction becomes permission *(live)*

> So: she says the thing. It becomes a permission with hard ceilings, restated in
> plain English, and she approves that before her key signs anything.
>
> Notice this isn't a new step. Reserve Pay already asks for a PIN. That tap used
> to mean "block a thousand rupees." Now it means "up to a thousand, at Zomato, on
> food, for two hours." Same tap. More meaning.

### 1:41 · 28s — five baskets *(live)*

> Five baskets, one permission. Allowed. Blocked. Blocked. Blocked. Escalated.
>
> **[slow down here]** Look at the third one. That product name is an injected
> instruction — it's telling whatever reads it that the order is pre-approved.
> It's blocked. And look at the header: **no model call.** It never reached a
> model at all. It failed on the category bound.
>
> Delete my injection detector entirely, and it still fails.

### 2:09 · 28s — where the model runs *(dark card)*

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

### 2:36 · 20s — the ledger, then tampering *(live)*

> Every decision is written down — including every refusal. Most systems log what
> they did. A dispute almost always turns on what was declined, and why.
>
> The chain is hash-linked, so let me break it on purpose. That's entry five
> rewritten. Everything from there is orphaned, and it names both hashes so you
> can check it yourself.

### 2:56 · 16s — the dispute pack *(live)*

> And this is what the merchant sends the bank. The exact words the customer said,
> the permission they approved, the basket checked against it, and the signatures
> binding all three to the payment. The bank verifies it against the customer's own
> public key — it doesn't have to trust the merchant's records.

### 3:11 · 12s — AP2 *(live)*

> The fair objection is that Google's AP2 already defines a chained mandate model.
> It does. But AP2 standardises what the credential *is*, not who *checks* it. The
> gate, the judge and the ledger are that gap. Same chain, exported in their
> vocabulary, with the three real divergences carried inside the document.

### 3:23 · 20s — results *(dark card)*

> Five hundred and forty labelled sessions, four policies, one seed.
>
> Warrant stops eighty-two percent of violations and leaks twenty-seven thousand
> seven hundred rupees, against two hundred and eighty-one thousand with no gate at
> all. Decisions take under three hundred microseconds at the median, because this
> sits in the payment path.
>
> And the numbers in the README can't go stale — the build fails if they drift from
> what the code measures.

### 3:42 · 24s — where it loses *(dark card)*

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

### 4:06 · 22s — known limits *(dark card)*

> Three more things I'd want you to know before you believe any of it.
>
> Categories come from the merchant's own catalog. The acquirer's category code
> closes half of that — Zomato can't sell electronics however it tags them. But a
> power bank mislabelled as food *inside* Zomato's catalog still passes. There's a
> test asserting that gap, so nobody later mistakes the fix for a complete one.
>
> A compromised authoriser can still spend the block, because the rail enforces
> amount, not category. This gives detection with attribution — not prevention.
>
> And every number is measured on data this repository generates. That's exactly
> why the losses are printed.
>
> Closing the rest needs the rail itself to enforce scope. Which is precisely the
> layer NPCI's UAP is being designed to occupy.

### 4:27 · 16s — close *(dark card)*

> Two hundred and eleven tests. Eight gates, green from a clean clone. The
> interesting ones exist because a green build didn't catch a real bug — a ledger
> that forked under concurrent writes, six baskets that overspent a hundred-rupee
> mandate, and a detector I'd written that didn't detect the thing it was for. I
> only found that last one because I broke it on purpose to check.
>
> Warrant. No agent spends without one.

---

## If you need to trim

Cut in this order — first to go is the least load-bearing:

1. **2:50 AP2** — the strongest cut. It's an objection-handler, not a demo.
2. **2:30 dispute pack** — you can say the sentence over the ledger footage instead.
3. **0:30 console at rest** — the mandate chain is re-explained on the next card.

**Never cut:** the injected basket at 1:15, or the losses at 3:20. Those two are
why this gets read twice.
