import { useEffect, useRef } from "react";
import { ShieldMark } from "./icons";

/** The landing page.
 *
 * One idea per viewport, type large enough that the sentence is the design.
 *
 * The version this replaced opened on "No agent spends without one." -- a good
 * line for someone who already knows what the product is, and four words that
 * tell a first-time reader nothing, above three lines of category prose. A
 * judge with sixty seconds could not have said what the software did. It says
 * what happens now, in the order it happens, and gets out of the way.
 *
 * Every number below is measured, not asserted, and `make docs-check` fails the
 * build if any of them drifts from what bench/RESULTS.json recorded -- which is
 * the only reason a landing page is allowed to quote numbers at all.
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
          Your agent
          <br />
          has your money.
        </h1>
        <p className="lp-sub" data-reveal>
          Say what you want once. It becomes a permission signed by your own key —
          an amount, a merchant, a category, a deadline. Every basket the agent
          proposes is checked against it <em>before</em> the money moves.
        </p>
        <div className="lp-actions" data-reveal>
          <button className="lp-cta lp-cta-lg" onClick={onEnter}>
            Watch it refuse something
          </button>
          <span className="lp-under">
            Runs live against a real shop&rsquo;s catalogue and Razorpay test mode.
          </span>
        </div>
      </section>

      {/* ------------------------------------------------------------ act two */}
      <section className="lp-act lp-gap">
        <p className="lp-kicker" data-reveal>
          The hole
        </p>
        <h2 data-reveal>
          A mandate enforces the amount.
          <br />
          <em>Nothing enforces what it is spent on.</em>
        </h2>
        <p className="lp-body" data-reveal>
          The bank never sees a basket, only a debit. A ceiling is equally happy to
          buy the thing you asked for and the thing you did not — and no fraud
          signal fires, because none of this is fraud. Real card, real device, real
          customer. Just not what they asked for.
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
            <span className="lp-score-n bad">416</span>
            <span className="lp-score-of">of 540 got through</span>
            <span className="lp-score-money">₹1,69,825 spent outside what was agreed</span>
          </div>
          <div className="lp-score" data-reveal>
            <span className="lp-score-label">With Warrant in front</span>
            <span className="lp-score-n good">90</span>
            <span className="lp-score-of">of 540 got through</span>
            <span className="lp-score-money">₹30,208, and not one wrongful refusal</span>
          </div>
        </div>
        <p className="lp-note" data-reveal>
          One seed, four policies, and the two categories Warrant scores zero on are
          printed in the same table as the wins. A benchmark you designed to pass is
          not a benchmark.
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
              What you said, and the limits derived from it. Signed by your own
              device key. Nothing else in the system can widen it.
            </p>
          </li>
          <li data-reveal>
            <span className="lp-link-n">02</span>
            <h3>The basket</h3>
            <p>
              What the agent proposes, checked line by line against the permission
              it names, and signed only once it passes.
            </p>
          </li>
          <li data-reveal>
            <span className="lp-link-n">03</span>
            <h3>The payment</h3>
            <p>
              The rail&rsquo;s own reference for the money that moved, bound to the
              basket that justified it. A payment with no basket behind it is
              visible as one.
            </p>
          </li>
        </ol>
        <p className="lp-note" data-reveal>
          Every decision — including every refusal — is appended to a hash-chained
          ledger. Edit an earlier entry and every entry after it orphans, which the
          console will let you try.
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
              The gate is a pure function of the signed documents. A model can
              propose and advise; it cannot change a verdict. Prompt injection in a
              product name is inert by construction, not by filtering.
            </dd>
          </div>
          <div data-reveal>
            <dt>Refusals are records</dt>
            <dd>
              A blocked purchase is written down with its reasons, the same as an
              allowed one. A control plane that logs only its successes cannot be
              audited.
            </dd>
          </div>
          <div data-reveal>
            <dt>Categories you don&rsquo;t control</dt>
            <dd>
              A merchant&rsquo;s ISO 18245 code is assigned by its acquirer, so it
              cannot relabel its way into a mandate it was never underwritten for.
            </dd>
          </div>
          <div data-reveal>
            <dt>Provable afterwards</dt>
            <dd>
              The decision happens before settlement, and what comes out is what a
              merchant files when a customer disputes the charge. Exportable as AP2
              / W3C Verifiable Credentials.
            </dd>
          </div>
        </dl>
      </section>

      {/* ------------------------------------------------------------ act six */}
      <section className="lp-act lp-end">
        <h2 data-reveal>See it refuse something.</h2>
        <p className="lp-sub" data-reveal>
          A signed permission, a live model that gets refused and works out why, the
          money it would have cost, and a real Razorpay payment at the end of it.
        </p>
        <div className="lp-actions" data-reveal>
          <button className="lp-cta lp-cta-lg" onClick={onEnter}>
            Open the console
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
