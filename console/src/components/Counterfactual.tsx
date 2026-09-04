import { rupees } from "../format";
import type { Comparison } from "../types";
import { Basket } from "./icons";
import { Empty } from "./primitives";

/** The same basket in two worlds.
 *
 * A rule name is not a stake. `scope.category → BLOCK` is correct, verifiable,
 * and says nothing about what it was worth. This answers in money: what settles
 * when nothing checks, what evidence exists afterwards, and what happens instead.
 *
 * Neither column is illustrative. The right-hand one is a real evaluation by the
 * same gate everything else uses, against the real mandate in this session.
 */
export function Counterfactual({
  comparison,
  empty,
}: {
  comparison: Comparison | null;
  empty: string;
}) {
  if (!comparison) {
    return (
      <Empty icon={<Basket />} title="Add something to the basket">
        {empty}
      </Empty>
    );
  }

  const { cart } = comparison;
  const stopped = comparison.with.outcome !== "allow";

  return (
    <div className="cf">
      <header className="cf-basket">
        <div className="cf-basket-items">
          {cart.line_items.map((item) => (
            <span key={item.name} className="cf-item">
              <b>{item.name}</b>
              <em>×{item.qty}</em>
              <span className="num">{rupees(item.line_paise, { compact: true })}</span>
            </span>
          ))}
        </div>
        <span className="cf-basket-total num">{rupees(cart.total_paise)}</span>
      </header>

      <div className="cf-columns">
        <section className="cf-col cf-without">
          <h3>Without Warrant</h3>
          {/* A tick inside a red disc, sitting opposite a cross inside a
              green one, inverts for anyone who reads the glyph before the
              colour -- which is everyone. The left column is a warning. */}
          <p className="cf-headline">
            <span className="cf-mark bad" aria-hidden>
              !
            </span>
            Payment captured
          </p>
          <p className="cf-amount num bad">−{rupees(comparison.without.amount_paise)}</p>
          <p className="cf-sub">This is today. Nothing checks the basket.</p>

          <h4>If you dispute it, the merchant has</h4>
          <ul className="cf-evidence">
            {comparison.without.evidence.map((e) => (
              <li key={e.item} className={e.present ? "yes" : "no"}>
                <span aria-hidden>{e.present ? "✓" : "✕"}</span>
                {e.item}
              </li>
            ))}
          </ul>
          <p className="cf-verdict bad">{comparison.without.on_dispute}</p>
        </section>

        <section className={`cf-col cf-with${stopped ? " stopped" : " allowed"}`}>
          <h3>With Warrant</h3>
          <p className="cf-headline">
            <span className={`cf-mark ${stopped ? "good" : "ok"}`} aria-hidden>
              {stopped ? "✕" : "✓"}
            </span>
            {comparison.with.outcome === "block"
              ? "Blocked before settlement"
              : comparison.with.outcome === "escalate"
                ? "Held for the customer"
                : "Authorised"}
          </p>
          <p className={`cf-amount num ${stopped ? "good" : ""}`}>
            {stopped ? rupees(0) : rupees(comparison.with.amount_paise)}
          </p>
          <p className="cf-sub">
            {comparison.with.checks_run} checks ·{" "}
            {comparison.with.model_used ? "model consulted" : "no model call"}
          </p>

          {comparison.with.failed_rules.length > 0 && (
            <ul className="cf-rules">
              {comparison.with.failed_rules.map((r) => (
                <li key={r.rule}>
                  <code>{r.rule}</code>
                  <span>{r.detail}</span>
                </li>
              ))}
            </ul>
          )}

          <h4>If you dispute it, the merchant has</h4>
          <ul className="cf-evidence">
            {comparison.with.evidence.map((e) => (
              <li key={e.item} className={e.present ? "yes" : "no"}>
                <span aria-hidden>{e.present ? "✓" : "✕"}</span>
                {e.item}
              </li>
            ))}
          </ul>
          <p className={`cf-verdict ${stopped ? "good" : ""}`}>{comparison.with.on_dispute}</p>
        </section>
      </div>
    </div>
  );
}
