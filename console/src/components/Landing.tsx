import { ShieldMark } from "./icons";

/** What a judge sees before the workspace.
 *
 * The research pattern for infrastructure products is "proof before promises":
 * one sentence, then a visual that proves the thing exists, then how it fits.
 * So this is not a marketing page — the hero is the counterfactual, because the
 * fastest way to explain a control plane is to show what happens without one.
 *
 * It also has a job the workspace cannot do: telling someone this is a service
 * other software calls, not an app people open. Without that, a viewer lands on
 * a storefront and reasonably wonders why they are shopping.
 */
export function Landing({ onEnter }: { onEnter: () => void }) {
  return (
    <div className="landing">
      <header className="landing-bar">
        <span className="brand">
          <span className="brand-mark">
            <ShieldMark />
          </span>
          <span className="brand-words">
            <b>Warrant</b>
            <span>No agent spends without one</span>
          </span>
        </span>
        <span className="grow" />
        <a
          className="btn btn-ghost btn-sm"
          href="https://github.com/YashwanthKamireddi/warrant"
          target="_blank"
          rel="noreferrer"
        >
          Source ↗
        </a>
        <button className="btn btn-primary btn-sm" onClick={onEnter}>
          Open the workspace
        </button>
      </header>

      <section className="hero">
        <span className="hero-eyebrow">Razorpay AI Buildathon · Track 01</span>
        <h1>
          An AI agent is spending your money.
          <br />
          <span className="quiet">Warrant makes sure it only spends it on what you agreed to.</span>
        </h1>
        <p className="hero-lead">
          Since February 2026, Razorpay and NPCI have run agentic UPI payments in
          production with Zomato, Swiggy and Zepto. <b>UPI Reserve Pay</b> lets you block
          funds once with your PIN — and the agent then debits against that block
          repeatedly, <b>without asking again</b>.
        </p>

        <div className="hero-holes">
          <div className="hole">
            <span className="hole-n">1</span>
            <p>
              <b>Nothing checks what it buys against what you asked for.</b> You said
              “chai and samosas, under ₹1,000”. The block is authorised. What stops a
              ₹499 charge for something nobody asked for?
            </p>
          </div>
          <div className="hole">
            <span className="hole-n">2</span>
            <p>
              <b>When you dispute it, the merchant has no evidence.</b> No device
              fingerprint, no session, no click. Chargeback codes have no category for
              “correctly authorised agent, wrong outcome”. The merchant eats it.
            </p>
          </div>
        </div>
      </section>

      <section className="proof">
        <h2>The same basket, in two worlds</h2>
        <div className="proof-cols">
          <div className="proof-col bad">
            <span className="proof-label">Without Warrant</span>
            <p className="proof-head">Payment captured</p>
            <p className="proof-amount num">−₹199.00</p>
            <ul>
              <li className="no">✕ device fingerprint</li>
              <li className="no">✕ browsing session</li>
              <li className="no">✕ customer click</li>
              <li className="no">✕ signed permission</li>
            </ul>
            <p className="proof-verdict">The merchant absorbs the chargeback.</p>
          </div>
          <div className="proof-col good">
            <span className="proof-label">With Warrant</span>
            <p className="proof-head">Blocked before settlement</p>
            <p className="proof-amount num">₹0.00</p>
            <ul>
              <li className="yes">✓ signed permission</li>
              <li className="yes">✓ checked basket</li>
              <li className="yes">✓ verifiable by the bank</li>
            </ul>
            <p className="proof-verdict">The money never moved.</p>
          </div>
        </div>
      </section>

      <section className="where">
        <h2>Where it sits</h2>
        <p className="where-lead">
          Warrant is not an app people open. It is one API call a merchant’s backend
          makes <b>before</b> it calls Razorpay. If Warrant says no, the payment never
          exists.
        </p>
        <pre className="where-flow">{`  Priya, in the Zomato app
        │  "order chai and samosas for my team, under ₹1,000"
        ▼
  Zomato's AI agent  ──── picks a basket
        │
        ▼
  Zomato's backend  ──── POST /authorize  { permission, basket }
        │                        │
        │                        ▼
        │                   ███ WARRANT ███   allow · block · escalate
        │                        │
        │◄───────────────────────┘
        │
        ├── blocked?  no payment is ever created
        │
        └── allowed?  Zomato calls Razorpay as normal
                              │
                              ▼
                        Razorpay → NPCI → Priya's bank`}</pre>
      </section>

      <section className="who">
        <h2>Who sees what</h2>
        <div className="who-grid">
          <div className="who-card">
            <span className="role-glyph customer" aria-hidden>
              P
            </span>
            <h3>The customer</h3>
            <p>
              <b>One approval screen.</b> “Allow up to ₹1,000 at Zomato for food, for 2
              hours.” Once, at the start. Never again during the session.
            </p>
          </div>
          <div className="who-card">
            <span className="role-glyph agent" aria-hidden>
              AI
            </span>
            <h3>The agent</h3>
            <p>
              <b>Nothing. It is an API.</b> The agent never sees a screen and is never
              told the limits — it only learns why a basket was refused.
            </p>
          </div>
          <div className="who-card">
            <span className="role-glyph merchant" aria-hidden>
              RT
            </span>
            <h3>The merchant’s risk team</h3>
            <p>
              <b>The console.</b> What was blocked and why, the tamper-evident ledger,
              and the evidence pack for a dispute.
            </p>
          </div>
        </div>
      </section>

      <section className="numbers">
        <h2>Measured, and honest about where it fails</h2>
        <div className="numbers-grid">
          <div className="number">
            <span className="n num">81.8%</span>
            <span className="k">violations stopped</span>
          </div>
          <div className="number">
            <span className="n num">₹27,280</span>
            <span className="k">leaked, of ₹281,635 at risk</span>
          </div>
          <div className="number">
            <span className="n num">&lt;300µs</span>
            <span className="k">p50 decision</span>
          </div>
          <div className="number">
            <span className="n num">224</span>
            <span className="k">tests, 9 gates</span>
          </div>
        </div>
        <p className="numbers-note">
          Two categories score near zero and are printed in the same table as the wins —
          baskets inside every signed bound that are still not what was asked for. No
          arithmetic catches those. A benchmark you designed to pass isn’t a benchmark.
        </p>
      </section>

      <section className="enter">
        <h2>Watch it work</h2>
        <p>
          A real model reads the instruction, picks a basket and says why. Warrant checks
          it before any payment exists. If it’s refused, the agent is told the reason —
          never the limits — and tries again.
        </p>
        <button className="btn btn-primary" onClick={onEnter}>
          Open the workspace
        </button>
      </section>

      <footer className="landing-foot">
        <span>Warrant · No agent spends without one</span>
        <a
          href="https://github.com/YashwanthKamireddi/warrant"
          target="_blank"
          rel="noreferrer"
        >
          github.com/YashwanthKamireddi/warrant
        </a>
      </footer>
    </div>
  );
}
