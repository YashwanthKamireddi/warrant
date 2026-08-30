# Testing the console

## Look at it yourself

```bash
make open          # builds, serves, and opens your browser
```

or, if you want to control the browser yourself:

```bash
make console       # builds and serves at http://127.0.0.1:8787
```

Then walk it in this order — it is the same order the pitch video follows:

| # | do this | what to look at |
| --- | --- | --- |
| 1 | Read the first screen | The mandate chain, drawn. Three documents, who signs each. |
| 2 | **Derive the permission** | The instruction becomes a certificate with hard ceilings, restated in plain English. |
| 3 | **Approve and sign** | The bronze seal stamps. The mandate strip comes alive with live gauges. |
| 4 | **Run five scripted baskets** | ALLOW, BLOCK, BLOCK, BLOCK, ESCALATE. Expand each one. |
| 5 | Expand the injected basket (#3) | Blocked on `scope.category`, with `no model call` in the header. The payload never reached a model. |
| 6 | Build your own basket | Add a Power Bank — watch it block. Add the Catering Tray — watch it escalate and offer co-signature. |
| 7 | **Ledger** tab | Every decision, including the refusals. Refusals are rows, not silences. |
| 8 | **Dispute evidence** tab | The full submission a merchant sends the bank. |
| 9 | **Tamper with the ledger** (status bar) | Entry 5 and everything after it goes striped. The status bar turns red. The evidence pack refuses to vouch for it. |

To poke at the API directly while you do this: `http://127.0.0.1:8787/docs`.

## Have the machine check it

```bash
make verify        # everything, in order, fails on the first problem
```

| gate | what it proves | run alone |
| --- | --- | --- |
| `lint` | ruff over engine, bench, tests | `make lint` |
| `test` | 82 tests | `make test` |
| `typecheck` | the console compiles under `strict` | `make typecheck` |
| `audit-tokens` | no colour outside `:root`, no undefined token, no hex in a component | `make audit-tokens` |
| `audit-contrast` | all 29 rendered pairs meet WCAG AA, computed from the tokens | `make audit-contrast` |
| `audit-overlap` | nothing spills its box or paints over a sibling, across 6 states | `make audit-overlap` |
| `browser` | frame holds at 5 viewports, real flow runs, no console errors | `make browser` |

Screenshots of every state land in `.verify/shots/`.

## Why these gates exist

`npm run build` proves the TypeScript compiled. It says nothing about whether the
page renders, whether the API answers, or whether anything throws at runtime.
Each of these was written after a real bug that a green build did not catch:

- **the storefront had drifted by one SKU** between two files, so the console's
  scripted run died on a 400 while all 75 backend tests passed
  → `tests/test_catalog.py` now guards that seam, and `walk.py` asserts the
  console's verdicts match what `warrant demo` prints
- **the top bar said "credentials configured"** while actually replaying a
  transcript — an expired token constructs a client fine and fails at call time
  → the chip now reports the path the last interpretation really took
- **a component rendered `className="signer seal"`**, and `seal` was a standalone
  rule elsewhere setting a 46px circle, so the label was clamped and its text
  spilled across the content beneath it
  → `audit_overlap.py`

That last one is worth reading in full, because the first detector written for it
did not work. Sibling-box overlap does not catch a cascade collision: overflowing
text does not change its element's bounding box. The check that does catch it is
*content larger than its own box while overflow is visible*. That was confirmed
by reintroducing the bug and watching the detector name it:

```
span.link-signer.seal spills 145x0px outside its box
```

If you change the detector, prove it the same way — break the thing on purpose
and check that it fails.

## Adding a component

Two things to keep the gates meaningful:

1. **Never write a raw colour.** Every value comes from `:root`. `audit-tokens`
   fails the build otherwise.
2. **Add its foreground/background pair to `PAIRS` in `audit_contrast.py`.** The
   audit checks pairs the interface actually paints, so a new surface that nobody
   declares is a new surface nobody checked.
