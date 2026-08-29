/** The mandate chain, drawn.
 *
 * This is the architecture the whole product rests on, so a reviewer opening the
 * console cold should be able to read it before touching anything. It is a real
 * diagram of the three documents and who signs each — not decoration, and not a
 * marketing panel. The asymmetry it exists to make obvious: only the person's
 * key can widen what may be spent.
 */

const LINKS = [
  {
    doc: "IntentMandate",
    signer: "the person's device key",
    tone: "root" as const,
    says: "Spend up to ₹1,000 at Zomato on food, for the next 2 hours.",
    note: "The root of trust. Derived from what they said, approved by them in plain English, signed by their key.",
  },
  {
    doc: "CartMandate",
    signer: "the authoriser",
    tone: "attest" as const,
    says: "6 × Masala Chai, 2 × Samosa Plate — ₹480 at Zomato.",
    note: "Attests that this exact basket was checked against that intent and fits inside every bound.",
  },
  {
    doc: "DebitReceipt",
    signer: "the authoriser",
    tone: "attest" as const,
    says: "pay_a1b2c3 settled ₹480 against that cart.",
    note: "Binds the rail payment to the cart and the intent. This is what a dispute is answered with.",
  },
];

export function ChainDiagram() {
  return (
    <section className="explainer">
      <header className="explainer-head">
        <h2>Every rupee an agent spends traces back to a scope a human signed.</h2>
        <p>
          Checked <b>before</b> settlement, provable <b>after</b> dispute. Three documents, each
          binding to the one above it by content address.
        </p>
      </header>

      <ol className="chain">
        {LINKS.map((link, i) => (
          <li className="link" key={link.doc}>
            <div className="link-spine" aria-hidden>
              <span className={`link-node link-node--${link.tone}`} />
              {i < LINKS.length - 1 && <span className="link-thread" />}
            </div>
            <div className="link-body">
              <div className="link-title">
                <code>{link.doc}</code>
                <span className={`link-signer link-signer--${link.tone}`}>
                  signed by {link.signer}
                </span>
              </div>
              <p className="link-says">{link.says}</p>
              <p className="link-note">{link.note}</p>
            </div>
          </li>
        ))}
      </ol>

      <footer className="explainer-foot">
        <p>
          <b>The asymmetry is the point.</b> Only the person's key can widen what may be spent. The
          authoriser can attest that something already permitted was checked — it cannot grant
          authority it was never given. A compromised authoriser can refuse valid baskets, which is
          visible and recoverable; it cannot manufacture a spend nobody sanctioned.
        </p>
      </footer>
    </section>
  );
}
