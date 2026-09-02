import { useEffect, useRef } from "react";
import { ShieldMark } from "./icons";

/** The landing page.
 *
 * Built the way a product page is built rather than the way a README is: one
 * idea per viewport, type large enough that the sentence is the design, and
 * nothing in a box. Boxes are for things that need separating from their
 * neighbours; when a screen holds one idea, there is nothing to separate.
 *
 * Every number below is measured, not asserted. `make docs-check` fails the
 * build if any of them drifts from what bench/RESULTS.json actually recorded,
 * which is the only reason a landing page is allowed to quote numbers at all.
 */

/** Reveal on scroll, once, and not at all for anyone who asked for less motion. */
function useReveal() {
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = root.current;
    if (!host) return;

    const targets = host.querySelectorAll<HTMLElement>("[data-reveal]");
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still) {
      targets.forEach((el) => el.setAttribute("data-shown", "true"));
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          (entry.target as HTMLElement).setAttribute("data-shown", "true");
          observer.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.12 },
    );
    targets.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  return root;
}

export function Landing({ onEnter }: { onEnter: () => void }) {
  const root = useReveal();

  return (
    <div className="lp" ref={root}>
      <header className="lp-bar">
        <span className="brand">
          <span className="brand-mark">
            <ShieldMark />
          </span>
          <span className="brand-words">
            <b>Warrant</b>
          </span>
        </span>
        <span className="grow" />
        <a className="lp-link" href="https://github.com/YashwanthKamireddi/warrant">
          Source
        </a>
        <button className="lp-cta" onClick={onEnter}>
          See it work
        </button>
      </header>

      {/* ------------------------------------------------------------ act one */}
      <section className="lp-act lp-open">
        <h1 data-reveal>
          No agent spends
          <br />
          without one.
        </h1>
        <p className="lp-sub" data-reveal>
          An authorization layer for agent-initiated payments. A person says what they
          want once. Everything the agent spends after that is checked against it — before
          the money moves, and provable long after.
        </p>
        <div className="lp-actions" data-reveal>
          <button className="lp-cta lp-cta-lg" onClick={onEnter}>
            See it work
          </button>
          <code className="lp-install">pip install warrant</code>
        </div>
      </section>

      {/* ------------------------------------------------------------ act two */}
      <section className="lp-act lp-gap">
        <p className="lp-kicker" data-reveal>
          The gap
        </p>
        <h2 data-reveal>
          A mandate enforces the amount.
          <br />
          <em>Nothing enforces what it is spent on.</em>
        </h2>
        <p className="lp-body" data-reveal>
          When someone authorises an agent to spend up to a limit, the bank enforces that
          limit and nothing else. It never sees a basket — only a debit. A ceiling is
          equally happy to buy the thing that was asked for and the thing that was not,
          and no fraud signal fires, because nothing here is fraud. The card is real, the
          device is real, the customer is real. It simply is not what they asked for.
        </p>
      </section>

      {/* ---------------------------------------------------------- act three */}
      <section className="lp-act lp-evidence">
        <p className="lp-kicker" data-reveal>
          Measured over 540 labelled cases
        </p>
        <div className="lp-scores">
          <div className="lp-score" data-reveal>
            <span className="lp-score-label">An amount ceiling, alone</span>
            <span className="lp-score-n bad">422</span>
            <span className="lp-score-of">of 540 got through</span>
            <span className="lp-score-money">₹1,55,923 spent outside what was agreed</span>
          </div>
          <div className="lp-score" data-reveal>
            <span className="lp-score-label">With Warrant in front</span>
            <span className="lp-score-n good">90</span>
            <span className="lp-score-of">of 540 got through</span>
            <span className="lp-score-money">₹27,280, and not one wrongful refusal</span>
          </div>
        </div>
        <p className="lp-note" data-reveal>
          Warrant does not catch everything, and the benchmark prints its own misses
          rather than hiding them. What it never does is stop a purchase the person
          actually authorised: <b>zero false stops</b>, across every category.
        </p>
      </section>

      {/* ----------------------------------------------------------- act four */}
      <section className="lp-act lp-chain">
        <p className="lp-kicker" data-reveal>
          How
        </p>
        <h2 data-reveal>Three documents, each one binding the next.</h2>
        <ol className="lp-links">
          <li data-reveal>
            <span className="lp-link-n">01</span>
            <h3>The permission</h3>
            <p>
              What the person said, and the limits derived from it — amount, merchant,
              category, count, window. Signed by their own device key. Nothing else in the
              system can widen it.
            </p>
          </li>
          <li data-reveal>
            <span className="lp-link-n">02</span>
            <h3>The basket</h3>
            <p>
              What the agent actually proposes to buy, checked line by line against the
              permission it names. Signed only once it passes, and bound to that exact
              permission by content address.
            </p>
          </li>
          <li data-reveal>
            <span className="lp-link-n">03</span>
            <h3>The payment</h3>
            <p>
              The rail's own reference for the money that moved, bound to the basket that
              justified it. A payment with no basket behind it is a payment nobody
              authorised, and it is visible as one.
            </p>
          </li>
        </ol>
        <p className="lp-note" data-reveal>
          Every decision — including every refusal — is appended to a hash-chained ledger.
          Editing any earlier entry breaks every entry after it, which the console will let
          you try.
        </p>
      </section>

      {/* ----------------------------------------------------------- act five */}
      <section className="lp-act lp-specs">
        <p className="lp-kicker" data-reveal>
          The parts that matter
        </p>
        <dl className="lp-spec-grid">
          <div data-reveal>
            <dt>No model decides</dt>
            <dd>
              The gate is a pure function of the signed documents and the state. A language
              model can propose and can advise, and cannot change a verdict. Prompt
              injection in a product name is inert by construction, not by filtering.
            </dd>
          </div>
          <div data-reveal>
            <dt>Refusals are records</dt>
            <dd>
              A blocked purchase is written to the ledger with its reasons, the same as an
              allowed one. A control plane that only logs its successes cannot be audited.
            </dd>
          </div>
          <div data-reveal>
            <dt>Your merchants, not ours</dt>
            <dd>
              The acquirer's book of underwritten merchants and their ISO 18245 codes is a
              file you supply. A merchant does not write its own category, so it cannot
              relabel its way into a mandate it was not underwritten for.
            </dd>
          </div>
          <div data-reveal>
            <dt>Checked before, provable after</dt>
            <dd>
              The decision happens before settlement, and the evidence pack that comes out
              the other side is what a merchant files when a customer disputes the charge.
              Exportable as AP2 / W3C Verifiable Credentials.
            </dd>
          </div>
        </dl>
      </section>

      {/* ------------------------------------------------------------ act six */}
      <section className="lp-act lp-end">
        <h2 data-reveal>See it refuse something.</h2>
        <p className="lp-sub" data-reveal>
          Four screens. A signed permission, a live agent that gets refused and adapts, the
          money it would have cost, and the record afterwards.
        </p>
        <div className="lp-actions" data-reveal>
          <button className="lp-cta lp-cta-lg" onClick={onEnter}>
            Open the workspace
          </button>
        </div>
      </section>

      <footer className="lp-foot">
        <span>Warrant · an authorization layer for agent-initiated payments</span>
        <span className="grow" />
        <a href="https://github.com/YashwanthKamireddi/warrant">github.com/YashwanthKamireddi/warrant</a>
      </footer>
    </div>
  );
}
