import { rupees } from "../format";
import type { FeedItem, VerifiedPayment } from "../types";

/** Everything that has been proposed, and what Warrant said about it.
 *
 * This is the product. Not a walkthrough of the product -- the thing itself,
 * running, on one screen. An agent proposes baskets against a permission it
 * cannot read; each one gets a verdict before any money exists; and when a
 * verdict needs a person, the person is right here and gets asked.
 *
 * The console this replaced was four numbered acts with a Next button. It
 * explained the idea well and demonstrated the product badly: you had to
 * navigate to find out what happened, the agent's work and your own were on
 * different screens, and the payment was three clicks from anything.
 */
export function Feed({
  items,
  running,
  busy,
  askAbout,
  onApprove,
  onDecline,
  onPay,
  payments,
  payError,
}: {
  items: FeedItem[];
  running: boolean;
  busy: boolean;
  /** The escalation waiting on a person, if there is one. */
  askAbout: FeedItem | null;
  onApprove: (item: FeedItem) => void;
  onDecline: () => void;
  /** Absent when this deployment has no Razorpay credentials. */
  onPay?: (item: FeedItem) => void;
  payments: Record<string, VerifiedPayment>;
  payError: string | null;
}) {
  return (
    <div className="feed">
      {items.map((item) => (
        <Entry
          key={item.id}
          item={item}
          isAsk={askAbout?.id === item.id}
          busy={busy}
          onApprove={() => onApprove(item)}
          onDecline={onDecline}
          onPay={onPay}
          payment={payments[item.id]}
          payError={payError}
        />
      ))}

      {running && (
        <div className="entry pending">
          <span className="entry-who">
            <span className="glyph agent" aria-hidden>
              AI
            </span>
            Your agent
          </span>
          <p className="entry-thinking">Reading the shop and choosing…</p>
        </div>
      )}
    </div>
  );
}

function Entry({
  item,
  isAsk,
  busy,
  onApprove,
  onDecline,
  onPay,
  payment,
  payError,
}: {
  item: FeedItem;
  isAsk: boolean;
  busy: boolean;
  onApprove: () => void;
  onDecline: () => void;
  onPay?: (item: FeedItem) => void;
  payment?: VerifiedPayment;
  payError: string | null;
}) {
  const { agent, outcome } = item;
  const verdict = outcome.verdict;
  const lines = outcome.cart.line_items;
  const total = outcome.cart.total_paise;
  const settled = outcome.rail?.settled === true;

  return (
    <div className={`entry ${verdict}`}>
      {/* ---------------------------------------------- what was proposed */}
      <div className="entry-head">
        <span className="entry-who">
          <span className={`glyph ${agent ? "agent" : "person"}`} aria-hidden>
            {agent ? "AI" : "YOU"}
          </span>
          {agent ? "Your agent" : "You"}
        </span>
        <span className="entry-total num">{rupees(total)}</span>
      </div>

      {agent?.reasoning && <p className="entry-said">{agent.reasoning}</p>}
      {item.note && !agent && <p className="entry-said">{item.note}</p>}

      <div className="entry-items">
        {lines.map((line, i) => (
          <span className="entry-item" key={`${line.sku}-${i}`}>
            {line.name} <em>×{line.qty}</em>
          </span>
        ))}
      </div>

      {/* ------------------------------------------------- what Warrant said */}
      <div className="entry-verdict">
        <span className={`verdict ${verdict}`}>{VERDICT_WORD[verdict] ?? verdict}</span>
        <span className="entry-meta">
          {outcome.checks.length} checks
          {outcome.gate_us !== undefined && ` · ${Math.round(outcome.gate_us)}µs`}
          {outcome.model_used ? " · a model was consulted" : " · no model was consulted"}
        </span>
      </div>

      {outcome.reasons.length > 0 ? (
        <ul className="entry-reasons">
          {outcome.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      ) : (
        <p className="entry-fine">
          Every bound you signed is satisfied.{" "}
          {settled ? "The money moved." : "The debit was placed."}
        </p>
      )}

      {/* ----------------------------------- what it would have cost, in money */}
      {item.counterfactual && (
        <div className="entry-cost">
          <b>{rupees(item.counterfactual.without.amount_paise)}</b> would have left your
          account with nothing checking, and{" "}
          {item.counterfactual.without.on_dispute.toLowerCase()}
        </div>
      )}

      {/* -------------------------------------------- Warrant asking a person */}
      {isAsk && (
        <div className="ask">
          <p className="ask-said">
            Warrant will not decide this one. It is over the amount you said needs
            your say-so, so it stopped and came back to you — and it cannot approve
            this by itself, and neither can the agent.
          </p>
          <div className="ask-do">
            <button className="btn btn-primary" onClick={onApprove} disabled={busy}>
              {busy ? "Signing…" : `Approve ${rupees(total)} — sign with my key`}
            </button>
            <button className="btn" onClick={onDecline} disabled={busy}>
              No
            </button>
          </div>
        </div>
      )}

      {/* ------------------------------------------------ the real Razorpay leg */}
      {settled &&
        (payment ? (
          <div className="entry-rail paid">
            <span className="paid-tick" aria-hidden>
              ✓
            </span>
            <span>
              <b>Paid on Razorpay</b> — <span className="mono">{payment.payment_id}</span>
              {payment.method && ` · ${payment.method}`}
              {payment.status && ` · ${payment.status}`}
              <em className="paid-note">
                Verified on the server against the key secret, not taken from the
                browser's word.
              </em>
            </span>
          </div>
        ) : (
          onPay && (
            <div className="entry-rail">
              <button className="btn btn-primary" onClick={() => onPay(item)} disabled={busy}>
                {busy ? "Opening Razorpay…" : `Pay ${rupees(total)} on Razorpay`}
              </button>
              <span className="entry-meta">
                Opens Razorpay&rsquo;s real payment sheet, in test mode. Enter a
                mobile number — Razorpay asks for one whatever is prefilled, and
                validates the format — then pick any bank under <b>Netbanking</b>{" "}
                and press <b>Success</b> on the page it opens. Cards are refused as
                international cards, because a test account is an Indian account.
                Nothing is sent to that number, and no real money can move on a
                test key.
              </span>
              {payError && <span className="entry-payerror">{payError}</span>}
            </div>
          )
        ))}
    </div>
  );
}

/** The engine's verdicts, said the way a person would say them. */
const VERDICT_WORD: Record<string, string> = {
  allow: "Allowed",
  block: "Refused",
  escalate: "Needs you",
};
